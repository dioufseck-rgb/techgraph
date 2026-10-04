"""Techgraph v4: opt-in realism mechanisms.

Every mechanism here is disabled by default. With RealismConfig() the demand
campaign reproduces the frozen v3 histories exactly (verified by regression
test). Each mechanism answers one assumption flagged in the 29 September
model review:

  bins/intra_amplitude   two clocks: several operating bins per decision epoch
  lump_share             economies of scale through a fixed (lumpy) build cost
  corridors/congestion   shared transport infrastructure with a convex congestion proxy
  use_bias               search attention toward operated designs (in RecipeSearch)
  learning_*             learning by doing (in VSRConfig)
  raw_forms              several raw resources, unevenly placed
  variant_share          interface variants of forms, with adapters (in RecipeSearch)
  capability_*           calibrated capability costs and functional domains
  forecast               adaptive and oracle forecast rules (in VSRConfig)

Nothing here seeds an adoption sequence, a target architecture or an outcome.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from math import log, exp, isfinite
import numpy as np


@dataclass(frozen=True)
class RealismConfig:
    bins: int = 1
    intra_amplitude: float = 0.0      # within-epoch demand swing, mean-preserving
    lump_share: float = 0.0           # share of reference-scale capital that is indivisible
    lump_reference: float = 1.0       # reference capacity, as a multiple of base demand
    lump_scope: str = 'all'           # all (every process) | infrastructure (corridors only; tractable)
    corridors: bool = False
    corridor_share: float = 0.7       # share of transport capital moved to the shared corridor
    congestion_threshold: float = 0.8
    congestion_cost: float = 0.0      # per unit of flow above the threshold share
    use_bias: float = 0.0             # parent weight = 1 + use_bias for designs operated last epoch
    raw_forms: int = 1
    variant_share: float = 0.0        # share of search attempts spent on interface variants
    adapter_cost: tuple = (0.05, 0.25)  # adapter capital and variable cost as multiples of the source design
    capability_cost_scale: float = 1.0
    capability_domains: str = 'parity'  # parity (v3) | function
    relocation_fix: bool = False
    switching_cost: float = 0.0
    forecast: str = 'none'
    learning_rate: float = 0.0
    learning_reference: float = 4.0     # multiple of base demand

    def validate(self):
        if not isinstance(self.bins,int) or not 1<=self.bins<=24:raise ValueError('bins must be 1..24')
        if not 0<=self.intra_amplitude<1:raise ValueError('intra_amplitude must be in [0,1)')
        if not 0<=self.lump_share<1 or self.lump_reference<=0:raise ValueError('Invalid lump parameters')
        if self.lump_scope not in {'all','infrastructure'}:raise ValueError('Unknown lump scope')
        if self.lump_scope=='infrastructure' and self.lump_share>0 and not self.corridors:raise ValueError('Infrastructure lumps require corridors')
        if not 0<self.corridor_share<1 or not 0<self.congestion_threshold<=1 or self.congestion_cost<0:raise ValueError('Invalid corridor parameters')
        if self.use_bias<0 or not isinstance(self.raw_forms,int) or self.raw_forms<1:raise ValueError('Invalid search/resource parameters')
        if not 0<=self.variant_share<1:raise ValueError('variant_share must be in [0,1)')
        if self.capability_cost_scale<=0 or self.capability_domains not in {'parity','function'}:raise ValueError('Invalid capability parameters')
        if self.forecast not in {'none','oracle','ar1','holt'}:raise ValueError('Unknown forecast')
        if self.switching_cost<0 or self.learning_rate<0 or self.learning_reference<=0:raise ValueError('Invalid friction/learning parameters')
        return self

    def is_default(self):
        return self==RealismConfig()


REALISTIC = dict(bins=4, intra_amplitude=.3, lump_share=.3, corridors=True, congestion_cost=1.0,
                 use_bias=4.0, capability_cost_scale=10.0, capability_domains='function',
                 relocation_fix=True, switching_cost=0.5, forecast='ar1', learning_rate=.234)


# --------------------------------------------------------------------------
# Forecast rules

def _forecast_series(obs, horizon, rule):
    """Forecast `horizon` future values from observed positive levels obs[0..k]."""
    last = obs[-1]
    if rule == 'ar1':
        if len(obs) < 4 or min(obs) <= 0:
            return [last] * horizon
        x = np.log(np.asarray(obs, float)); mu = x.mean(); d = x - mu
        den = float((d[:-1] ** 2).sum())
        phi = 0.0 if den <= 1e-12 else float(np.clip((d[1:] * d[:-1]).sum() / den, 0.0, .99))
        return [float(exp(mu + phi ** h * d[-1])) for h in range(1, horizon + 1)]
    if rule == 'holt':
        a, b = .5, .3; level = obs[0]; trend = 0.0
        for v in obs[1:]:
            prev = level; level = a * v + (1 - a) * (level + trend); trend = b * (level - prev) + (1 - b) * trend
        return [max(0.0, level + h * trend) for h in range(1, horizon + 1)]
    raise ValueError(rule)


def forecast_trajectory(tr, k, end, rule):
    """Trajectory whose epochs k+1..end carry forecasts; epoch k and earlier are observed.

    'oracle' returns the true trajectory (the window sees realized future
    demand). Other rules forecast each named demand and resource path from its
    own observed history only. Costs, availability and leads are unchanged.
    """
    if rule == 'oracle' or end <= k:
        return tr
    h = end - k
    def sub(paths):
        out = {}
        for name, values in paths.items():
            values = list(values); fc = _forecast_series(values[:k + 1], h, rule)
            values[k + 1:end + 1] = fc; out[name] = values
        return out
    kw = {'demand_scale': sub(tr.demand_scale)}
    if tr.resource_scale:
        # Resource availability is forecast by persistence and never above the
        # declared maximum (scale <= 1), which the flow audit enforces.
        rs = {}
        for name, values in tr.resource_scale.items():
            values = list(values); values[k + 1:end + 1] = [values[k]] * h; rs[name] = values
        kw['resource_scale'] = rs
    return replace(tr, **kw)


# --------------------------------------------------------------------------
# World transformations (applied before initial assets are solved)

def bin_profile(bins, amplitude):
    if bins == 1:
        return [1.0]
    return [1.0 + amplitude * np.sin(2 * np.pi * (t + .5) / bins) for t in range(bins)]


def apply_bins(sc, bins, amplitude):
    """Two clocks: `bins` operating sub-periods per decision epoch.

    Hours per bin are 1/bins, so per-epoch quantities and cost weights are
    unchanged. Demand follows a known, mean-preserving within-epoch profile;
    raw supply is flat. Stocks are chronological within the epoch, so storage
    can now resolve a within-epoch temporal mismatch.
    """
    if bins == 1:
        return sc
    prof = bin_profile(bins, amplitude); fs = sc.flow_system
    demands = tuple(replace(q, rates=tuple(q.rates[0] * p for p in prof)) for q in fs.demands)
    resources = tuple(replace(q, max_rates=(q.max_rates[0],) * bins) for q in fs.resources)
    return replace(sc, periods=bins, hours=1.0 / bins, demand_D=[0.0] * bins,
                   flow_system=replace(fs, demands=demands, resources=resources))


def apply_lumps(sc, share, reference_capacity, include=lambda name, d: d.kind == 'process'):
    """Economies of scale: at the reference capacity total capital is unchanged;
    below it unit cost is higher, above it lower. Implemented with the core's
    existing lump binary (fixed_cost), charged over the asset life."""
    if share <= 0:
        return sc
    ds = {}
    for n, d in sc.designs.items():
        if include(n, d) and d.annual_cost > 0:
            ds[n] = replace(d, annual_cost=d.annual_cost * (1 - share),
                            fixed_cost=d.fixed_cost + d.annual_cost * share * reference_capacity)
        else:
            ds[n] = d
    return replace(sc, designs=ds)


def add_corridors(sc, lives, share):
    """Shared transport infrastructure.

    For every spatial edge direction a corridor design carries `share` of the
    mean per-form transport capital; per-form transport keeps the rest as
    handling equipment. All forms moving on the edge share the corridor's
    capacity in every bin. A single-form flow costs the same as in v3; shared
    use saves capital only where flows of different forms net on one corridor,
    and, with lumps enabled, through economies of density. Returns scenario, lives, roles and the member map.
    """
    from .catalog import Design
    ds = dict(sc.designs); lives = dict(lives); members = {}
    for n, d in sc.designs.items():
        if not (d.kind == 'process' and n.startswith('T_') and n.count('_') == 3):
            continue
        _, form, a, b = n.split('_')
        members.setdefault(f'C_{a}_{b}', []).append(n)
    for c, ms in sorted(members.items()):
        mean = sum(sc.designs[m].annual_cost for m in ms) / len(ms)
        cap = max(sc.designs[m].max_cap for m in ms)
        ds[c] = Design(c, 'corridor', annual_cost=mean * share, activity_unit='tonne/h', max_cap=cap * 3)
        lives[c] = 2 * max(lives[m] for m in ms)
        for m in ms:
            ds[m] = replace(ds[m], annual_cost=ds[m].annual_cost * (1 - share))
    return replace(sc, designs=ds), lives, members
