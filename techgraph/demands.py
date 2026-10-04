"""Demands associated with actors (opt-in, v4 extension).

A `Demand` is a load with a location, an hourly profile, an owner (the entity that serves it, such as a
utility or a cooperative) and a segment (such as residential or data centers). Demands at the same
location are added together in the physical balance, so the network sees one load per location, as
before. Their identity is kept for two purposes:

  - institutions can define their base by owner and segment (for example, a portfolio standard that
    applies only to one utility's retail sales, or an adequacy obligation for one load-serving entity);
  - cost accounting can attribute peak and energy to owners and segments.

The legacy `Scenario.extra_demand` field keeps working; its entries are treated as demands with no
owner or segment. With no demands declared, every equation is unchanged.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Demand:
    name: str
    location: str
    profile: Tuple[float, ...]          # MW per period
    owner: str = ''
    segment: str = ''
    form: str = 'elec'                  # the substance demanded (electricity by default)
    # Flexibility (all zero = inflexible). Curtailment: up to curtail_max_frac of the load in any period,
    # within an annual energy budget of curtail_budget (fraction of the demand's annual energy), at
    # curtail_cost $/MWh; moving work out of the system counts as curtailment from the system's view.
    # Shifting: up to shift_frac of the load moved between periods of the same representative day,
    # energy-neutral within the day, at shift_cost $/MWh moved.
    curtail_max_frac: float = 0.0
    curtail_budget: float = 0.0
    curtail_cost: float = 0.0
    shift_frac: float = 0.0
    shift_cost: float = 0.0
    curtail_daily_hours: float = 0.0   # if > 0: curtailed energy in any 24-hour day <= this many hours at full depth
    shortage_cost: Optional[float] = None   # if set: the demand can go unserved at this cost per MWh (priority)

    @property
    def flexible(self) -> bool:
        return (self.curtail_max_frac > 0 and self.curtail_budget > 0) or self.shift_frac > 0 or self.shortage_cost is not None


def all_demands(sc) -> List[Demand]:
    """Declared demands plus legacy extra_demand entries (as anonymous demands)."""
    out = [Demand(f'extra_{loc}', loc, tuple(p)) for loc, p in sc.extra_demand.items()]
    out += list(getattr(sc, 'demands', ()) or ())
    for d in out:
        if len(d.profile) != sc.periods:
            raise ValueError(f'Demand {d.name} must have one value per period')
        if d.location not in sc.locations:
            raise ValueError(f'Demand {d.name} is at unknown location {d.location}')
    names = [d.name for d in out]
    if len(names) != len(set(names)):
        raise ValueError('Demand names must be unique')
    return out


def location_demand(sc) -> Dict[str, List[float]]:
    """Total electricity demand per location and period, summed over all electricity demands."""
    tot: Dict[str, List[float]] = {}
    for d in all_demands(sc):
        if d.form != 'elec':
            continue
        acc = tot.setdefault(d.location, [0.0] * sc.periods)
        for t, q in enumerate(d.profile):
            acc[t] += q
    return tot


def form_demand(sc) -> Dict[Tuple[str, str], List[float]]:
    """Demand for substances other than electricity: (form, location) -> per-period quantity."""
    tot: Dict[Tuple[str, str], List[float]] = {}
    for d in all_demands(sc):
        if d.form == 'elec':
            continue
        acc = tot.setdefault((d.form, d.location), [0.0] * sc.periods)
        for t, q in enumerate(d.profile):
            acc[t] += q
    return tot


def select(demands: Iterable[Demand], owners: Optional[Tuple[str, ...]] = None,
           segments: Optional[Tuple[str, ...]] = None, locations: Optional[Tuple[str, ...]] = None) -> List[Demand]:
    """Demands matching all given filters (None means no filter)."""
    return [d for d in demands
            if (owners is None or d.owner in owners)
            and (segments is None or d.segment in segments)
            and (locations is None or d.location in locations)]


def shares(sc, by: str = 'owner', at: str = 'peak', dm: float = 1.0) -> Dict[str, float]:
    """Share of coincident system peak ('peak') or of weighted energy ('energy') by owner or segment.

    The coincident peak is the period with the largest total demand. Energy uses period weights
    when representative days are declared."""
    from .operation import period_weights
    ds = all_demands(sc)
    key = (lambda d: d.owner) if by == 'owner' else (lambda d: d.segment) if by == 'segment' else None
    if key is None:
        raise ValueError("by must be 'owner' or 'segment'")
    if at == 'peak':
        totals = [sum(d.profile[t] for d in ds) for t in range(sc.periods)]
        tp = max(range(sc.periods), key=lambda t: totals[t])
        vals = {}
        for d in ds:
            vals[key(d)] = vals.get(key(d), 0.0) + d.profile[tp]
    elif at == 'energy':
        W = period_weights(sc)
        vals = {}
        for d in ds:
            vals[key(d)] = vals.get(key(d), 0.0) + sum(W[t] * q for t, q in enumerate(d.profile))
    else:
        raise ValueError("at must be 'peak' or 'energy'")
    s = sum(vals.values())
    return {k: v / s for k, v in vals.items()} if s > 0 else vals


def add_flexibility(prob, sc, balance, cost, H, W, tag, dm=1.0, lp=None):
    """Add curtailment and shifting variables for flexible demands. Returns {name: series}.

    Curtailment and downward shifts appear on the supply side of the location's balance; upward
    shifts add to demand. Costs are weighted by the period weights."""
    if lp is None:
        from .backend import lp
    from .operation import cycle_blocks
    out = {}
    blocks = cycle_blocks(sc)
    for d in all_demands(sc):
        if not d.flexible:
            continue
        T = sc.periods
        q = [dm * x for x in d.profile]
        rec = {}
        if d.curtail_max_frac > 0 and d.curtail_budget > 0:
            c = [lp.LpVariable(f'curt_{d.name}_{tag}_{t}', 0, d.curtail_max_frac * q[t]) for t in range(T)]
            prob += (lp.lpSum(W[t] * H * c[t] for t in range(T))
                     <= d.curtail_budget * sum(W[t] * H * q[t] for t in range(T))), f'curt_budget_{d.name}_{tag}'
            if d.curtail_daily_hours > 0:
                for start, L in blocks:
                    for day0 in range(start, start + L, 24):
                        day = range(day0, min(day0 + 24, start + L))
                        prob += (lp.lpSum(c[t] for t in day) <= d.curtail_daily_hours * d.curtail_max_frac * max(q[t] for t in day)), f'curt_day_{d.name}_{tag}_{day0}'
            for t in range(T):
                balance[(d.form, d.location, t)].append(H * c[t])
                cost.append(W[t] * d.curtail_cost * H * c[t])
            rec['curtail'] = c
        if d.shortage_cost is not None:
            u = [lp.LpVariable(f'short_{d.name}_{tag}_{t}', 0, q[t]) for t in range(T)]
            for t in range(T):
                balance[(d.form, d.location, t)].append(H * u[t])
                cost.append(W[t] * d.shortage_cost * H * u[t])
            rec['shortage'] = u
        if d.shift_frac > 0:
            up = [lp.LpVariable(f'shup_{d.name}_{tag}_{t}', 0, d.shift_frac * q[t]) for t in range(T)]
            dn = [lp.LpVariable(f'shdn_{d.name}_{tag}_{t}', 0, d.shift_frac * q[t]) for t in range(T)]
            for start, L in blocks:
                prob += lp.lpSum(up[t] - dn[t] for t in range(start, start + L)) == 0, f'shift_day_{d.name}_{tag}_{start}'
            for t in range(T):
                balance[(d.form, d.location, t)].append(H * (dn[t] - up[t]))
                cost.append(W[t] * d.shift_cost * H * dn[t])
            rec['shift_up'], rec['shift_down'] = up, dn
        out[d.name] = rec
    return out


def firm_profile(d: Demand):
    """The part of a demand that can be neither curtailed nor shifted away from a given hour.

    Used by adequacy rules that credit flexibility. The credit is valid only when the requirement binds
    in few enough hours for the curtailment budget (and shifting room) to cover them; a requirement that
    binds most hours, such as transport into a region with flat load, should not credit it."""
    flex = 0.0
    if d.curtail_max_frac > 0 and d.curtail_budget > 0:
        flex += d.curtail_max_frac
    flex += d.shift_frac
    flex = min(flex, 1.0)
    return tuple(x * (1 - flex) for x in d.profile) if flex > 0 else d.profile
