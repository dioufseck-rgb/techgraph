"""Analysis tools: incumbent systems, counterfactual values, dual screening."""
from itertools import combinations
from typing import Dict, Iterable, List, Tuple
from .backend import lp, mip_solver, lp_solver, solver_metadata, require_optimal

from .catalog import Scenario
from .model import solve, check_balances, Result, DAYS_PER_YEAR

INCUMBENT_LANDSCAPE = ("GEN_D", "FUEL_TRANS", "FUEL_STORE_D", "SOLAR_D", "LINE_HD")
CANDIDATES = ("GEN_R", "SOLAR_R", "WIND_R", "LINE_RH", "BATT_H")


def verified(sc: Scenario, res: Result) -> Result:
    if res.status != "Optimal":
        raise RuntimeError(f"solve status {res.status}")
    bad = check_balances(sc, res)
    if bad:
        raise AssertionError(f"balance residuals: {bad}")
    return res


def incumbent(sc: Scenario) -> Result:
    """The cost-minimizing system built from the incumbent landscape only."""
    return verified(sc, solve(sc, INCUMBENT_LANDSCAPE))


def J(sc: Scenario, existing: Dict[str, float], landscape: Iterable[str]) -> Result:
    """Optimal forward cost with sunk `existing` capacity and a given buildable landscape."""
    return verified(sc, solve(sc, landscape, existing=existing))


def value(sc: Scenario, existing: Dict[str, float], base: Iterable[str],
          bundle: Iterable[str]) -> Tuple[float, Result]:
    """V(B) = J*(L) - J*(L u B), in $/day. Same requirements, initial state and costs."""
    base = set(base)
    r0 = J(sc, existing, base)
    r1 = J(sc, existing, base | set(bundle))
    return r0.objective - r1.objective, r1


def operating_prices(sc: Scenario, existing: Dict[str, float]) -> Result:
    """Operate a fixed configuration as an LP and return its state prices."""
    from .needs import has_discrete_needs
    if has_discrete_needs(sc):
        raise ValueError("Indivisible optional service remains discrete at fixed capacity; use reoptimization, not LP prices")
    return verified(sc, solve(sc, [], existing=existing, fixed=True))


def _storage_surplus(prices: List[float], H: float, duration: float,
                     eta_c: float, eta_d: float) -> float:
    """Daily arbitrage surplus of 1 MWh of storage acting as a price-taker."""
    T = len(prices)
    p = lp.LpProblem("arb", lp.LpMaximize)
    c = [lp.LpVariable(f"c{t}", 0, 1.0 / duration) for t in range(T)]
    d = [lp.LpVariable(f"d{t}", 0, 1.0 / duration) for t in range(T)]
    s = [lp.LpVariable(f"s{t}", 0, 1.0) for t in range(T)]
    for t in range(T):
        p += s[(t + 1) % T] == s[t] + H * (eta_c * c[t] - (1.0 / eta_d) * d[t])
    p += lp.lpSum(H * prices[t] * (d[t] - c[t]) for t in range(T))
    p.solve(lp_solver(msg=False))
    require_optimal(p)
    return float(lp.value(p.objective))


def screen(sc: Scenario, priced: Result, candidates: Iterable[str]) -> Dict[str, float]:
    """Indicative net surplus per unit of new capacity ($/unit-day), from state prices.

    Uses g = value of outputs - value of inputs - variable cost at each period, taking
    each unit of capacity as fully used when g > 0. Fixed (lump) costs are ignored:
    this is a marginal screening signal, not an investment valuation.
    """
    H, T = sc.hours, sc.periods
    # A state absent from the configuration has no price: nothing can reach it or
    # leave it. Inputs from such a state are unavailable; outputs to it are worthless.
    pi = lambda f, l, t: priced.prices.get((f, l, t))
    out = {}
    for name in candidates:
        d = sc.designs[name]
        g = 0.0
        if d.kind in {"process","sink","withdraw"}:
            raise NotImplementedError("Use reoptimization for explicit-flow additions; legacy screening does not price closed residual destinations")
        if d.kind == "convert":
            for t in range(T):
                po, pin = pi(d.form_out, d.loc, t), pi(d.form_in, d.loc, t)
                if po is not None and pin is not None:
                    g += H * max(0.0, po - pin / d.eff - d.var_cost)
        elif d.kind == "renewable":
            prof = sc.profiles[d.profile]
            for t in range(T):
                po = pi("elec", d.loc, t)
                if po is not None:
                    g += H * prof[t] * max(0.0, po - d.var_cost)
        elif d.kind == "transport":
            for t in range(T):
                pa, pb = pi(d.form, d.loc_from, t), pi(d.form, d.loc_to, t)
                if pa is None or pb is None:
                    continue
                fw = (1 - d.loss) * pb - pa - d.var_cost
                bw = (1 - d.loss) * pa - pb - d.var_cost
                g += H * max(0.0, fw, bw if d.bidirectional else 0.0)
        elif d.kind == "store":
            prices = [pi(d.form, d.loc, t) for t in range(T)]
            if all(x is not None for x in prices):
                g = _storage_surplus(prices, H, d.duration_h, d.eta_c, d.eta_d)
        out[name] = g - sc.days * d.annual_cost / DAYS_PER_YEAR
    return out


def bundle_values(sc: Scenario, existing: Dict[str, float], base: Iterable[str],
                  candidates: Iterable[str], max_size: int = 2) -> Dict[Tuple[str, ...], float]:
    cands = list(candidates)
    vals = {}
    for k in range(1, max_size + 1):
        for b in combinations(cands, k):
            vals[b], _ = value(sc, existing, base, b)
    return vals


def capacity_rent_fd(sc: Scenario, existing: Dict[str, float], name: str,
                     delta: float = 1.0) -> Tuple[float, float]:
    """Finite-difference value of capacity for an installed design ($/unit per horizon).

    Returns (value of one more unit, cost of one less unit). Operating duals on
    capacity constraints are often degenerate at an optimized system; the two
    one-sided differences make that visible instead of hiding it.
    """
    op = lambda cap: (lambda r: r.objective - r.costs["existing_fom"])(operating_prices(sc, cap))
    base = op(existing)
    up = dict(existing); up[name] = existing.get(name, 0.0) + delta
    v_up = (base - op(up)) / delta
    v_down = float("nan")
    if existing.get(name, 0.0) >= delta:
        dn = dict(existing); dn[name] = existing[name] - delta
        v_down = (op(dn) - base) / delta
    return v_up, v_down


def generation_mix(sc: Scenario, res: Result) -> Dict[str, float]:
    H = sc.hours
    gen = {k: H * sum(v["output"]) for k, v in res.activity.items() if "output" in v}
    for n, v in res.activity.items():
        d=sc.designs[n]
        if d.kind=="process":
            coefficient=sum(p.coefficient for p in d.output_ports if p.form=="elec")
            if coefficient: gen[n]=H*coefficient*sum(v["activity"])
    tot = sum(gen.values()) or 1.0
    return {k: v / tot for k, v in gen.items()}


def architecture_label(sc: Scenario, res: Result, share: float = 0.05) -> str:
    mix = generation_mix(sc, res)
    parts = sorted(k for k, v in mix.items() if v >= share)
    if res.capacity.get("BATT_H", 0.0) > 1.0 and any(
            x > 1e-6 for x in res.activity.get("BATT_H", {}).get("discharge", [])):
        parts.append("BATT")
    return "+".join(parts) if parts else "none"
