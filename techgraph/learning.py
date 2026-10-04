"""Stage 3a: endogenous learning among several actors.

Each actor runs its own physical system. They interact only through technology:
the cost of a design family falls with experience (cumulative deployment), and an
actor's experience counts its own deployment plus a share phi of everyone else's.
Actors take current costs as given and do not internalize the learning they cause.
"""
import math
from dataclasses import replace
from typing import Dict, List
import numpy as np

from .catalog import default_scenario, Design
from .analysis import incumbent
from .dynamic import Trajectory, Params, Vintage, solve_window
from .stage2 import LIFE, summarize

# learning families: designs sharing a family share experience
FAMILY = {"SOLAR_R": "solar", "SOLAR_D": "solar", "WIND_R": "wind", "BATT_H": "batt_A", "BATT_B": "batt_B"}
LEARNING_RATE = {"solar": 0.20, "wind": 0.10, "batt_A": 0.05, "batt_B": 0.25}  # cost drop per doubling
C0 = {"solar": 600.0, "wind": 400.0, "batt_A": 300.0, "batt_B": 300.0}           # prior world experience
# B: long-duration storage (8 h), dearer per MWh today, fast learner
BATT_B = Design("BATT_B", "store", annual_cost=27_000, form="elec", loc="H",
                duration_h=8.0, eta_c=0.93, eta_d=0.93)
LIFE3 = dict(LIFE, BATT_B=6)


def make_actor(rng, K):
    sc = default_scenario()
    designs = dict(sc.designs); designs["BATT_B"] = BATT_B
    dscale = rng.uniform(0.6, 1.4)
    sscale, wscale = rng.uniform(0.8, 1.2), rng.uniform(0.7, 1.3)
    prof = dict(sc.profiles)
    prof["solar_R"] = [min(1, x * sscale) for x in prof["solar_R"]]
    prof["solar_D"] = [min(1, x * sscale) for x in prof["solar_D"]]
    prof["wind_R"] = [min(1, x * wscale) for x in prof["wind_R"]]
    sc = replace(sc, designs=designs, profiles=prof,
                 demand_D=[x * dscale for x in sc.demand_D],
                 hub_energy=sc.hub_energy * dscale, hub_max_rate=sc.hub_max_rate * dscale)
    fuel0 = rng.uniform(20, 45)
    traj = Trajectory(K=K, fuel_price=[fuel0 * 1.05 ** k for k in range(K)],
                      demand_mult=[1.03 ** k for k in range(K)],
                      cost_mult={d: [1.0] * K for d in FAMILY})
    gen_age = int(rng.integers(8, 15))          # old generator retires at epoch 15 - age
    ages = {"GEN_D": gen_age, "SOLAR_D": int(rng.integers(3, 10)), "FUEL_TRANS": int(rng.integers(6, 16)),
            "LINE_HD": int(rng.integers(0, 10)), "FUEL_STORE_D": int(rng.integers(5, 15))}
    inc = incumbent(replace(sc, designs={k: v for k, v in sc.designs.items() if k != "BATT_B"}))
    hist = [Vintage(n, -ages[n], c, c, sc.designs[n].annual_cost, sc.designs[n].fixed_cost, LIFE3[n])
            for n, c in inc.capacity.items() if c > 1e-6]
    return {"sc": sc, "traj": traj, "hist": hist, "fuel0": fuel0, "dscale": dscale,
            "sscale": sscale, "wscale": wscale, "retire_epoch": 15 - gen_age}


def run_market(seed=0, N=6, K=10, phi=1.0, learning=True, lr=None, exclude=()):
    lr = lr or LEARNING_RATE
    rng = np.random.default_rng(seed)
    actors = [make_actor(rng, K) for _ in range(N)]
    for a in actors:
        if exclude:
            a["sc"] = replace(a["sc"], designs={k: v for k, v in a["sc"].designs.items() if k not in exclude})
    prm = Params(life=LIFE3)
    own = [{f: 0.0 for f in C0} for _ in range(N)]         # own cumulative deployment by family
    records = [[] for _ in range(N)]
    mult_log = []
    for k in range(K):
        tot = {f: sum(o[f] for o in own) for f in C0}
        mk = []
        for i, a in enumerate(actors):
            m = {}
            for d, f in FAMILY.items():
                if d not in a["sc"].designs:
                    continue
                exp = C0[f] + own[i][f] + phi * (tot[f] - own[i][f])
                b = -math.log2(1 - lr[f])
                m[d] = (exp / C0[f]) ** (-b) if learning else 1.0
                a["traj"].cost_mult[d][k] = m[d]
            mk.append(m)
        mult_log.append(mk)
        for i, a in enumerate(actors):
            sol = solve_window(a["sc"], a["traj"], prm, k, k, a["hist"])
            e = sol["epochs"][k]
            records[i].append(e)
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
    out = {"seed": seed, "phi": phi, "learning": learning, "actors": []}
    for i, a in enumerate(actors):
        s = summarize(a["sc"], a["traj"], {"epochs": records[i]}, prm)
        em = s["emissions"]
        out["actors"].append({
            "fuel0": a["fuel0"], "dscale": a["dscale"], "sscale": a["sscale"], "wscale": a["wscale"],
            "retire_epoch": a["retire_epoch"], "path_cost": s["path_cost"], "emissions": em,
            "switch_epoch": next((k for k, x in enumerate(em) if x < 0.5 * max(em[0], 1)), None),
            "builds": s["builds"], "own": own[i],
            "mult": [mult_log[k][i] for k in range(K)]})
    out["total"] = {f: sum(o[f] for o in own) for f in C0}
    return out
