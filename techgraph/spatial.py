"""Spatial worlds: locations with coordinates, and transport designs generated from
distance-scaled templates for every pair of locations. Topology is an outcome."""
import math
from dataclasses import replace
from itertools import combinations
from typing import Dict, Tuple

from .catalog import Scenario, Design, default_scenario, default_designs
from .model import solve
from .analysis import verified

# Templates calibrated so that the old R-H (200 km) and H-D (50 km) lines keep
# roughly their Stage 1 costs.
LINE = dict(terminal=6_667.0, per_km=166.7, lump_per_km=20_000.0, loss0=0.005, loss_per_km=0.000125)
PIPE = dict(terminal=1_000.0, per_km=28.0, lump_per_km=6_000.0, loss0=0.0, loss_per_km=0.00004,
            var_per_km=0.004)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def link_designs(coords: Dict[str, Tuple[float, float]], lump_mult=1.0, km_mult=1.0,
                 pipes=True) -> Dict[str, Design]:
    out = {}
    for a, b in combinations(sorted(coords), 2):
        d = dist(coords[a], coords[b])
        out[f"LINE_{a}_{b}"] = Design(
            f"LINE_{a}_{b}", "transport", form="elec", loc_from=a, loc_to=b, bidirectional=True,
            annual_cost=LINE["terminal"] + km_mult * LINE["per_km"] * d,
            fixed_cost=lump_mult * LINE["lump_per_km"] * d,
            loss=LINE["loss0"] + LINE["loss_per_km"] * d)
        if pipes:
            out[f"PIPE_{a}_{b}"] = Design(
                f"PIPE_{a}_{b}", "transport", form="fuel", loc_from=a, loc_to=b, bidirectional=True,
                annual_cost=PIPE["terminal"] + km_mult * PIPE["per_km"] * d,
                fixed_cost=lump_mult * PIPE["lump_per_km"] * d,
                loss=PIPE["loss0"] + PIPE["loss_per_km"] * d, var_cost=PIPE["var_per_km"] * d)
    return out


# ---------------------------------------------------------------- S1 ------
S1_COORDS = {"R": (0.0, 0.0), "H": (200.0, 40.0), "D": (250.0, 0.0)}


def s1_world(lump_mult=1.0, km_mult=1.0, coords=None) -> Scenario:
    """The Stage 1 world, with the hub placed off the R-D axis and every pairwise
    line and pipe available as a candidate."""
    sc = default_scenario()
    coords = coords or S1_COORDS
    designs = {k: v for k, v in default_designs().items()
               if v.kind != "transport"}
    designs.update(link_designs(coords, lump_mult, km_mult))
    return replace(sc, designs=designs, coords=coords)


# ---------------------------------------------------------------- S2 ------
S2_COORDS = {"R": (0.0, 0.0), "S": (120.0, 160.0), "J": (140.0, 40.0),
             "D": (300.0, 0.0), "T": (260.0, 140.0), "U": (230.0, -120.0)}
S2_DEMAND_SHARE = {"D": 0.6, "T": 0.2, "U": 0.2}


def s2_world(lump_mult=1.0, km_mult=1.0, fuel_price=25.0) -> Scenario:
    """Six locations: a fuel and wind site (R), a solar site (S), an empty junction (J),
    a city (D) and two towns (T, U). Every pair can be linked."""
    base = default_scenario()
    tmpl = default_designs()
    designs: Dict[str, Design] = {}

    def add(name, proto, **kw):
        designs[name] = replace(proto, name=name, **kw)

    add("GEN_R", tmpl["GEN_R"]); add("SOLAR_R", tmpl["SOLAR_R"]); add("WIND_R", tmpl["WIND_R"])
    add("BATT_R", tmpl["BATT_H"], loc="R")
    add("SOLAR_S", tmpl["SOLAR_R"], loc="S", profile="solar_S")
    add("BATT_S", tmpl["BATT_H"], loc="S")
    for c in ("D", "T", "U"):
        add(f"GEN_{c}", tmpl["GEN_D"], loc=c)
        add(f"SOLAR_{c}", tmpl["SOLAR_D"], loc=c)
        add(f"BATT_{c}", tmpl["BATT_H"], loc=c)
        add(f"FUEL_STORE_{c}", tmpl["FUEL_STORE_D"], loc=c)
    designs.update(link_designs(S2_COORDS, lump_mult, km_mult))
    prof = dict(base.profiles)
    prof["solar_S"] = [min(1.0, x * 1.15) for x in prof["solar_R"]]
    d = base.demand_D
    return replace(base, designs=designs, profiles=prof, coords=S2_COORDS,
                   locations=tuple(S2_COORDS), fuel_sites=("R",), hub_energy=0.0,
                   demand_D=[x * S2_DEMAND_SHARE["D"] for x in d],
                   extra_demand={c: [x * S2_DEMAND_SHARE[c] for x in d] for c in ("T", "U")},
                   fuel_price_R=fuel_price)


# ---------------------------------------------------------------- metrics --
def topology(sc: Scenario, res, form="elec", tol=1e-3) -> dict:
    """Links built, and energy passing through each node (transit) for one form."""
    H = sc.hours
    links = {}
    inflow = {l: [0.0] * sc.periods for l in sc.locations}
    outflow = {l: [0.0] * sc.periods for l in sc.locations}
    delivered = 0.0
    for n, d in sc.designs.items():
        if d.kind != "transport" or d.form != form or res.capacity.get(n, 0.0) <= tol:
            continue
        ser = res.activity[n]
        fw, bw = ser["forward"], ser.get("backward", [0.0] * sc.periods)
        links[n] = {"a": d.loc_from, "b": d.loc_to, "capacity": res.capacity[n],
                    "km": dist(sc.coords[d.loc_from], sc.coords[d.loc_to]),
                    "energy": H * (sum(fw) + sum(bw))}
        for t in range(sc.periods):
            outflow[d.loc_from][t] += fw[t]; inflow[d.loc_to][t] += (1 - d.loss) * fw[t]
            outflow[d.loc_to][t] += bw[t]; inflow[d.loc_from][t] += (1 - d.loss) * bw[t]
            delivered += H * (1 - d.loss) * (fw[t] + bw[t])
    transit = {l: H * sum(min(inflow[l][t], outflow[l][t]) for t in range(sc.periods))
               for l in sc.locations}
    hub = max(transit, key=transit.get) if links else None
    degree = {l: sum(1 for x in links.values() if l in (x["a"], x["b"])) for l in sc.locations}
    return {"links": links, "transit": transit, "delivered": delivered,
            "hub": hub, "hub_share": (transit[hub] / delivered) if links and delivered > 0 else 0.0,
            "degree": degree,
            "MW_km": sum(x["capacity"] * x["km"] for x in links.values())}


def components(sc: Scenario, res, tol=1e-3) -> int:
    """Number of connected groups of locations (lines and pipes both connect)."""
    parent = {l: l for l in sc.locations}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for n, d in sc.designs.items():
        if d.kind == "transport" and res.capacity.get(n, 0.0) > tol:
            parent[find(d.loc_from)] = find(d.loc_to)
    used = {l for l in sc.locations if l != "J"} | {
        l for n, d in sc.designs.items() if d.kind == "transport" and res.capacity.get(n, 0) > tol
        for l in (d.loc_from, d.loc_to)}
    return len({find(l) for l in used})
