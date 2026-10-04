"""Distributed demand: the same total demand spread across R, H and D."""
from dataclasses import replace
from itertools import combinations
from typing import Dict, List

from .catalog import Scenario, Design, default_scenario
from .model import solve
from .analysis import verified, operating_prices, screen, generation_mix, architecture_label
from .robustness import path_cost, FUEL_PATH, two_day_lull

# The legacy landscape now includes local solar at the hub and the remote line,
# so a legacy grid can reach demand wherever it is.
LEGACY = ("GEN_D", "FUEL_TRANS", "FUEL_STORE_D", "SOLAR_D", "SOLAR_H", "LINE_HD", "LINE_RH")
SOLAR_H = Design("SOLAR_H", "renewable", annual_cost=75_000, loc="H", profile="solar_D")


def dist_scenario(sc: Scenario, s: float) -> Scenario:
    """Move a share s of demand at D to R and H in equal parts (same profile)."""
    designs = dict(sc.designs); designs["SOLAR_H"] = SOLAR_H
    base = list(sc.demand_D)
    extra = {"R": [x * s / 2 for x in base], "H": [x * s / 2 for x in base]} if s > 0 else {}
    return replace(sc, designs=designs, demand_D=[x * (1 - s) for x in base], extra_demand=extra)


def metrics(sc: Scenario, res) -> dict:
    H = sc.hours
    firm = H * (sum(sc.demand_D) + sum(sum(v) for v in sc.extra_demand.values())) + sc.hub_energy
    line_delivered = 0.0
    for n in ("LINE_RH", "LINE_HD"):
        d = sc.designs[n]; ser = res.activity.get(n, {})
        line_delivered += H * (1 - d.loss) * (sum(ser.get("forward", [0])) + sum(ser.get("backward", [0])))
    mix = generation_mix(sc, res)
    through_hub = 0.0
    for n in ("LINE_RH", "LINE_HD"):
        ser = res.activity.get(n, {})
        # energy entering the hub over lines
        if n == "LINE_RH":
            through_hub += H * (1 - sc.designs[n].loss) * sum(ser.get("forward", [0]))
        else:
            through_hub += H * (1 - sc.designs[n].loss) * sum(ser.get("backward", [0]))
    active_edges = sum(1 for n, ser in res.activity.items()
                       if any(sum(v) > 1e-3 for k, v in ser.items() if k != "level"))
    return {
        "cost_per_day": res.objective / sc.days,
        "emissions_per_day": res.emissions / sc.days,
        "arch": architecture_label(sc, res),
        "remote_gen_share": sum(v for k, v in mix.items() if sc.designs[k].loc == "R"),
        "transported_share": line_delivered / firm,
        "hub_inflow_share": through_hub / firm,
        "line_MW": res.capacity.get("LINE_RH", 0.0) + res.capacity.get("LINE_HD", 0.0),
        "battery_MWh": res.capacity.get("BATT_H", 0.0),
        "active_modules": active_edges,
        "capacity": {k: v for k, v in res.capacity.items() if v > 1e-3},
    }


def adoption_sequence(sc: Scenario, path=FUEL_PATH, max_bundle=3, min_value=100.0):
    """As e2, but the actor may expand anything it has installed; every design it
    does not yet have is a candidate. Returns (log, incumbent capacity)."""
    inc = verified(sc, solve(sc, LEGACY))
    existing = dict(inc.capacity)
    log = []
    for fp in path:
        s = replace(sc, fuel_price_R=fp)
        while True:
            base = {n for n, c in existing.items() if c > 1e-6}
            cands = [n for n in s.designs if n not in base]
            priced = operating_prices(s, existing)
            r0 = verified(s, solve(s, base, existing=existing)).objective
            vals = {}
            for k in range(1, max_bundle + 1):
                for b in combinations(cands, k):
                    vals[b] = r0 - verified(s, solve(s, base | set(b), existing=existing)).objective
            best_v = max(vals.values()) if vals else 0.0
            entry = {"fuel_price": fp, "emissions": priced.emissions / s.days,
                     "active_states": sorted(f"{k[0]}@{k[1]}" for k in {(n[0], n[1]) for n in priced.prices}),
                     "adopted": None, "value": 0.0}
            if best_v <= min_value:
                entry["capacity_after"] = dict(existing)
                log.append(entry); break
            ok = [b for b, v in vals.items() if v >= best_v * 0.995]
            chosen = min(ok, key=lambda b: (len(b), -vals[b]))
            r = verified(s, solve(s, base | set(chosen), existing=existing))
            existing = dict(r.capacity)
            entry.update(adopted=chosen, value=vals[chosen], capacity_after=dict(existing))
            log.append(entry)
    return log, inc.capacity


def summarize(sc, log, inc_cap):
    adopted = [e for e in log if e["adopted"]]
    final_cap = log[-1]["capacity_after"]
    final = operating_prices(replace(sc, fuel_price_R=FUEL_PATH[-1]), final_cap)
    return {
        "switch_price": adopted[0]["fuel_price"] if adopted else None,
        "first_action": "+".join(adopted[0]["adopted"]) if adopted else None,
        "first_is_bundle": bool(adopted and len(adopted[0]["adopted"]) > 1),
        "actions": ["+".join(e["adopted"]) + f" @{e['fuel_price']}" for e in adopted],
        "path_cost_per_day": path_cost(sc, log, inc_cap) / sc.days,
        "final_emissions_per_day": final.emissions / sc.days,
        "final_arch": architecture_label(sc, final),
        "final_capacity": {k: v for k, v in final_cap.items() if v > 1e-3},
    }
