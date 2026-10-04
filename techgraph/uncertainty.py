"""Planning under uncertainty: actors know the distribution of futures, not the future."""
from dataclasses import dataclass, replace
from typing import List
import numpy as np

from .dynamic import Trajectory, solve_window, solve_window_stochastic, Vintage
from .stage2 import base_trajectory, summarize

LEARNED = ("SOLAR_R", "SOLAR_D", "WIND_R", "BATT_H")


@dataclass
class Draw:
    fuel_growth: float
    demand_growth: float
    solar: float
    wind: float
    batt: float
    batt_from: int

    def trajectory(self, K=10) -> Trajectory:
        return base_trajectory(K=K, fuel_growth=self.fuel_growth, demand_growth=self.demand_growth,
                               learn={"SOLAR_R": self.solar, "SOLAR_D": self.solar,
                                      "WIND_R": self.wind, "BATT_H": self.batt},
                               batt_from=self.batt_from)


def sample_prior(rng) -> Draw:
    return Draw(rng.uniform(0.0, 0.15), rng.uniform(0.0, 0.08), rng.uniform(0.02, 0.10),
                rng.uniform(0.0, 0.06), rng.uniform(0.04, 0.15), int(rng.integers(0, 5)))


MEAN = Draw(0.075, 0.04, 0.06, 0.03, 0.095, 2)


def projected(truth: Trajectory, k: int, q: Draw, rng=None) -> Trajectory:
    """What an actor at epoch k plans against: observed values up to k, then
    growth and learning at the rates of scenario q."""
    K = truth.K
    fuel = truth.fuel_price[:k + 1] + [truth.fuel_price[k] * (1 + q.fuel_growth) ** (j - k) for j in range(k + 1, K)]
    dem = truth.demand_mult[:k + 1] + [truth.demand_mult[k] * (1 + q.demand_growth) ** (j - k) for j in range(k + 1, K)]
    rate = {"SOLAR_R": q.solar, "SOLAR_D": q.solar, "WIND_R": q.wind, "BATT_H": q.batt}
    mult = {d: truth.cost_mult[d][:k + 1] + [truth.cost_mult[d][k] * (1 - rate[d]) ** (j - k) for j in range(k + 1, K)]
            for d in LEARNED}
    true_from = truth.avail_from.get("BATT_H", 0)
    if true_from <= k:
        batt_from = true_from                      # already observed
    elif rng is not None:
        batt_from = int(rng.integers(k + 1, 5)) if k + 1 <= 4 else k + 1
    else:
        batt_from = max(k + 1, int(round((k + 1 + 4) / 2)))  # conditional mean
    return Trajectory(K=K, fuel_price=fuel, demand_mult=dem, cost_mult=mult,
                      avail_from={"BATT_H": batt_from}, discount=truth.discount)


def run_planner(sc, truth: Trajectory, prm, history0: List[Vintage], mode: str,
                horizon: int = 4, S: int = 5, seed: int = 0, m_new=None):
    """mode: 'stochastic' | 'mean' | 'perfect' (rolling, same horizon, true future)."""
    history = [replace(v) for v in history0]
    record = []
    for k in range(truth.K):
        k1 = min(truth.K - 1, k + horizon - 1)
        if mode == "perfect":
            sol = solve_window(sc, truth, prm, k, k1, history, m_new)
        elif mode == "mean":
            sol = solve_window(sc, projected(truth, k, MEAN), prm, k, k1, history, m_new)
        else:
            rng = np.random.default_rng(seed * 100 + k)
            trajs = [projected(truth, k, sample_prior(rng), rng) for _ in range(S)]
            sol = solve_window_stochastic(sc, trajs, [1.0 / S] * S, prm, k, k1, history, m_new)
        record.append(sol["epochs"][k])
        for i, v in enumerate(history):
            v.alive = sol["hist_alive"][i, k]
        for (n, v), x in sol["build"].items():
            if v == k and x > 1e-4:
                d = sc.designs[n]
                history.append(Vintage(n, k, x, sol["new_alive"].get((n, k, k), x),
                                       d.annual_cost * truth.mult(n, k), d.fixed_cost * truth.mult(n, k),
                                       prm.life[n]))
    return {"epochs": record}
