"""Generated geographies on a jittered hexagonal lattice, run through the dynamic engine."""
import math, time
from dataclasses import replace
from itertools import combinations
from typing import Dict, List
import numpy as np

from .catalog import default_scenario, default_designs, Design
from .spatial import link_designs, dist
from .model import solve
from .analysis import verified
from .dynamic import Trajectory, Params, Vintage, run_policy
from .stage2 import summarize
from .spatial_dynamic import life_of


def contingency_set(sc, p_outage=0.01, p_calm=0.05, calm_scale=0.3):
    cont = []
    for loc in sc.locations:
        fail = tuple(n for n, d in sc.designs.items() if d.kind == "transport" and loc in (d.loc_from, d.loc_to))
        if fail:
            cont.append({"fail": fail, "p": p_outage})
    for loc in sc.locations:
        fail = tuple(n for n, d in sc.designs.items() if (d.kind == "renewable" or n.startswith("GEN")) and d.loc == loc)
        if fail and (loc == "D" or loc in sc.extra_demand):
            cont.append({"fail": fail, "p": p_outage})
    cont.append({"profile_scale": calm_scale, "p": p_calm})
    return cont

K = 10
SPACING = 110.0  # km between adjacent cells


def hex_cells(radius=2):
    cells = []
    for q in range(-radius, radius + 1):
        for r in range(-radius, radius + 1):
            if abs(q + r) <= radius:
                cells.append((q, r))
    return cells


def hex_dist(a, b):
    dq, dr = a[0] - b[0], a[1] - b[1]
    return max(abs(dq), abs(dr), abs(dq + dr))


def to_xy(q, r, rng, jitter=0.12):
    x = SPACING * (q + r / 2) + rng.normal(0, jitter * SPACING)
    y = SPACING * (math.sqrt(3) / 2) * r + rng.normal(0, jitter * SPACING)
    return (round(x, 1), round(y, 1))


def make_world(seed=0, resource_distance=2, dispersion=1.5, n_demand=7, lump_mult=1.0):
    """resource_distance: hex distance from the main center to the resource cluster (1 or 2),
    or 'split' (fuel at one edge, wind at the opposite edge).
    dispersion: Zipf exponent for demand shares; large = one dominant center, small = many equal towns."""
    rng = np.random.default_rng(seed)
    cells = hex_cells(2)
    center = (0, 0)
    names = {c: ("D" if c == center else f"n{i}") for i, c in enumerate(cells)}
    coords = {names[c]: to_xy(*c, rng) for c in cells}
    # demand: main center at the origin, other demand cells random; shares Zipf(dispersion)
    others = [c for c in cells if c != center]
    rng.shuffle(others)
    demand_cells = [center] + others[:n_demand - 1]
    shares = np.array([(i + 1) ** (-dispersion) for i in range(n_demand)]); shares /= shares.sum()
    demand_share = {names[c]: float(s) for c, s in zip(demand_cells, shares)}
    # resources
    if resource_distance == "split":
        ring2 = [c for c in cells if hex_dist(c, center) == 2]
        fuel_cell = ring2[int(rng.integers(len(ring2)))]
        wind_cell = max(ring2, key=lambda c: hex_dist(c, fuel_cell))
    else:
        ring = [c for c in cells if hex_dist(c, center) == resource_distance and c not in demand_cells[1:]]
        fuel_cell = ring[int(rng.integers(len(ring)))]
        wind_cell = fuel_cell
    fuel_loc, wind_loc = names[fuel_cell], names[wind_cell]
    wind_cells = {names[c] for c in cells if hex_dist(c, wind_cell) <= 1}
    # solar gradient: better toward the resource side
    fx = coords[fuel_loc][0]; xs = [v[0] for v in coords.values()]
    solar_scale = {l: 0.8 + 0.4 * (0.5 + 0.5 * np.sign(fx) * (v[0] / (max(map(abs, xs)) + 1e-9))) for l, v in coords.items()}
    # scenario
    base = default_scenario(); tmpl = default_designs()
    designs: Dict[str, Design] = {}
    profiles = dict(base.profiles)
    for l in coords:
        profiles[f"solar_{l}"] = [min(1.0, x * solar_scale[l]) for x in base.profiles["solar_R"]]
        designs[f"SOLAR_{l}"] = replace(tmpl["SOLAR_R"], name=f"SOLAR_{l}", loc=l, profile=f"solar_{l}",
                                        annual_cost=tmpl["SOLAR_R"].annual_cost * (1.0 if l not in demand_share else 1.25))
        designs[f"BATT_{l}"] = replace(tmpl["BATT_H"], name=f"BATT_{l}", loc=l)
        if l in wind_cells:
            designs[f"WIND_{l}"] = replace(tmpl["WIND_R"], name=f"WIND_{l}", loc=l)
        if l in demand_share:
            designs[f"GEN_{l}"] = replace(tmpl["GEN_D"], name=f"GEN_{l}", loc=l)
            designs[f"FUEL_STORE_{l}"] = replace(tmpl["FUEL_STORE_D"], name=f"FUEL_STORE_{l}", loc=l)
    designs[f"GEN_{fuel_loc}"] = replace(tmpl["GEN_R"], name=f"GEN_{fuel_loc}", loc=fuel_loc)
    # candidate links: adjacent cells (lines and pipes) + direct lines from resource cells to top-3 centers
    inv = {v: k for k, v in names.items()}
    top = sorted(demand_share, key=demand_share.get, reverse=True)[:3]
    allowed = set()
    for a, b in combinations(coords, 2):
        if hex_dist(inv[a], inv[b]) == 1:
            allowed.add(frozenset((a, b)))
    for r in (fuel_loc, wind_loc):
        for t in top:
            if r != t:
                allowed.add(frozenset((r, t)))
    links = link_designs(coords, lump_mult, 1.0, pipes=True)
    for n, d in links.items():
        if frozenset((d.loc_from, d.loc_to)) in allowed:
            if d.form == "fuel" and not (fuel_loc in (d.loc_from, d.loc_to) or hex_dist(inv[d.loc_from], inv[d.loc_to]) == 1):
                continue
            designs[n] = d
    prof = base.demand_D
    sc = replace(base, designs=designs, profiles=profiles, coords=coords, locations=tuple(coords),
                 fuel_sites=(fuel_loc,), hub_energy=0.0,
                 demand_D=[x * demand_share["D"] for x in prof],
                 extra_demand={l: [x * s for x in prof] for l, s in demand_share.items() if l != "D"})
    meta = {"seed": seed, "resource_distance": str(resource_distance), "dispersion": dispersion,
            "fuel_loc": fuel_loc, "wind_loc": wind_loc, "demand_share": demand_share, "coords": coords,
            "hex": {names[c]: c for c in cells}}
    return sc, meta


def incumbent(sc, rng):
    fuel_only = [n for n in sc.designs if n.startswith(("GEN", "PIPE", "FUEL_STORE"))]
    inc = verified(sc, solve(sc, fuel_only))
    hist = []
    for n, c in inc.capacity.items():
        if c > 1e-6:
            d = sc.designs[n]
            hist.append(Vintage(n, -int(rng.integers(4, 13)), c, c, d.annual_cost, d.fixed_cost, life_of(n)))
    return hist


def trajectory(sc, fuel_growth=0.10, demand_growth=0.04, learn=None):
    learn = learn or {"SOLAR": 0.06, "WIND": 0.03, "BATT": 0.06}
    mult = {n: [(1 - r) ** k for k in range(K)] for n in sc.designs for p, r in learn.items() if n.startswith(p)}
    return Trajectory(K=K, fuel_price=[25.0 * (1 + fuel_growth) ** k for k in range(K)],
                      demand_mult=[(1 + demand_growth) ** k for k in range(K)], cost_mult=mult)


def snapshot(sc, e, meta):
    links, nodes = [], {l: {"gen": {}, "storage": 0.0} for l in sc.locations}
    for n, c in e["capacity"].items():
        if c <= 1e-3:
            continue
        d = sc.designs[n]; t = e["throughput"].get(n, 0.0)
        if d.kind == "transport":
            links.append({"a": d.loc_from, "b": d.loc_to, "form": d.form, "capacity": round(c, 1), "throughput": round(t, 1),
                          "idle": t < 1.0, "km": round(dist(sc.coords[d.loc_from], sc.coords[d.loc_to]))})
        elif n.startswith("BATT"):
            nodes[d.loc]["storage"] += c
        elif n.startswith(("GEN", "SOLAR", "WIND")):
            fam = "fuel" if n.startswith("GEN") else ("solar" if n.startswith("SOLAR") else "wind")
            g = nodes[d.loc]["gen"].setdefault(fam, {"capacity": 0.0, "throughput": 0.0})
            g["capacity"] += c; g["throughput"] += t
    return {"links": links, "nodes": nodes, "emissions": round(e["emissions"], 1)}


def measures(snap, meta):
    """Structure per epoch: components, link km, connectivity concentration, redundancy,
    distance of the network's capacity-weighted center from resources and from demand."""
    C = meta["coords"]; act = [l for l in snap["links"] if not l["idle"]]
    parent = {l: l for l in C}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for l in act: parent[find(l["a"])] = find(l["b"])
    demand = list(meta["demand_share"])
    comps = len({find(l) for l in demand})
    inc = {l: 0.0 for l in C}
    for l in act:
        inc[l["a"]] += l["capacity"]; inc[l["b"]] += l["capacity"]
    tot = sum(inc.values()) or 1.0
    hub = max(inc, key=inc.get)
    conc = inc[hub] / tot if act else 0.0
    deg = {l: 0 for l in C}
    for l in act: deg[l["a"]] += 1; deg[l["b"]] += 1
    redund = np.mean([1.0 if (deg[d] >= 2 or (deg[d] >= 1 and snap["nodes"][d]["gen"])) else 0.0 for d in demand]) if demand else 0.0
    if act:
        w = np.array([l["capacity"] * l["km"] for l in act]); pts = np.array([[(C[l["a"]][0] + C[l["b"]][0]) / 2, (C[l["a"]][1] + C[l["b"]][1]) / 2] for l in act])
        center = (w[:, None] * pts).sum(0) / w.sum()
    else:
        center = None
    dres = float(np.hypot(*(center - np.array(C[meta["fuel_loc"]])))) if center is not None else None
    dsh = np.array([meta["demand_share"][d] for d in demand]); dpts = np.array([C[d] for d in demand])
    dcen = (dsh[:, None] * dpts).sum(0) / dsh.sum()
    ddem = float(np.hypot(*(center - dcen))) if center is not None else None
    return {"components": comps, "link_km": sum(l["km"] * (0 if l["idle"] else 1) for l in snap["links"]),
            "n_active_links": len(act), "hub": hub if act else None, "concentration": round(conc, 3),
            "redundancy": round(float(redund), 3), "dist_center_to_fuel": dres, "dist_center_to_demand": ddem}


def run_world(seed=0, resource_distance=2, dispersion=1.5, lump_mult=1.0, n1=False, verbose=True):
    sc, meta = make_world(seed, resource_distance, dispersion, lump_mult=lump_mult)
    rng = np.random.default_rng(seed + 77)
    hist = incumbent(sc, rng)
    prm = Params(life={n: life_of(n) for n in sc.designs})
    traj = trajectory(sc)
    t = time.time()
    cont = contingency_set(sc) if n1 else None
    r = run_policy(sc, traj, prm, hist, horizon=1, contingencies=cont)
    s = summarize(sc, traj, r, prm)
    snaps = [snapshot(sc, e, meta) for e in r["epochs"]]
    ms = [measures(sn, meta) for sn in snaps]
    exit_epoch = {}
    for l in meta["demand_share"]:
        exit_epoch[l] = next((k for k, sn in enumerate(snaps) if sn["nodes"][l]["gen"].get("fuel", {}).get("throughput", 0) < 1.0), None)
    if verbose:
        print(f"seed {seed} dist {resource_distance} disp {dispersion}: {time.time()-t:.0f}s designs {len(sc.designs)} path {s['path_cost']/1e6:.2f}M emis {s['cum_emissions']:.0f}", flush=True)
    return {"meta": meta, "path_cost": s["path_cost"], "cum_emissions": s["cum_emissions"], "snaps": snaps,
            "measures": ms, "exit_epoch": exit_epoch, "n1": n1, "lump_mult": lump_mult}
