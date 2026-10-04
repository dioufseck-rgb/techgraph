"""Institutions as declared constraints on the technology layer (opt-in, v4 extension).

Institutions act on the technology layer at four points:
  1. what may be built, where and when      -> existing: forbid, Trajectory.avail_from / avail_until
  2. how fast it may be built                 -> existing: Trajectory.build_rate
  3. prices of building and operating         -> existing: Trajectory.cost_mult, fuel_price
  4. aggregate requirements across designs    -> this module
Rules that act on agents (cost allocation, export credits, siting choices) belong to the society
layer outside the substrate.

Each institution here is a declared object with a per-epoch schedule. It may carry an escape valve
(a compliance payment or price cap): the requirement can be missed at a stated price per unit of
shortfall. Each reports its implicit price, the dual of its constraint, which measures institutional
pressure in the same currency as the network's mismatch signals.

Kinds:
  EnergyShare        : sum of members' energy >= share x (demand energy - excluded designs' energy)
                       e.g. a renewable portfolio standard defined on non-nuclear retail sales.
  CapacityQuantity   : sum of members' capacity >= minimum (e.g. a storage procurement mandate).
  AccreditedCapacity : sum of accreditation_d x capacity_d >= (1 + margin) x peak demand
                       (a resource adequacy requirement with effective-load-carrying ratings; with
                       `locations`, a deliverability requirement for a constrained area).
  EmissionCap        : recorded emissions <= cap (optional price ceiling).

Usage: pass `institutions=[...]` to `dynamic.solve_window`. With no institutions the window is
unchanged, so default behavior is identical to v4.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from .backend import lp
from .policy import Measure, Requirement, Adequacy, Charge, Context, add_requirement, add_adequacy, add_charge


def _sched(values, k):
    if isinstance(values, (int, float)):
        return float(values)
    return float(values[k])


@dataclass(frozen=True)
class EnergyShare:
    name: str
    members: Tuple[str, ...]
    share: object                       # float or per-epoch list
    excluded: Tuple[str, ...] = ()      # designs whose energy is removed from the base (e.g. nuclear)
    escape_price: Optional[float] = None   # $/MWh compliance payment; None = hard requirement
    escape_tiers: Tuple[Tuple[float, float], ...] = ()  # cheaper limited valves: (price, max share of the requirement),
                                                        # e.g. out-of-state credits allowed up to 25% of the requirement
    base_owners: Optional[Tuple[str, ...]] = None      # base = demand of these owners only (e.g. one utility's retail sales)
    base_segments: Optional[Tuple[str, ...]] = None    # ... and/or these segments; None = all demand


@dataclass(frozen=True)
class CapacityQuantity:
    name: str
    members: Tuple[str, ...]
    minimum: object                     # MW, float or per-epoch list
    escape_price: Optional[float] = None   # $/MW-yr


@dataclass(frozen=True)
class AccreditedCapacity:
    name: str
    accreditation: Dict[str, float]     # design -> fraction of capacity that counts
    margin: object = 0.0
    escape_price: Optional[float] = None   # $/MW-yr (a price cap on capacity)
    locations: Optional[Tuple[str, ...]] = None   # peak of demand at these locations only (a locational
                                                  # deliverability requirement); None = whole system
    owners: Optional[Tuple[str, ...]] = None      # peak of these owners' demand only (an entity's obligation)
    segments: Optional[Tuple[str, ...]] = None
    flexibility_credit: float = 1.0               # share of the flexible part credited when credit_flexibility is True
    credit_flexibility: bool = False              # True: the requirement covers only the firm (non-curtailable)
                                                  # part of flexible demands, as when a rule accepts curtailable load


@dataclass(frozen=True)
class EmissionCap:
    name: str
    cap: object                         # tCO2 per representative block
    escape_price: Optional[float] = None


@dataclass(frozen=True)
class EnergyCeiling:
    """Upper limit on the energy of a group of designs.

    share_of_demand: energy of members <= share x annual demand energy (e.g. an import reliance cap).
    capacity_factor: energy of members <= capacity_factor x 8760 x installed capacity of members
    (e.g. peaking resources limited to a capacity factor). weights optionally scale each member's energy
    (e.g. only part of an aggregated resource counts toward the limit)."""
    name: str
    members: Tuple[str, ...]
    share_of_demand: object = None
    capacity_factor: object = None
    weights: Optional[Dict[str, float]] = None
    escape_price: Optional[float] = None


def _energy(rec, H, names, T, W=None):
    W = W or [1.0] * T
    return lp.lpSum(W[t] * H * rec[n][t] for n in names if n in rec for t in range(T))


def _neg(sched_value):
    return [-float(x) for x in sched_value] if isinstance(sched_value, (list, tuple)) else -float(sched_value)


def to_primitive(inst):
    """Convert a legacy rule declaration into a generic policy primitive (policy.Requirement or policy.Adequacy)."""
    if isinstance(inst, (Requirement, Adequacy, Charge)):
        return inst
    if isinstance(inst, EnergyShare):
        return Requirement(inst.name, '>=', lhs=((1.0, Measure('flow', tuple(inst.members))),),
                           rhs=((inst.share, Measure('demand', owners=inst.base_owners, segments=inst.base_segments)),
                                (_neg(inst.share), Measure('flow', tuple(inst.excluded)))),
                           escape_price=inst.escape_price, escape_tiers=tuple(inst.escape_tiers), unit='MWh', kind='EnergyShare')
    if isinstance(inst, CapacityQuantity):
        return Requirement(inst.name, '>=', lhs=((1.0, Measure('capacity', tuple(inst.members))),), bound=inst.minimum,
                           escape_price=inst.escape_price, unit='MW', annualized_escape=True, kind='CapacityQuantity')
    if isinstance(inst, EnergyCeiling):
        if inst.share_of_demand is not None:
            rhs = ((inst.share_of_demand, Measure('demand')),)
        else:
            rhs = ((inst.capacity_factor, Measure('capacity_hours', tuple(inst.members))),)
        return Requirement(inst.name, '<=', lhs=((1.0, Measure('flow', tuple(inst.members), weights=inst.weights)),), rhs=rhs,
                           escape_price=inst.escape_price, unit='MWh', kind='EnergyCeiling')
    if isinstance(inst, EmissionCap):
        return Requirement(inst.name, '<=', lhs=((1.0, Measure('byproduct')),), bound=inst.cap,
                           escape_price=inst.escape_price, unit='t', kind='EmissionCap')
    if isinstance(inst, AccreditedCapacity):
        return Adequacy(inst.name, ratings=dict(inst.accreditation), margin=inst.margin, owners=inst.owners, segments=inst.segments,
                        locations=inst.locations, credit_flexibility=inst.credit_flexibility, flexibility_credit=inst.flexibility_credit,
                        escape_price=inst.escape_price, kind='AccreditedCapacity')
    raise TypeError(f'Unknown institution {inst!r}')


def add_institutions(prob, sc, k0, k1, ops, institutions, tag='', discount=1.0, annual_factor=365.0):
    """Add institutional constraints for epochs k0..k1. Returns (objective_terms, handles).

    Every rule is converted to a generic primitive (policy.Requirement or policy.Adequacy) and evaluated on
    measures of the window; the legacy classes are declarations only."""
    H, T = sc.hours, sc.periods
    from .operation import period_weights
    W = period_weights(sc)
    design_loc = {n: getattr(d, 'loc', None) for n, d in sc.designs.items()}
    prims = [to_primitive(i) for i in institutions]
    obj, handles = [], []
    for k in range(k0, k1 + 1):
        o = ops[k]
        phys = o['states'][0]['flow']['physical']
        ctx = Context(rec=o['rec'], cap=o['cap'], emis=o['emis'], demands=phys['demands'], parts=phys.get('demand_parts', {}),
                      W=W, H=H, T=T, design_loc=design_loc, acts=phys.get('activities', {}), stocks=o.get('stocks') or {},
                      designs=sc.designs)
        w = discount ** k
        for prim in prims:
            cname = f'inst_{prim.name}{tag}_{k}'
            slack = lp.LpVariable(f'slack_{prim.name}{tag}_{k}', lowBound=0) if prim.escape_price is not None else None
            if isinstance(prim, Charge):
                terms, amount = add_charge(prob, prim, ctx, k, w)
                obj += terms
                handles.append(dict(name=prim.name, kind=prim.kind, epoch=k, constraint=None, slack=None, unit='$',
                                    price_scale=1.0, weight=w, tiers=[], amount=amount, accounting=prim.accounting))
                continue
            if isinstance(prim, Requirement):
                terms, tiers, unit, price_scale, audit = add_requirement(prob, prim, ctx, k, cname, slack, w, annual_factor)
            else:
                terms, tiers, unit, price_scale, audit = add_adequacy(prob, prim, ctx, k, cname, slack, w, annual_factor)
            obj += terms
            handles.append(dict(name=prim.name, kind=prim.kind, epoch=k, constraint=cname, slack=slack, unit=unit,
                                price_scale=price_scale, weight=w, tiers=tiers, audit=audit,
                                per_period=getattr(prim, 'per_period', False)))
    return obj, handles


def _val(x):
    return float(lp.value(x) or 0.0) if not isinstance(x, (int, float)) else float(x)


def extract_institutions(prob, handles):
    """Implicit price (dual), shortfall, and audit per institution and epoch.

    Prices are per unit: $/MWh for energy measures, $/MW-yr for capacity requirements, $/t for byproduct caps.
    Duals are available for pure LP windows; for MIP windows the price is reported as None. For per-period rules the
    price reported is that of the most constrained period. Charges report their amount and accounting class.
    The audit gives the largest violation of the rule by the reported solution, counting escapes as relief."""
    out = []
    for h in handles:
        if h.get('constraint') is None:          # a charge
            out.append(dict(name=h['name'], kind=h['kind'], epoch=h['epoch'], implicit_price=None, unit='$', shortfall=0.0,
                            tier_use=[], amount=_val(h['amount']), accounting=h['accounting'], violation=0.0))
            continue
        cons = prob.constraints
        names = [h['constraint']] if not h.get('per_period') else [n for n in cons if n.startswith(h['constraint'] + '_t') and '_tier' not in n]
        pis = []
        for n in names:
            c = cons.get(n) if hasattr(cons, 'get') else cons[n]
            pi = getattr(c, 'pi', None)
            if pi is not None: pis.append(abs(float(pi)))
        price = (max(pis) * h['price_scale'] / h['weight']) if pis else None
        a = h.get('audit') or {}
        viol = 0.0
        for L, R, F in zip(a.get('lhs', []), a.get('rhs', []), a.get('relief', [])):
            l, r, f = _val(L), _val(R), sum(_val(x) for x in F)
            viol = max(viol, (r - l - f) if a['sense'] == '>=' else (l - f - r))
        if h.get('per_period'):
            shortfall = sum(_val(v) for F in a.get('relief', []) for v in F[-1:]) if h['slack'] is not None else 0.0
        else:
            shortfall = float(lp.value(h['slack']) or 0.0) if h['slack'] is not None else 0.0
        out.append(dict(name=h['name'], kind=h['kind'], epoch=h['epoch'], implicit_price=price, unit=h['unit'],
                        shortfall=shortfall, tier_use=[_val(v) for v in h.get('tiers', [])],
                        lhs=[_val(x) for x in a.get('lhs', [])], rhs=[_val(x) for x in a.get('rhs', [])], violation=viol))
    return out
