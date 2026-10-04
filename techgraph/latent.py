"""Stage 3b: a latent catalog revealed on a schedule (technological determinism as a
first approach). Every design exists in the feasibility space from the start; it
becomes available at its arrival epoch. Learning with spillovers stays on, so the
order of arrivals can interact with increasing returns."""
import math
from dataclasses import replace
from typing import Dict
import numpy as np

from .catalog import Design
from .analysis import incumbent
from .dynamic import Trajectory, Params, Vintage, solve_window
from .stage2 import LIFE, summarize
from .robustness import two_day_lull

LATENT = {
    # new generations of existing technologies
    "SOLAR_R_G2": Design("SOLAR_R_G2", "renewable", annual_cost=44_000, loc="R", profile="solar_R_g2"),
    "SOLAR_R_G3": Design("SOLAR_R_G3", "renewable", annual_cost=33_000, loc="R", profile="solar_R_g3"),
    "SOLAR_D_G2": Design("SOLAR_D_G2", "renewable", annual_cost=60_000, loc="D", profile="solar_D_g2"),
    "BATT_G2": Design("BATT_G2", "store", annual_cost=25_500, form="elec", loc="H",
                      duration_h=4.0, eta_c=0.97, eta_d=0.97),
    # hydrogen: a new form of flow, arriving as a family
    "ELZ_R": Design("ELZ_R", "convert", annual_cost=60_000, form_in="elec", form_out="h2", loc="R", eff=0.70),
    "H2_STORE_R": Design("H2_STORE_R", "store", annual_cost=800, form="h2", loc="R",
                         duration_h=24.0, eta_c=0.99, eta_d=0.99),
    "H2_PIPE_RD": Design("H2_PIPE_RD", "transport", annual_cost=12_000, fixed_cost=2_000_000,
                         form="h2", loc_from="R", loc_to="D", loss=0.02),
    "H2_GEN_D": Design("H2_GEN_D", "convert", annual_cost=70_000, form_in="h2", form_out="elec", loc="D", eff=0.50),
}
H2 = ("ELZ_R", "H2_STORE_R", "H2_PIPE_RD", "H2_GEN_D")
BASE_SCHEDULE = {"SOLAR_R_G2": 3, "SOLAR_D_G2": 3, "BATT_G2": 4, "SOLAR_R_G3": 6,
                 "ELZ_R": 5, "H2_STORE_R": 5, "H2_PIPE_RD": 5, "H2_GEN_D": 5}
LIFE_L = dict(LIFE, SOLAR_R_G2=13, SOLAR_R_G3=13, SOLAR_D_G2=13, BATT_G2=6,
              ELZ_R=10, H2_STORE_R=20, H2_PIPE_RD=20, H2_GEN_D=12)
FAMILY = {"SOLAR_R": "solar", "SOLAR_D": "solar", "SOLAR_R_G2": "solar", "SOLAR_R_G3": "solar",
          "SOLAR_D_G2": "solar", "WIND_R": "wind", "BATT_H": "batt", "BATT_G2": "batt",
          "ELZ_R": "elz", "H2_GEN_D": "h2gen"}
LR = {"solar": 0.20, "wind": 0.10, "batt": 0.15, "elz": 0.15, "h2gen": 0.10}
C0 = {"solar": 600.0, "wind": 400.0, "batt": 300.0, "elz": 100.0, "h2gen": 100.0}


def make_actor(rng, K, schedule, fuel_growth=0.05, h2_cost=1.0):
    sc = two_day_lull()
    dscale = rng.uniform(0.6, 1.4)
    sscale, wscale = rng.uniform(0.8, 1.2), rng.uniform(0.7, 1.3)
    prof = {k: list(v) for k, v in sc.profiles.items()}
    prof["solar_R"] = [min(1, x * sscale) for x in prof["solar_R"]]
    prof["solar_D"] = [min(1, x * sscale) for x in prof["solar_D"]]
    prof["wind_R"] = [min(1, x * wscale) for x in prof["wind_R"]]
    prof["solar_R_g2"] = [min(1, x * 1.10) for x in prof["solar_R"]]
    prof["solar_R_g3"] = [min(1, x * 1.15) for x in prof["solar_R"]]
    prof["solar_D_g2"] = [min(1, x * 1.10) for x in prof["solar_D"]]
    designs = dict(sc.designs)
    designs.update({n: (replace(d, annual_cost=d.annual_cost * h2_cost, fixed_cost=d.fixed_cost * h2_cost)
                        if n in H2 else d) for n, d in LATENT.items()})
    sc = replace(sc, designs=designs, profiles=prof,
                 demand_D=[x * dscale for x in sc.demand_D],
                 hub_energy=sc.hub_energy * dscale, hub_max_rate=sc.hub_max_rate * dscale)
    fuel0 = rng.uniform(20, 45)
    traj = Trajectory(K=K, fuel_price=[fuel0 * (1 + fuel_growth) ** k for k in range(K)],
                      demand_mult=[1.03 ** k for k in range(K)],
                      cost_mult={d: [1.0] * K for d in FAMILY},
                      avail_from=dict(schedule))
    ages = {"GEN_D": int(rng.integers(8, 15)), "SOLAR_D": int(rng.integers(3, 10)),
            "FUEL_TRANS": int(rng.integers(6, 16)), "LINE_HD": int(rng.integers(0, 10)),
            "FUEL_STORE_D": int(rng.integers(5, 15))}
    inc = incumbent(replace(sc, designs={k: v for k, v in sc.designs.items() if k not in LATENT}))
    hist = [Vintage(n, -ages[n], c, c, sc.designs[n].annual_cost, sc.designs[n].fixed_cost, LIFE_L[n])
            for n, c in inc.capacity.items() if c > 1e-6]
    return {"sc": sc, "traj": traj, "hist": hist, "fuel0": fuel0}


def run_market(seed=0, schedule=None, N=6, K=10, phi=1.0, learning=True, fuel_growth=0.05, h2_cost=1.0):
    schedule = dict(schedule or BASE_SCHEDULE)
    rng = np.random.default_rng(seed)
    actors = [make_actor(rng, K, schedule, fuel_growth, h2_cost) for _ in range(N)]
    prm = Params(life=LIFE_L)
    own = [{f: 0.0 for f in C0} for _ in range(N)]
    records = [[] for _ in range(N)]
    for k in range(K):
        tot = {f: sum(o[f] for o in own) for f in C0}
        for i, a in enumerate(actors):
            for d, f in FAMILY.items():
                exp = C0[f] + own[i][f] + phi * (tot[f] - own[i][f])
                a["traj"].cost_mult[d][k] = (exp / C0[f]) ** math.log2(1 - LR[f]) if learning else 1.0
        for i, a in enumerate(actors):
            sol = solve_window(a["sc"], a["traj"], prm, k, k, a["hist"])
            records[i].append(sol["epochs"][k])
            for j, v in enumerate(a["hist"]):
                v.alive = sol["hist_alive"][j, k]
            for (n, v), x in sol["build"].items():
                if v == k and x > 1e-4:
                    d = a["sc"].designs[n]
                    a["hist"].append(Vintage(n, k, x, sol["new_alive"].get((n, k, k), x),
                                             d.annual_cost * a["traj"].mult(n, k),
                                             d.fixed_cost * a["traj"].mult(n, k), prm.life[n]))
                    if n in FAMILY:
                        own[i][FAMILY[n]] += x
    res = {"seed": seed, "schedule": schedule, "actors": [], "records": records, "actor_sc": [a["sc"] for a in actors]}
    agg_gen, agg_store = {}, {}
    for i, a in enumerate(actors):
        s = summarize(a["sc"], a["traj"], {"epochs": records[i]}, prm)
        last = records[i][-1]
        for n, e in last["throughput"].items():
            d = a["sc"].designs[n]
            if d.kind in ("renewable", "convert") and (d.form_out in (None, "elec")):
                agg_gen[n] = agg_gen.get(n, 0.0) + e
            if d.kind == "store" and d.form in ("elec", "h2"):
                agg_store[n] = agg_store.get(n, 0.0) + e
        res["actors"].append({"fuel0": a["fuel0"], "path_cost": s["path_cost"], "emissions": s["emissions"],
                              "h2": last["throughput"].get("H2_GEN_D", 0.0) > 1.0,
                              "first_build": s["first_build"]})
    res["final_generation"] = agg_gen      # MWh over the two representative days, final epoch
    res["final_storage"] = agg_store
    res["total_cost"] = sum(a["path_cost"] for a in res["actors"])
    res["cum_emissions"] = sum(sum(a["emissions"]) for a in res["actors"])
    res["h2_actors"] = sum(a["h2"] for a in res["actors"])
    return res
