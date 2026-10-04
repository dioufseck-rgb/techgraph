"""Robustness and extension experiments (R1-R5) on the Stage 1 world."""
from dataclasses import replace
import numpy as np

from .catalog import Scenario, default_scenario
from .analysis import (INCUMBENT_LANDSCAPE, CANDIDATES, incumbent, operating_prices,
                       screen, bundle_values, verified, generation_mix, architecture_label,
                       capacity_rent_fd)
from .experiments import e2_bottleneck_sequence, e4_resource_shocks
from .model import solve

FUEL_PATH = (25, 35, 45, 55, 65, 75, 85, 100)


def perturb(sc: Scenario, rng, sigma=0.3) -> Scenario:
    """Independent lognormal multipliers on each design's costs; renewable
    profiles scaled by independent factors in [0.8, 1.2]."""
    ups = {}
    for n, d in sc.designs.items():
        m = float(np.exp(rng.normal(0, sigma)))
        ups[n] = dict(annual_cost=d.annual_cost * m, fixed_cost=d.fixed_cost * m)
    s = sc.with_designs(**ups)
    prof = {k: [min(1.0, x * rng.uniform(0.8, 1.2)) for x in v] for k, v in sc.profiles.items()}
    return replace(s, profiles=prof)


def path_cost(sc, log, incumbent_cap, fom_share=0.2):
    """Cost of a whole adoption path: for each fuel-price epoch, operating cost at that
    price, plus fixed O&M on the incumbent, plus the full annualized cost of every unit
    added since the start. Unlike forward cost, this does not hide past investment."""
    by_fp = {}
    for e in log:
        if "capacity_after" in e:
            by_fp[e["fuel_price"]] = e["capacity_after"]
    total = 0.0
    for fp, cap in by_fp.items():
        r = operating_prices(replace(sc, fuel_price_R=fp), cap)
        op = r.objective - r.costs["existing_fom"]
        cap_cost = 0.0
        for n, c in cap.items():
            d = sc.designs[n]
            inc = min(c, incumbent_cap.get(n, 0.0))
            add = max(0.0, c - inc)
            cap_cost += sc.days * (fom_share * d.annual_cost * inc + d.annual_cost * add) / 365.0
            if add > 1e-6 and incumbent_cap.get(n, 0.0) <= 1e-6:
                cap_cost += sc.days * d.fixed_cost / 365.0
        total += op + cap_cost
    return total / len(by_fp)


def summarize_e2(sc, log):
    steps = [e for e in log if "final_capacity" not in e]
    adopted = [e for e in steps if e["adopted"]]
    first = adopted[0] if adopted else None
    final_cap = log[-1]["final_capacity"]
    final = operating_prices(replace(sc, fuel_price_R=FUEL_PATH[-1]), final_cap)
    return {
        "switch_price": first["fuel_price"] if first else None,
        "first_action": "+".join(first["adopted"]) if first else None,
        "first_is_bundle": bool(first and len(first["adopted"]) > 1),
        "n_adoptions": len(adopted),
        "final_forward_cost": final.objective,
        "final_emissions": final.emissions,
        "final_arch": architecture_label(sc, final),
        "final_capacity": final_cap,
        "path_cost": path_cost(sc, log, incumbent(sc).capacity),
    }


def r1_r2_monte_carlo(n=150, seed=7, sigma=0.3):
    """R1: robustness of lock-in and policy effects. R2: prevalence of complementarity."""
    rng = np.random.default_rng(seed)
    base = default_scenario()
    rows = []
    for i in range(n):
        sc = perturb(base, rng, sigma)
        green = verified(sc, solve(sc, sc.designs.keys()))
        inc = incumbent(sc)
        A = summarize_e2(sc, e2_bottleneck_sequence(sc, FUEL_PATH, max_bundle=1))
        B = summarize_e2(sc, e2_bottleneck_sequence(sc, FUEL_PATH, max_bundle=3))
        # complementarity at the incumbent, fuel price 60
        s60 = replace(sc, fuel_price_R=60.0)
        vals = bundle_values(s60, inc.capacity, INCUMBENT_LANDSCAPE, CANDIDATES, max_size=3)
        scr = screen(s60, operating_prices(s60, inc.capacity), CANDIDATES)
        singles = {b[0]: v for b, v in vals.items() if len(b) == 1}
        best_single = max(singles.values())
        best_b, best_v = max(vals.items(), key=lambda kv: kv[1])
        best_min = min((b for b, v in vals.items() if v >= best_v * 0.995), key=len)
        super_add = best_v - sum(singles[x] for x in best_min)
        members_neg_screen = [x for x in best_min if scr[x] < 0]
        top_screen = max(scr, key=scr.get)
        best_single_name = max(singles, key=singles.get)
        rows.append({
            "draw": i,
            "greenfield_arch": architecture_label(sc, green),
            "greenfield_remote_share": sum(v for k, v in generation_mix(sc, green).items()
                                           if sc.designs[k].loc == "R"),
            "greenfield_emissions": green.emissions,
            "incumbent_arch": architecture_label(sc, inc),
            **{f"A_{k}": v for k, v in A.items() if k != "final_capacity"},
            **{f"B_{k}": v for k, v in B.items() if k != "final_capacity"},
            "c_best_single": best_single,
            "c_best_value": best_v,
            "c_best_is_bundle": len(best_min) > 1 and best_v > best_single * 1.01,
            "c_best_action": "+".join(best_min),
            "c_superadditivity": super_add,
            "c_members_negative_screen": len(members_neg_screen),
            "c_bundle_size": len(best_min),
            "c_screen_top_equals_best_single": (top_screen == best_single_name) if best_single > 1 else None,
            "c_any_positive_screen": max(scr.values()) > 0,
            "c_any_positive_single": best_single > 1,
        })
    return rows


def r3_hysteresis(sc=None):
    """R3: fuel price rises and then falls back. Does the system return?"""
    sc = sc or default_scenario()
    path = (25, 45, 65, 85, 100, 85, 65, 45, 25)
    out = {}
    for label, mb in (("A", 1), ("B", 3)):
        log = e2_bottleneck_sequence(sc, path, max_bundle=mb)
        cap = log[-1]["final_capacity"]
        end = operating_prices(replace(sc, fuel_price_R=25), cap)
        out[label] = {"end_forward_cost": end.objective, "end_emissions": end.emissions,
                      "end_arch": architecture_label(sc, end)}
    inc = incumbent(sc)
    inc_op = operating_prices(sc, inc.capacity)
    green = verified(sc, solve(sc, sc.designs.keys()))
    out["incumbent_at_25"] = {"forward_cost": inc_op.objective, "emissions": inc_op.emissions,
                              "arch": architecture_label(sc, inc_op)}
    out["greenfield_at_25"] = {"total_cost": green.objective, "emissions": green.emissions,
                               "arch": architecture_label(sc, green)}
    return out


def r4_capacity_scarcity(sc=None):
    """R4: where is scarcity once operating prices are zero? Finite-difference rents."""
    sc = sc or default_scenario()
    s100 = replace(sc, fuel_price_R=100)
    out = {}
    for label, mb in (("A", 1), ("B", 3)):
        cap = e2_bottleneck_sequence(sc, FUEL_PATH, max_bundle=mb)[-1]["final_capacity"]
        pr = operating_prices(s100, cap)
        rents = {}
        for n, c in cap.items():
            if c > 1e-6:
                up, dn = capacity_rent_fd(s100, cap, n, delta=1.0)
                rents[n] = {"capacity": c, "value_one_more": up, "cost_one_less": dn,
                            "daily_capacity_cost": sc.designs[n].annual_cost / 365.0}
        out[label] = {"max_elec_price": max(v for k, v in pr.prices.items() if k[0] == "elec"), "rents": rents}
    return out


def two_day_lull() -> Scenario:
    """Two representative days: a normal day and a calm, cloudy day."""
    sc = default_scenario()
    prof = {
        "solar_R": sc.profiles["solar_R"] + [x * 0.5 for x in sc.profiles["solar_R"]],
        "solar_D": sc.profiles["solar_D"] + [x * 0.5 for x in sc.profiles["solar_D"]],
        "wind_R": sc.profiles["wind_R"] + [x * 0.2 for x in sc.profiles["wind_R"]],
    }
    return replace(sc, periods=8, demand_D=sc.demand_D * 2, hub_energy=sc.hub_energy * 2,
                   profiles=prof, days=2.0)


def r5_two_day(sc2=None):
    """R5: rerun the main findings in the two-day world with a calm, cloudy day."""
    sc2 = sc2 or two_day_lull()
    green = verified(sc2, solve(sc2, sc2.designs.keys()))
    inc = incumbent(sc2)
    A = summarize_e2(sc2, e2_bottleneck_sequence(sc2, FUEL_PATH, max_bundle=1))
    B = summarize_e2(sc2, e2_bottleneck_sequence(sc2, FUEL_PATH, max_bundle=3))
    shocks = e4_resource_shocks(sc2)
    return {
        "greenfield": {"cost_per_day": green.objective / 2, "arch": architecture_label(sc2, green),
                       "emissions_per_day": green.emissions / 2,
                       "capacity": {k: v for k, v in green.capacity.items() if v > 1e-3}},
        "incumbent_arch": architecture_label(sc2, inc),
        "A": {k: v for k, v in A.items() if k != "final_capacity"},
        "B": {k: v for k, v in B.items() if k != "final_capacity"},
        "A_final_capacity": A["final_capacity"], "B_final_capacity": B["final_capacity"],
        "shocks": {k: {kk: vv for kk, vv in v.items() if kk in (
            "brownfield_new_capacity", "greenfield_capacity",
            "brownfield_emissions_t", "greenfield_emissions_t", "installed_throughput_MWh")}
            for k, v in shocks.items() if k != "baseline"},
        "baseline_capacity": {k: v for k, v in shocks["baseline"]["capacity"].items() if v > 1e-3},
    }
