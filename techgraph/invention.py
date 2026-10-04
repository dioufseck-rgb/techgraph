"""Stage 3c: directed invention. Latent families arrive through a hazard process whose
rate depends on demand pull (the value the family would create across actors now)
and on proximity (its parent must exist). The determinist schedule is the null."""
import math
from dataclasses import replace
import numpy as np

from .latent import make_actor, LATENT, H2, FAMILY, LR, C0, LIFE_L
from .dynamic import Params, Vintage, solve_window
from .stage2 import summarize

FAMILIES = {"G2_R": ["SOLAR_R_G2"], "G3_R": ["SOLAR_R_G3"], "G2_D": ["SOLAR_D_G2"],
            "BATT_G2": ["BATT_G2"], "H2": list(H2)}
NEVER = 99


def proximity_ok(fam, invented, exp, t=1.5):
    """The adjacent possible: a family can appear only once its parent exists."""
    if fam == "G2_R":
        return exp["solar"] >= t * C0["solar"]
    if fam == "G3_R":
        return "G2_R" in invented
    if fam == "G2_D":
        return exp["solar"] >= t * C0["solar"]
    if fam == "BATT_G2":
        return exp["batt"] >= t * C0["batt"]
    return True  # hydrogen: no parent, low base rate


def run_invention(seed=0, mode="directed", N=6, K=10, phi=1.0, h2_cost=0.5,
                  beta=0.05, alpha=0.3, v_ref=12_000.0, beta_random=0.29, proximity=True, prox_t=1.5):
    rng = np.random.default_rng(seed)
    arr_rng = np.random.default_rng(seed + 1000)
    sched = {n: NEVER for ns in FAMILIES.values() for n in ns}
    actors = [make_actor(rng, K, sched, 0.05, h2_cost) for _ in range(N)]
    prm = Params(life=LIFE_L)
    own = [{f: 0.0 for f in C0} for _ in range(N)]
    records = [[] for _ in range(N)]
    invented, arrivals, signals = set(), {}, []
    for k in range(K):
        tot = {f: sum(o[f] for o in own) for f in C0}
        exp_global = {f: C0[f] + tot[f] for f in C0}
        for i, a in enumerate(actors):
            for d, f in FAMILY.items():
                e = C0[f] + own[i][f] + phi * (tot[f] - own[i][f])
                a["traj"].cost_mult[d][k] = (e / C0[f]) ** math.log2(1 - LR[f])
        # ---- invention step --------------------------------------------------
        # All candidate families are valued against the same pre-arrival landscape,
        # in undiscounted current-epoch units; arrivals are then drawn simultaneously.
        sig, drawn = {}, []
        undiscount = 1.0 / (actors[0]["traj"].discount ** k)
        base_obj = None
        for fam, designs in FAMILIES.items():
            if fam in invented:
                continue
            if proximity and not proximity_ok(fam, invented, exp_global, prox_t):
                sig[fam] = None
                continue
            V = 0.0
            if mode == "directed":
                if base_obj is None:
                    base_obj = [solve_window(a["sc"], a["traj"], prm, k, k, a["hist"])["objective"] for a in actors]
                for a, b in zip(actors, base_obj):
                    tr = replace(a["traj"], avail_from=dict(a["traj"].avail_from, **{n: k for n in designs}))
                    V += max(0.0, b - solve_window(a["sc"], tr, prm, k, k, a["hist"])["objective"])
                V *= undiscount
                rate = beta + alpha * V / v_ref
            else:
                rate = beta_random
            p = 1 - math.exp(-rate)
            sig[fam] = {"value": V, "p": p}
            if arr_rng.random() < p:
                drawn.append(fam)
        for fam in drawn:
            invented.add(fam); arrivals[fam] = k
            for a in actors:
                for n in FAMILIES[fam]:
                    a["traj"].avail_from[n] = k
        signals.append(sig)
        # ---- adoption step ---------------------------------------------------
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
    gen, store, cost, emis = {}, {}, 0.0, 0.0
    for i, a in enumerate(actors):
        s = summarize(a["sc"], a["traj"], {"epochs": records[i]}, prm)
        cost += s["path_cost"]; emis += sum(s["emissions"])
        for n, e in records[i][-1]["throughput"].items():
            d = a["sc"].designs[n]
            if d.kind in ("renewable", "convert") and d.form_out in (None, "elec"):
                gen[n] = gen.get(n, 0.0) + e
            if d.kind == "store":
                store[n] = store.get(n, 0.0) + e
    return {"records": records, "actor_sc": [a["sc"] for a in actors], "seed": seed, "mode": mode, "proximity": proximity, "arrivals": arrivals,
            "signals": signals, "final_generation": gen, "final_storage": store,
            "total_cost": cost, "cum_emissions": emis}
