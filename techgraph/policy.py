"""Generic policy primitives over the technology network (see TECHGRAPH_SPACE_AND_POLICY_DESIGN.md).

Every rule is defined on measures: weighted sums over network quantities, selected by filters. Nothing here is
specific to a substance or a sector. Domain rules (portfolio standards, capacity accreditation, emission caps,
withdrawal permits, safe-yield requirements) are parameterizations of these primitives.

Measure kinds available inside a planning window:
  flow            sum_t W_t * H * activity of the selected designs (output, transport flow)
  capacity        installed capacity of the selected designs
  capacity_hours  installed capacity times the hours represented (H * sum W), for capacity-factor limits
  demand          weighted annual demand, optionally filtered by owner, segment and location
  byproduct       recorded byproduct (e.g. emissions) of the window
  stock           level of storage designs or of residual stocks (stocks.py); aggregate value = closing level
  boundary        net inflow across the boundary of a set of locations, on transport designs

Per-period rules (Requirement.per_period) evaluate measures as rates in each period: flows and demand in MW-like
units per hour, stock levels as levels. Byproducts are available only as annual totals.

Location filters accept a tuple of locations or a dict {location: weight}; a dict expresses fractional membership,
for example a partition from the spatial layer resolved to location weights.

Primitives:
  Requirement  sum(coef * measure) on the left, compared (>= or <=) with sum(coef * measure) + bound on the right,
               with an optional escape: a price per unit of shortfall and limited cheaper tiers.
  Adequacy     sum(rating * capacity) >= (1 + margin) * demand at the stress condition, where demand can exclude
               a credited share of flexible demand.
  Charge       a price on measures, classified as a resource cost or a transfer, with the amount reported.
Priority among demands is expressed on demands themselves (demands.Demand.shortage_cost); see apply_priority.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple, Union
from .backend import lp

Locs = Optional[Union[Tuple[str, ...], Dict[str, float]]]


def sched(values, k):
    """A scalar or a per-epoch schedule."""
    if values is None:
        return None
    if isinstance(values, (int, float)):
        return float(values)
    return float(values[k])


def _locw(locations, loc):
    if locations is None:
        return 1.0
    if isinstance(locations, dict):
        return float(locations.get(loc, 0.0))
    return 1.0 if loc in locations else 0.0


@dataclass(frozen=True)
class Measure:
    kind: str                                    # flow | capacity | capacity_hours | demand | byproduct | stock | boundary
    designs: Optional[Tuple[str, ...]] = None    # for flow and capacity kinds
    weights: Optional[Dict[str, float]] = None   # per-design weights (default 1)
    owners: Optional[Tuple[str, ...]] = None     # for demand: owner filter
    segments: Optional[Tuple[str, ...]] = None   # for demand: segment filter
    locations: Locs = None                       # location filter or fractional weights
    form: Optional[str] = None                   # for demand: the substance (None = electricity, legacy behavior)


@dataclass
class Context:
    """What a planning window exposes to rules for one epoch."""
    rec: dict          # design -> list of activity variables per period
    cap: dict          # design -> capacity variable
    emis: list         # byproduct terms
    demands: dict      # (location, period) -> MW
    parts: dict        # demand name -> (owner, segment, location, profile, firm_profile)
    W: Sequence[float]
    H: float
    T: int
    design_loc: dict   # design -> location (for location-filtered flows and capacities)
    acts: dict = None  # design -> activity series (output, charge/discharge/level, forward/backward)
    stocks: dict = None  # residual stock name -> handle with 'levels'
    designs: dict = None # design name -> Design (for transport endpoints)


def _boundary_terms(m, ctx):
    """(sign, series) pairs for net inflow into the location set m.locations on transport designs."""
    inside = (lambda l: _locw(m.locations, l) >= 0.5)
    out = []
    for n, d in (ctx.designs or {}).items():
        if getattr(d, 'kind', None) != 'transport' or n not in (ctx.acts or {}):
            continue
        if m.designs is not None and n not in m.designs:
            continue
        a, b = inside(getattr(d, 'loc_from', None)), inside(getattr(d, 'loc_to', None))
        if a == b:
            continue
        sign = 1.0 if b else -1.0                       # forward flow enters the set if the destination is inside
        act = ctx.acts[n]
        if 'forward' in act: out.append((sign, act['forward']))
        if 'backward' in act: out.append((-sign, act['backward']))
    return out


def value(m: Measure, ctx: Context, t=None):
    """LP expression (or number) for a measure: annual total (t=None) or rate in period t."""
    wt = m.weights or {}
    per = range(ctx.T) if t is None else (t,)
    scale = (lambda tt: ctx.W[tt] * ctx.H) if t is None else (lambda tt: 1.0)
    if m.kind in ('flow', 'capacity', 'capacity_hours'):
        names = [n for n in (m.designs or ()) if (n in ctx.rec if m.kind == 'flow' else n in ctx.cap)]
        lw = lambda n: _locw(m.locations, ctx.design_loc.get(n)) if m.locations is not None else 1.0
        if m.kind == 'flow':
            return lp.lpSum(wt.get(n, 1.0) * lw(n) * scale(tt) * ctx.rec[n][tt] for n in names for tt in per)
        cap = lp.lpSum(wt.get(n, 1.0) * lw(n) * ctx.cap[n] for n in names)
        return cap if m.kind == 'capacity' else ctx.H * sum(ctx.W) * cap
    if m.kind == 'demand':
        if m.form is not None and m.form != 'elec':
            return sum(scale(tt) * p[3][tt] * _locw(m.locations, p[2]) for p in ctx.parts.values()
                       if len(p) > 5 and p[5] == m.form and (m.owners is None or p[0] in m.owners)
                       and (m.segments is None or p[1] in m.segments) for tt in per)
        if m.owners is None and m.segments is None:
            return sum(scale(tt) * q * _locw(m.locations, l) for (l, tt), q in ctx.demands.items() if tt in per)
        return sum(scale(tt) * prof[tt] * _locw(m.locations, loc)
                   for (own, seg, loc, prof, *_r) in ctx.parts.values()
                   if (m.owners is None or own in m.owners) and (m.segments is None or seg in m.segments)
                   for tt in per)
    if m.kind == 'byproduct':
        if t is not None:
            raise ValueError('Byproducts are available only as annual totals')
        return lp.lpSum(ctx.emis)
    if m.kind == 'stock':
        tt = (ctx.T - 1) if t is None else t
        terms = []
        for n in (m.designs or ()):
            if ctx.acts and n in ctx.acts and 'level' in ctx.acts[n]:
                terms.append(wt.get(n, 1.0) * ctx.acts[n]['level'][tt])
            elif ctx.stocks and n in ctx.stocks:
                lv = ctx.stocks[n]['levels']; terms.append(wt.get(n, 1.0) * lv[min(tt + 1, len(lv) - 1)])
        return lp.lpSum(terms)
    if m.kind == 'boundary':
        return lp.lpSum(sign * scale(tt) * series[tt] for sign, series in _boundary_terms(m, ctx) for tt in per)
    raise ValueError(f'Unknown measure kind {m.kind!r}')


@dataclass(frozen=True)
class Requirement:
    name: str
    sense: str                                        # '>=' (floor or minimum share) or '<=' (ceiling or cap)
    lhs: Tuple[Tuple[object, Measure], ...]           # (coefficient or schedule, measure)
    rhs: Tuple[Tuple[object, Measure], ...] = ()
    bound: object = None                              # constant or schedule added to the right side
    escape_price: Optional[float] = None              # price per unit of shortfall; None = strict
    escape_tiers: Tuple[Tuple[float, float], ...] = ()  # (price, max share of the right side), floors only
    unit: str = ''                                    # reporting unit of the implicit price
    annualized_escape: bool = False                   # escape price per year on a capacity quantity
    escape_steps: Tuple[Tuple[float, float], ...] = ()  # (price, max quantity): an outside pool as a supply curve
    per_period: bool = False                          # hold in every period (rates), e.g. minimum flows or levels
    periods: Optional[Tuple[int, ...]] = None         # subset of periods for per-period rules
    kind: str = 'Requirement'                         # reported kind (legacy class name when converted)


@dataclass(frozen=True)
class Adequacy:
    name: str
    ratings: Dict[str, float]                         # design -> share of capacity that counts at the stress condition
    margin: object = 0.0
    periods: Optional[Tuple[int, ...]] = None         # stress condition; None = all periods (peak over the horizon)
    owners: Optional[Tuple[str, ...]] = None
    segments: Optional[Tuple[str, ...]] = None
    locations: Optional[Tuple[str, ...]] = None
    credit_flexibility: bool = False
    flexibility_credit: float = 1.0
    escape_price: Optional[float] = None              # per MW-yr
    kind: str = 'Adequacy'


def _terms(terms, ctx, k, t=None):
    return lp.lpSum(sched(c, k) * value(m, ctx, t) for c, m in terms) if terms else 0


def _one(prob, r, lhs, rhs, cname, slack, w, price_scale, label):
    obj, tiers = [], []
    if r.sense == '>=':
        for j, (price, max_share) in enumerate(r.escape_tiers):
            v = lp.LpVariable(f'tier{j}_{label}', lowBound=0)
            prob += v <= max_share * rhs, f'{cname}_tier{j}'
            obj.append(w * price * v); tiers.append(v)
    for j, (price, qmax) in enumerate(r.escape_steps):
        v = lp.LpVariable(f'step{j}_{label}', lowBound=0, upBound=qmax)
        obj.append(w * price * v); tiers.append(v)
    relief = lp.lpSum(tiers) + (slack if slack is not None else 0)
    if r.sense == '>=':
        prob += (lhs + relief) >= rhs, cname
    elif r.sense == '<=':
        prob += (lhs - relief) <= rhs, cname
    else:
        raise ValueError(f'Unknown sense {r.sense!r}')
    if slack is not None:
        obj.append(w * r.escape_price / price_scale * slack)
    return obj, tiers


def add_requirement(prob, r: Requirement, ctx: Context, k, cname, slack, w, annual_factor):
    """Add one requirement for epoch k. Returns (objective terms, tier variables, unit, price_scale, audit).

    audit holds the left and right sides (expressions) so that results can be checked against the rule."""
    price_scale = annual_factor if r.annualized_escape else 1.0
    if not r.per_period:
        lhs = _terms(r.lhs, ctx, k); rhs = _terms(r.rhs, ctx, k) + (sched(r.bound, k) or 0.0)
        obj, tiers = _one(prob, r, lhs, rhs, cname, slack, w, price_scale, cname[5:])
        return obj, tiers, r.unit, price_scale, dict(sense=r.sense, lhs=[lhs], rhs=[rhs], relief=[tiers + ([slack] if slack is not None else [])])
    obj, tiers, L, R, F = [], [], [], [], []
    for t in (r.periods if r.periods is not None else range(ctx.T)):
        lhs = _terms(r.lhs, ctx, k, t); rhs = _terms(r.rhs, ctx, k, t) + (sched(r.bound, k) or 0.0)
        st = lp.LpVariable(f'{slack.name}_t{t}', lowBound=0) if slack is not None else None
        o_, tr = _one(prob, r, lhs, rhs, f'{cname}_t{t}', st, w * ctx.W[t] * ctx.H, price_scale, f'{cname[5:]}_t{t}')
        obj += o_; tiers += tr; L.append(lhs); R.append(rhs); F.append(tr + ([st] if st is not None else []))
    return obj, tiers, r.unit, price_scale, dict(sense=r.sense, lhs=L, rhs=R, relief=F)


@dataclass(frozen=True)
class Charge:
    name: str
    terms: Tuple[Tuple[object, Measure], ...]         # (price or schedule, measure): amount = sum(price * measure)
    accounting: str = 'transfer'                      # 'transfer' (e.g. a tax or allowance payment) or 'resource'
    kind: str = 'Charge'
    escape_price: Optional[float] = None              # unused; charges have no shortfall


def add_charge(prob, c: Charge, ctx: Context, k, w):
    amount = _terms(c.terms, ctx, k)
    return [w * amount], amount


def apply_priority(demands, ranking, top_value, ratio=0.5):
    """Give demands shortage costs that decrease with rank: ranking is a list of (owner, segment) keys, highest
    priority first (None matches any). The first rank gets top_value, each next rank `ratio` times the previous.
    Returns new Demand objects; demands not ranked keep their shortage cost."""
    from dataclasses import replace as _r
    out = []
    for d in demands:
        val = None
        for i, (own, seg) in enumerate(ranking):
            if (own is None or d.owner == own) and (seg is None or d.segment == seg):
                val = top_value * ratio ** i; break
        out.append(_r(d, shortage_cost=val) if val is not None else d)
    return out


def lagged(schedule: Dict[int, float], lag: int) -> Dict[int, float]:
    """A process rule: what is in service in year y equals what was approved by year y - lag."""
    return {y + lag: v for y, v in schedule.items()}


def adequacy_peak(a: Adequacy, ctx: Context):
    """Demand at the stress condition, net of credited flexibility."""
    periods = range(ctx.T) if a.periods is None else a.periods
    locs = a.locations
    if a.credit_flexibility or a.owners is not None or a.segments is not None:
        parts = [p for p in ctx.parts.values()
                 if (a.owners is None or p[0] in a.owners) and (a.segments is None or p[1] in a.segments)
                 and (locs is None or p[2] in locs)]
        if not parts:
            return 0.0
        if a.credit_flexibility:
            phi = a.flexibility_credit
            return max(sum(p[3][t] - phi * (p[3][t] - p[4][t]) for p in parts) for t in periods)
        return max(sum(p[3][t] for p in parts) for t in periods)
    return max(sum(q for (l, t), q in ctx.demands.items() if t == tt and (locs is None or l in locs)) for tt in periods)


def add_adequacy(prob, a: Adequacy, ctx: Context, k, cname, slack, w, annual_factor):
    peak = adequacy_peak(a, ctx)
    lhs = lp.lpSum(r * ctx.cap[n] for n, r in a.ratings.items() if n in ctx.cap)
    prob += (lhs + (slack if slack is not None else 0)) >= (1 + sched(a.margin, k)) * peak, cname
    obj = [w * a.escape_price / annual_factor * slack] if slack is not None else []
    return obj, [], 'MW', annual_factor, dict(sense='>=', lhs=[lhs], rhs=[(1 + sched(a.margin, k)) * peak], relief=[[slack] if slack is not None else []])
