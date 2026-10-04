"""Exogenous service-demand trajectories for sensitivity experiments.

Demand paths are inputs. Technology adoption, installed capacity, flows, topology,
and realized optional service are outputs. These archetypes are normalized
experimental forcing functions, not adoption curves and not calibrated forecasts.
"""
from __future__ import annotations
from dataclasses import replace
import math
from .evolving_networks import make_evolving_network_world

ARCHETYPES=(
    'flat','compound_growth','saturating_growth','decline','structural_break',
    'regional_shift','correlated_growth','sinusoidal_stress'
)


def _normalize(v):
    if not v or v[0] <= 0: raise ValueError('Positive starting demand required')
    b=float(v[0]);return [float(x/b) for x in v]


def common_path(kind,K):
    if K<2: return [1.0]
    x=[k/(K-1) for k in range(K)]
    if kind=='flat': return [1.0]*K
    if kind=='compound_growth':
        # 1.2% per epoch, within the current AEO 2026 U.S. electricity-demand
        # projection range if an epoch is interpreted as approximately one year.
        return [1.012**k for k in range(K)]
    if kind=='saturating_growth':
        # Mature service: smooth growth toward a 35% higher plateau.
        return _normalize([1.0+.35*(1-math.exp(-4*z)) for z in x])
    if kind=='decline': return [1.0-.25*z for z in x]
    if kind=='structural_break': return [1.0 if k < K//2 else 1.30 for k in range(K)]
    raise ValueError(kind)


def named_paths(world,kind,K):
    """Return required-service multipliers; aggregate service is an input."""
    names=[q.name for q in world.scenario.flow_system.demands]
    if kind in {'flat','compound_growth','saturating_growth','decline','structural_break'}:
        base=common_path(kind,K);return {n:list(base) for n in names}
    if kind=='sinusoidal_stress':
        # Historical stress generator retained as a null/sensitivity case.
        old=make_evolving_network_world(len(world.scenario.locations),world.metadata['seed'],
            world.metadata['connectivity'],K=K,demand_mode='moving',optional=False,
            alternatives=world.metadata['alternatives'])
        return {n:_normalize(list(old.trajectory.demand_scale[n])) for n in names}
    locs=list(world.scenario.locations)
    paths={}
    if kind=='correlated_growth':
        # Shared macro trend plus persistent regional/service growth heterogeneity;
        # no independent phase oscillations.
        for n in names:
            loc=n.split('_',1)[1]
            i=locs.index(loc);secondary=n.startswith('secondary_')
            g=.010 + .002*((i%3)-1) + (-.002 if secondary else .001)
            paths[n]=[(1+g)**k for k in range(K)]
        return paths
    if kind=='regional_shift':
        # Same aggregate required quantity at each epoch, but service moves
        # progressively from the first half of sites to the second half.
        half=max(1,len(locs)//2)
        for n in names:
            loc=n.split('_',1)[1];i=locs.index(loc)
            sign=-1 if i<half else 1
            amp=.30 if not n.startswith('secondary_') else .20
            raw=[1.0+sign*amp*(k/(K-1)) for k in range(K)]
            paths[n]=raw
        # Normalize each service class at every epoch so weighted aggregate
        # demand equals its epoch-0 total. Base site quantities differ, so use
        # actual reference-block demand as weights.
        qmap={q.name:sum(q.rates) for q in world.scenario.flow_system.demands}
        for secondary in (False,True):
            subset=[n for n in names if n.startswith('secondary_')==secondary]
            target=sum(qmap[n]*paths[n][0] for n in subset)
            for k in range(K):
                total=sum(qmap[n]*paths[n][k] for n in subset)
                factor=target/total
                for n in subset:paths[n][k]*=factor
        return paths
    raise ValueError(kind)


def make_demand_archetype_world(n_sites=6,seed=0,connectivity='rich',*,K=24,
                                archetype='flat',alternatives='rich'):
    if archetype not in ARCHETYPES:raise ValueError('Unknown demand archetype')
    # Start from the fixed-demand long world so optional uptake is absent and
    # required service is the only changing forcing in this experiment.
    w=make_evolving_network_world(n_sites,seed,connectivity,K=K,demand_mode='fixed',
                                  optional=False,alternatives=alternatives)
    paths=named_paths(w,archetype,K)
    tr=replace(w.trajectory,demand_scale=paths)
    meta={**w.metadata,'demand_experiment':{
        'archetype':archetype,'role':'exogenous required-service input',
        'adoption_is_output':True,
        'scope':'normalized archetype; not a technology-adoption curve or calibrated forecast'}}
    return replace(w,trajectory=tr,metadata=meta)
