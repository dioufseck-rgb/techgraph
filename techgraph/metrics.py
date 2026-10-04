"""Architecture metrics at several levels of aggregation (Stage 0)."""
import numpy as np
from .flows import forms
from .measurement.architecture import share_composition,share_distance

FAMILY_OF = {"SOLAR_R": "solar_remote", "SOLAR_R_G2": "solar_remote", "SOLAR_R_G3": "solar_remote",
             "SOLAR_D": "solar_local", "SOLAR_D_G2": "solar_local", "SOLAR_H": "solar_local",
             "WIND_R": "wind", "GEN_D": "fuel_local", "GEN_R": "fuel_remote", "H2_GEN_D": "hydrogen",
             "BATT_H": "battery", "BATT_G2": "battery", "BATT_B": "battery_long", "H2_STORE_R": "h2_store"}


def composition(gen: dict, level: str = "family") -> dict:
    """Compatibility entry point for explicit design/family composition."""
    return share_composition(gen,None if level=="design" else FAMILY_OF)


def distance(a: dict, b: dict) -> float:
    """Compatibility entry point for half-L1 share distance."""
    return share_distance(a,b)


def state_kinds(sc, res, tol=1e-3):
    """Classify (form, location) states: candidate, reachable (some module can deliver
    to it in this configuration), used (positive throughput into it)."""
    H = sc.hours
    reachable, used = set(), set()
    for n, ser in res.activity.items():
        d = sc.designs[n]
        if res.capacity.get(n, 0.0) <= tol:
            continue
        outs = d.outputs()
        for o in outs:
            reachable.add(o)
        flow = sum(sum(v) for k, v in ser.items() if k != "level")
        if flow * H > tol:
            for o in outs:
                used.add(o)
    candidate = {(f, l) for f in forms(sc) for l in sc.locations}
    return {"candidate": candidate, "reachable": reachable, "used": used}
