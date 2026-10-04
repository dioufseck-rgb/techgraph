"""Stage 2 scenarios and experiments."""
from dataclasses import replace
from typing import Dict, List, Optional
import numpy as np

from .catalog import default_scenario, Scenario
from .analysis import INCUMBENT_LANDSCAPE, incumbent
from .dynamic import Trajectory, Params, Vintage, run_policy, path_cost, solve_window

YEARS_PER_EPOCH = 2
K = 10  # 20 years

# technical lives in epochs (2 years each)
LIFE = {"GEN_D": 15, "GEN_R": 15, "SOLAR_R": 13, "SOLAR_D": 13, "WIND_R": 12,
        "FUEL_TRANS": 20, "LINE_RH": 20, "LINE_HD": 20, "BATT_H": 6, "FUEL_STORE_D": 20}
# ages of the incumbent's assets at epoch 0 (epochs): the old generator retires at
# epoch 4, local solar at 7, the fuel pipe at 8; the local line lasts the horizon.
INCUMBENT_AGE = {"GEN_D": 11, "SOLAR_D": 6, "FUEL_TRANS": 12, "LINE_HD": 5, "FUEL_STORE_D": 10}


def base_trajectory(K=K, fuel_growth=0.10, demand_growth=0.04, learn=None, batt_from=2) -> Trajectory:
    learn = learn or {"SOLAR_R": 0.06, "SOLAR_D": 0.06, "WIND_R": 0.03, "BATT_H": 0.10}
    return Trajectory(
        K=K,
        fuel_price=[25.0 * (1 + fuel_growth) ** k for k in range(K)],
        demand_mult=[(1 + demand_growth) ** k for k in range(K)],
        cost_mult={d: [(1 - r) ** k for k in range(K)] for d, r in learn.items()},
        avail_from={"BATT_H": batt_from},
    )


def incumbent_history(sc: Scenario) -> List[Vintage]:
    inc = incumbent(sc)
    hist = []
    for n, c in inc.capacity.items():
        if c > 1e-6:
            d = sc.designs[n]
            hist.append(Vintage(n, -INCUMBENT_AGE[n], c, c, d.annual_cost, d.fixed_cost, LIFE[n]))
    return hist


POLICIES = {
    "foresight":        dict(horizon=99, expectations="true", m_new=None),
    "plan 3, static":   dict(horizon=3, expectations="static", m_new=None),
    "myopic, m=inf":    dict(horizon=1, expectations="true", m_new=None),
    "myopic, m=1":      dict(horizon=1, expectations="true", m_new=1),
    "myopic, m=0":      dict(horizon=1, expectations="true", m_new=0),
}


def capital_by_epoch(sc, traj, prm, run) -> List[float]:
    """Compatibility entry point for the common realized-capital ledger."""
    from .accounting import capital_charges_by_epoch
    return capital_charges_by_epoch(sc, traj, prm, run)


def summarize(sc, traj, run, prm=None) -> dict:
    prm = prm or Params(life=LIFE)
    E = run["epochs"]
    capital = capital_by_epoch(sc, traj, prm, run)
    for k, e in enumerate(E):
        e["capital"] = capital[k]
    first = {}
    for k, e in enumerate(E):
        for n in e["builds"]:
            first.setdefault(n, k)
    return {
        "path_cost": path_cost(traj, run),
        "emissions": [e["emissions"] for e in E],
        "cum_emissions": sum(e["emissions"] for e in E),
        "unmet": sum(e["unmet_MWh"] for e in E),
        "first_build": first,
        "capacity": [e["capacity"] for e in E],
        "throughput": [e["throughput"] for e in E],
        "builds": [e["builds"] for e in E],
        "costs": [{"capital": e["capital"], "fom": e["fom"], "ops": e["ops_cost"]} for e in E],
    }


def run_all(sc=None, traj=None, prm=None, policies=POLICIES) -> Dict[str, dict]:
    sc = sc or default_scenario()
    traj = traj or base_trajectory()
    prm = prm or Params(life=LIFE)
    hist = incumbent_history(sc)
    return {name: summarize(sc, traj, run_policy(sc, traj, prm, hist, **kw), prm) for name, kw in policies.items()}
