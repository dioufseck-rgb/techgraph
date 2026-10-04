"""Orthogonal service-demand geometry experiments.

Demand is an exogenous service requirement. The generator controls four target
properties separately: aggregate scale, spatial concentration, placement of the
concentration relative to an advantaged incumbent supply site, and service
composition. Technology adoption, flows, investment and topology remain outputs.
"""
from __future__ import annotations
from dataclasses import replace
import math
from .measurement.demand import gini
from .evolving_networks import make_evolving_network_world



def geometry_anchors(world):
    locs=list(world.scenario.locations);traits=world.metadata['traits'];coords=world.scenario.coords
    # Incumbent feed-to-intermediate variable-cost proxy. This is a declared
    # experimental reference point, not a claim that resources exist only here.
    score={l:traits[l]['resource_price']/traits[l]['old_yield'] for l in locs}
    advantaged=min(locs,key=lambda l:(score[l],l))
    ax,ay=coords[advantaged]
    away=max(locs,key=lambda l:((coords[l][0]-ax)**2+(coords[l][1]-ay)**2,l))
    return advantaged,away,score


def _shares(n,alpha,target):
    if not 0<=alpha<1:raise ValueError('concentration alpha must be in [0,1)')
    base=(1-alpha)/n
    return [base+(alpha if i==target else 0.) for i in range(n)]


def make_demand_geometry_world(n_sites=6,seed=0,connectivity='rich',*,K=24,
                               scale=1.,concentration=0.,placement='toward',
                               primary_share=.8,transition_start=4,transition_end=8,
                               alternatives='rich'):
    if scale<=0:raise ValueError('scale must be positive')
    if not 0<primary_share<1:raise ValueError('primary_share must lie in (0,1)')
    if placement not in {'toward','away'}:raise ValueError('placement must be toward or away')
    if not 0<=transition_start<=transition_end<K:raise ValueError('bad transition interval')
    w=make_evolving_network_world(n_sites,seed,connectivity,K=K,demand_mode='fixed',optional=False,alternatives=alternatives)
    locs=list(w.scenario.locations);adv,far,score=geometry_anchors(w);target=locs.index(adv if placement=='toward' else far)
    shares=_shares(len(locs),concentration,target)
    qmap={q.name:sum(q.rates)*w.scenario.hours for q in w.scenario.flow_system.demands}
    primary=[n for n in qmap if n.startswith('product_')];secondary=[n for n in qmap if n.startswith('secondary_')]
    initial_total=sum(qmap.values());target_total=initial_total*scale
    target_totals={'primary':target_total*primary_share,'secondary':target_total*(1-primary_share)}
    target_q={}
    for names,kind in [(primary,'primary'),(secondary,'secondary')]:
        for i,l in enumerate(locs):
            target_q[(kind,l)]=target_totals[kind]*shares[i]
    paths={}
    for q in w.scenario.flow_system.demands:
        kind='primary' if q.name.startswith('product_') else 'secondary';l=q.name.split('_',1)[1]
        base=qmap[q.name];target_amount=target_q[(kind,l)]
        if base<=0:raise ValueError('positive base demand required')
        target_mult=target_amount/base
        vals=[]
        for k in range(K):
            if k<=transition_start:f=0.
            elif k>=transition_end:f=1.
            else:f=(k-transition_start)/(transition_end-transition_start)
            vals.append((1-f)+f*target_mult)
        paths[q.name]=vals
    tr=replace(w.trajectory,demand_scale=paths)
    coords=w.scenario.coords;ax,ay=coords[adv]
    def spatial_state(k):
        vals=[]
        for l in locs:
            p=next(q for q in w.scenario.flow_system.demands if q.name=='product_'+l)
            s=next(q for q in w.scenario.flow_system.demands if q.name=='secondary_'+l)
            vals.append(qmap[p.name]*paths[p.name][k]+qmap[s.name]*paths[s.name][k])
        total=sum(vals);cx=sum(v*coords[l][0] for v,l in zip(vals,locs))/total;cy=sum(v*coords[l][1] for v,l in zip(vals,locs))/total
        sep=sum(v*math.dist(coords[l],(ax,ay)) for v,l in zip(vals,locs))/total
        return {'total':total,'gini':gini(vals),'centroid':[cx,cy],'centroid_from_advantaged':math.dist((cx,cy),(ax,ay)),
                'demand_weighted_distance_from_advantaged':sep}
    meta={**w.metadata,'demand_geometry':{'role':'exogenous service-demand input','scale':scale,'concentration_alpha':concentration,
          'placement':placement,'primary_share':primary_share,'transition_start':transition_start,'transition_end':transition_end,
          'advantaged_supply_site':adv,'away_site':far,'incumbent_supply_score':score,
          'initial_state':spatial_state(0),'target_state':spatial_state(K-1),
          'adoption_is_output':True}}
    return replace(w,trajectory=tr,metadata=meta)
