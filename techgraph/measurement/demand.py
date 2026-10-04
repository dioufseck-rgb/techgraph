"""Demand-forcing measurements. Demand is input; adoption is not inferred here."""
from __future__ import annotations
import math


def gini(values):
    """Non-negative Gini coefficient. Scale invariant; contains no location information."""
    x=[max(0.,float(v)) for v in values]
    if not x or sum(x)<=0:return 0.
    n=len(x);sx=sorted(x)
    return sum((2*i-n-1)*v for i,v in enumerate(sx,1))/(n*sum(sx))


def _amount(sc,tr,q,k):
    return float(sum(q.rates)*sc.hours*tr.demand(q.name,k))


def demand_state(sc,tr,k,*,resource_sites=()):
    """Describe exogenous required-service forcing at decision epoch k.

    Returns aggregate scale, site totals, spatial Gini, centroid, dispersion,
    optional separation from a declared resource-site set, and form composition.
    This function does not inspect installed technology or operation.
    """
    fs=sc.flow_system
    if fs is None:
        raise ValueError('Demand-state metrics require an explicit FlowSystem')
    by_site={l:0. for l in sc.locations};by_form={}
    for q in fs.demands:
        v=_amount(sc,tr,q,k);by_site[q.location]+=v;by_form[q.form]=by_form.get(q.form,0.)+v
    total=sum(by_site.values())
    coords=getattr(sc,'coords',{}) or {}
    centroid=None;dispersion=None;separation=None
    if total>0 and all(l in coords for l in sc.locations):
        dim=len(coords[sc.locations[0]])
        centroid=tuple(sum(by_site[l]*coords[l][j] for l in sc.locations)/total for j in range(dim))
        dispersion=sum(by_site[l]*math.dist(coords[l],centroid) for l in sc.locations)/total
        rs=tuple(resource_sites)
        if rs:
            if any(l not in coords for l in rs):raise ValueError('Unknown resource site in demand metric')
            separation=sum(by_site[l]*min(math.dist(coords[l],coords[r]) for r in rs) for l in sc.locations)/total
    composition={f:(v/total if total else 0.) for f,v in by_form.items()}
    return {'epoch':k,'total':total,'by_site':by_site,'gini':gini(by_site.values()),
            'centroid':centroid,'dispersion':dispersion,'resource_separation':separation,
            'composition':composition}


def demand_series(sc,tr,*,resource_sites=()):
    return [demand_state(sc,tr,k,resource_sites=resource_sites) for k in range(tr.K)]
