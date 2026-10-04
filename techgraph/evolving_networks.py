"""Long-horizon evolving-demand variants of generated network worlds.

This layer changes the problem through time without changing the persistent-
knowledge contract. Demand paths are supplied experimental inputs, not inferred
preferences. Optional uptake remains endogenous conditional on supplied values.
"""
from __future__ import annotations
from dataclasses import replace
import math
from .network_worlds import make_network_world
from .needs import NeedSystem, OptionalNeed, ServiceProfile


def _smooth_path(K, phase, growth, amplitude):
    vals=[]
    for k in range(K):
        x=1.0+growth*k+amplitude*math.sin(2*math.pi*k/max(K,1)+phase)
        vals.append(max(.55,x))
    return vals


def make_evolving_network_world(n_sites=6, seed=0, connectivity='rich', *, K=24,
                                demand_mode='fixed', optional=False,
                                adjustment_rate=None, alternatives='rich'):
    if demand_mode not in {'fixed','moving'}: raise ValueError('Unknown demand mode')
    w=make_network_world(n_sites,seed,connectivity,K=K,alternatives=alternatives)
    fs=w.scenario.flow_system
    demands=[];named={}
    for i,q in enumerate(fs.demands):
        # Turn on named trajectory scaling while retaining the original within-block profile.
        demands.append(replace(q,scale_with_demand=True))
        if demand_mode=='fixed':
            named[q.name]=[1.0]*K
        else:
            # Primary and coproduct services move differently and districts have different phases.
            is_secondary=q.name.startswith('secondary_')
            phase=(i//2)*.63 + (1.4 if is_secondary else 0.)
            growth=.004 if is_secondary else .010
            amplitude=.28 if is_secondary else .22
            named[q.name]=_smooth_path(K,phase,growth,amplitude)
    sc=replace(w.scenario,flow_system=replace(fs,demands=tuple(demands)))
    need_system=None
    if optional:
        needs=[]
        for i,l in enumerate(sc.locations):
            base=w.metadata['traits'][l]['primary_rate']
            # Two bounded segments: an early moderate-value service and a later larger one.
            # Values vary by district but are constant through time; uptake changes with supply conditions.
            rates1=tuple(.10*base for _ in range(sc.periods))
            rates2=tuple(.16*base for _ in range(sc.periods))
            req='grade_'+l
            needs.extend([
                OptionalNeed(f'optional_early_{l}',(ServiceProfile('product',l,rates1,req),),
                             value=5.0+.35*(i%4),recognized_from=4,mode='divisible',
                             description='bounded discretionary product service'),
                OptionalNeed(f'optional_late_{l}',(ServiceProfile('product',l,rates2,req),),
                             value=7.0+.45*((i+1)%5),recognized_from=10,mode='divisible',
                             description='later bounded discretionary product service'),
            ])
        need_system=NeedSystem(tuple(needs))
        sc=replace(sc,need_system=need_system)
    tr=replace(w.trajectory,K=K,fuel_price=[w.trajectory.fuel_price[0]]*K,demand_mult=[1.0]*K,
               demand_scale=named)
    if adjustment_rate is not None:
        if adjustment_rate<=0: raise ValueError('Adjustment rate must be positive')
        tr=replace(tr,build_rate={n:[float(adjustment_rate)]*K for n in sc.designs})
    meta={**w.metadata,'long_horizon':{'K':K,'demand_mode':demand_mode,'optional':optional,
          'adjustment_rate':adjustment_rate,
          'scope':'supplied evolving demand; optional uptake conditional on fixed values; build-rate limit is not a commissioning lag'}}
    return replace(w,scenario=sc,trajectory=tr,metadata=meta)
