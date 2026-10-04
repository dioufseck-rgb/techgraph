"""Dynamics on a spatial world with free topology: the six-node world of spatial.py run
through the Stage 2 engine. Links, generation and storage are all vintages; topology evolves."""
import time
from dataclasses import replace
from typing import Dict, List
from .spatial import s2_world, topology, components, dist
from .model import solve
from .analysis import verified
from .dynamic import Trajectory, Params, Vintage, run_policy
from .stage2 import summarize

K = 10


def life_of(name: str) -> int:
    if name.startswith("GEN"): return 15
    if name.startswith("SOLAR"): return 13
    if name.startswith("WIND"): return 12
    if name.startswith("BATT"): return 6
    if name.startswith(("LINE", "PIPE", "FUEL_STORE")): return 20
    return 15


def world(lump_mult=1.0):
    sc = s2_world(lump_mult, 1.0, 25.0)
    return sc


def incumbent_history(sc, ages: Dict[str, int]) -> List[Vintage]:
    """The fossil incumbent: fuel designs only (generators, pipes, fuel stores), built
    at the base fuel price with free topology; then aged."""
    fuel_only = [n for n, d in sc.designs.items()
                 if n.startswith(("GEN", "PIPE", "FUEL_STORE"))]
    inc = verified(sc, solve(sc, fuel_only))
    hist = []
    for n, c in inc.capacity.items():
        if c > 1e-6:
            d = sc.designs[n]
            a = ages.get(n, ages.get(n.split("_")[0], 5))
            hist.append(Vintage(n, -a, c, c, d.annual_cost, d.fixed_cost, life_of(n)))
    return hist, inc


def trajectory(sc, fuel_growth=0.10, demand_growth=0.04, learn=None):
    learn = learn or {"SOLAR": 0.06, "WIND": 0.03, "BATT": 0.10}
    mult = {}
    for n in sc.designs:
        for pref, r in learn.items():
            if n.startswith(pref):
                mult[n] = [(1 - r) ** k for k in range(K)]
    return Trajectory(K=K, fuel_price=[25.0 * (1 + fuel_growth) ** k for k in range(K)],
                      demand_mult=[(1 + demand_growth) ** k for k in range(K)], cost_mult=mult)


def snapshot(sc, e):
    """Per-epoch: links (with capacity, throughput), per-node local generation by family and storage."""
    links = []
    for n, c in e["capacity"].items():
        if c <= 1e-3 or not n.startswith(("LINE", "PIPE")):
            continue
        d = sc.designs[n]
        links.append({"a": d.loc_from, "b": d.loc_to, "form": d.form, "capacity": round(c, 1),
                      "throughput": round(e["throughput"].get(n, 0.0), 1), "idle": e["throughput"].get(n, 0.0) < 1.0,
                      "km": round(dist(sc.coords[d.loc_from], sc.coords[d.loc_to]))})
    nodes = {}
    for l in sc.locations:
        nodes[l] = {"gen": {}, "storage": 0.0, "storage_used": False}
    for n, c in e["capacity"].items():
        if c <= 1e-3 or n.startswith(("LINE", "PIPE")):
            continue
        d = sc.designs[n]
        loc = d.loc
        fam = "fuel" if n.startswith("GEN") else ("solar" if n.startswith("SOLAR") else ("wind" if n.startswith("WIND") else ("battery" if n.startswith("BATT") else "fuelstore")))
        if fam == "battery":
            nodes[loc]["storage"] += c; nodes[loc]["storage_used"] |= e["throughput"].get(n, 0) > 1
        elif fam != "fuelstore":
            g = nodes[loc]["gen"].setdefault(fam, {"capacity": 0.0, "throughput": 0.0})
            g["capacity"] += c; g["throughput"] += e["throughput"].get(n, 0.0)
    return {"links": links, "nodes": nodes, "emissions": round(e["emissions"], 1)}


def contingency_set(sc, p_outage=0.01, p_calm=0.05, calm_scale=0.3):
    """Reduced N-1 set: loss of a whole corridor (line and pipe between a pair of
    locations), loss of each resource site's generation, loss of local generation at
    each demand node, and a calm period with renewables scaled down."""
    from itertools import combinations
    cont = []
    for a, b in combinations(sorted(sc.locations), 2):
        fail = tuple(n for n, d in sc.designs.items() if d.kind == "transport" and {d.loc_from, d.loc_to} == {a, b})
        if fail:
            cont.append({"fail": fail, "p": p_outage})
    for loc in sc.locations:
        fail = tuple(n for n, d in sc.designs.items() if (d.kind == "renewable" or n.startswith("GEN")) and d.loc == loc)
        if fail:
            cont.append({"fail": fail, "p": p_outage})
    cont.append({"profile_scale": calm_scale, "p": p_calm})
    return cont


def run(lump_mult=1.0, m_new=None, horizon=1, ages=None, verbose=True, n1=False):
    sc = world(lump_mult)
    ages = ages or {"GEN_D": 11, "GEN_T": 8, "GEN_U": 5, "GEN_R": 9, "PIPE": 10, "FUEL_STORE": 8}
    hist, inc = incumbent_history(sc, ages)
    prm = Params(life={n: life_of(n) for n in sc.designs})
    traj = trajectory(sc)
    t = time.time()
    cont = contingency_set(sc) if n1 else None
    r = run_policy(sc, traj, prm, hist, horizon=horizon, m_new=m_new, contingencies=cont)
    s = summarize(sc, traj, r, prm)
    if verbose:
        print(f"lump {lump_mult} m={m_new} horizon={horizon} n1={n1}: {time.time()-t:.0f}s path {s['path_cost']/1e6:.2f}M cumEmis {s['cum_emissions']:.0f} unmet {sum(e['unmet_MWh'] for e in r['epochs']):.2f}")
    snaps = [snapshot(sc, e) for e in r["epochs"]]
    return {"sc": sc, "traj": traj, "summary": s, "snaps": snaps, "coords": sc.coords, "incumbent": inc.capacity}
