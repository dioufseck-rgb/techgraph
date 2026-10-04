"""The four Stage 1 experiments."""
from dataclasses import replace
from typing import Dict, List

from .catalog import Scenario
from .analysis import (INCUMBENT_LANDSCAPE, CANDIDATES, verified, incumbent, J,
                       operating_prices, screen, bundle_values)
from .model import solve

FUEL_ONLY = ("GEN_D", "GEN_R", "FUEL_TRANS", "LINE_RH", "LINE_HD", "FUEL_STORE_D")
MULTS = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0]


def _scale(sc: Scenario, name: str, m: float) -> Scenario:
    d = sc.designs[name]
    return sc.with_designs(**{name: dict(annual_cost=d.annual_cost * m, fixed_cost=d.fixed_cost * m)})


def _delivered_route_shares(sc: Scenario, r) -> Dict[str, float]:
    """Share of fuel-based electricity made at the source (GEN_R) vs at the load (GEN_D)."""
    H = sc.hours
    gen_r = H * sum(r.activity.get("GEN_R", {}).get("output", [0] * sc.periods))
    gen_d = H * sum(r.activity.get("GEN_D", {}).get("output", [0] * sc.periods))
    tot = gen_r + gen_d
    return {"process_then_transport": gen_r / tot if tot else 0.0,
            "transport_then_process": gen_d / tot if tot else 0.0}


# ---------------------------------------------------------------- E1 -------
def e1_order_of_operations(sc: Scenario) -> List[dict]:
    """C2, part a: fuel-only world. Vary electricity-line cost against fuel-transport
    cost and record whether fuel is processed at the source or at the load."""
    rows = []
    for ml in MULTS:
        for mf in MULTS:
            s = _scale(_scale(sc, "LINE_RH", ml), "FUEL_TRANS", mf)
            r = verified(s, solve(s, FUEL_ONLY))
            rows.append({"line_mult": ml, "fuel_transport_mult": mf,
                         "cost_per_day": r.objective,
                         **_delivered_route_shares(s, r)})
    return rows


def e1_transport_vs_storage(sc: Scenario) -> List[dict]:
    """C2, part b: full landscape. Vary remote-line cost against battery cost."""
    rows = []
    H = sc.hours
    for ml in MULTS:
        for mb in MULTS:
            s = _scale(_scale(sc, "LINE_RH", ml), "BATT_H", mb)
            r = verified(s, solve(s, s.designs.keys()))
            gen = {k: H * sum(v.get("output", [0])) for k, v in r.activity.items() if "output" in v}
            tot = sum(gen.values())
            remote = sum(v for k, v in gen.items() if s.designs[k].loc == "R")
            rows.append({"line_mult": ml, "battery_mult": mb,
                         "cost_per_day": r.objective,
                         "remote_share": remote / tot if tot else 0.0,
                         "line_RH_MW": r.capacity.get("LINE_RH", 0.0),
                         "battery_MWh": r.capacity.get("BATT_H", 0.0),
                         "emissions_t": r.emissions})
    return rows


# ---------------------------------------------------------------- E2 -------
def e2_bottleneck_sequence(sc: Scenario, fuel_path=(25, 35, 45, 55, 65, 75, 85, 100),
                           max_bundle=3, min_value=100.0) -> List[dict]:
    """C1: start from the incumbent system. As the fuel price rises by steps, read
    state prices, screen candidates, value singles and bundles, adopt the best action,
    and record where scarcity moves."""
    existing = dict(incumbent(sc).capacity)
    base = set(INCUMBENT_LANDSCAPE)
    log = []
    for fp in fuel_path:
        s = replace(sc, fuel_price_R=fp)
        while True:
            priced = operating_prices(s, existing)
            remaining = [c for c in CANDIDATES if c not in base]
            scr = screen(s, priced, remaining) if remaining else {}
            vals = bundle_values(s, existing, base, remaining, max_size=max_bundle) if remaining else {}
            best_v = max(vals.values()) if vals else 0.0
            entry = {
                "fuel_price": fp,
                "prices_D": [priced.prices.get(("elec", "D", t)) for t in range(s.periods)],
                "prices_H": [priced.prices.get(("elec", "H", t)) for t in range(s.periods)],
                "emissions_t": priced.emissions,
                "forward_cost": priced.objective,
                "screen": scr,
                "top_screened": max(scr, key=scr.get) if scr else None,
                "singles_positive": {b[0]: v for b, v in vals.items() if len(b) == 1 and v > min_value},
                "adopted": None, "value": 0.0,
            }
            if best_v <= min_value:
                entry["capacity_after"] = dict(existing)
                log.append(entry)
                break
            # smallest bundle within 0.5% of the best value
            ok = [b for b, v in vals.items() if v >= best_v * 0.995]
            chosen = min(ok, key=lambda b: (len(b), -vals[b]))
            r = J(s, existing, base | set(chosen))
            entry["adopted"], entry["value"] = chosen, vals[chosen]
            existing = dict(r.capacity)
            entry["capacity_after"] = dict(existing)
            log.append(entry)
            base |= set(chosen)
    final = operating_prices(replace(sc, fuel_price_R=fuel_path[-1]), existing)
    log.append({"fuel_price": fuel_path[-1], "final_capacity": existing,
                "emissions_t": final.emissions})
    return log


# ---------------------------------------------------------------- E3 -------
def e3_bundles(sc: Scenario, fuel_price=60.0) -> Dict[tuple, dict]:
    """Complementarity: V for singles and pairs at the incumbent, with superadditivity
    S(A,B) = V(A u B) - V(A) - V(B), and the dual screening signal for singles."""
    s = replace(sc, fuel_price_R=fuel_price)
    existing = dict(incumbent(sc).capacity)
    vals = bundle_values(s, existing, INCUMBENT_LANDSCAPE, CANDIDATES, max_size=3)
    scr = screen(s, operating_prices(s, existing), CANDIDATES)
    out = {}
    for b, v in vals.items():
        row = {"value": v}
        if len(b) == 1:
            row["screen"] = scr[b[0]]
        else:
            row["superadditivity"] = v - sum(vals[(x,)] for x in b)
        out[b] = row
    return out


# ---------------------------------------------------------------- E4 -------
def shocks(sc: Scenario) -> Dict[str, Scenario]:
    evening = list(sc.demand_D)
    evening[3] *= 1.4
    prof = dict(sc.profiles)
    prof["solar_R"] = [x * 0.6 for x in prof["solar_R"]]
    return {
        "fuel price x3": replace(sc, fuel_price_R=sc.fuel_price_R * 3),
        "evening demand +40%": replace(sc, demand_D=evening),
        "remote solar -40%": replace(sc, profiles=prof),
    }


def e4_resource_shocks(sc: Scenario) -> dict:
    """Shocks to resources and requirements after a system is built. Compare adapting
    the installed system (brownfield) with building afresh (greenfield)."""
    all_d = list(sc.designs.keys())
    base = verified(sc, solve(sc, all_d))
    installed = dict(base.capacity)
    out = {"baseline": {"capacity": installed, "cost": base.objective, "emissions_t": base.emissions}}
    for label, s in shocks(sc).items():
        brown = verified(s, solve(s, all_d, existing=installed))
        green = verified(s, solve(s, all_d))
        H = s.hours
        idle = {}
        for k, cap in installed.items():
            if cap <= 1e-6:
                continue
            ser = brown.activity.get(k, {})
            key = "output" if "output" in ser else ("forward" if "forward" in ser else "discharge")
            use = sum(ser.get(key, [0])) + sum(ser.get("backward", [0]))
            idle[k] = use * H  # MWh/day moved or produced by the originally installed design
        out[label] = {
            "brownfield_cost": brown.objective,
            "brownfield_new_capacity": {k: v for k, v in brown.new_capacity.items() if v > 1e-3},
            "brownfield_emissions_t": brown.emissions,
            "greenfield_cost": green.objective,
            "greenfield_capacity": {k: v for k, v in green.capacity.items() if v > 1e-3},
            "greenfield_emissions_t": green.emissions,
            "installed_throughput_MWh": idle,
        }
    return out
