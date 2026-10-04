"""Capability and support determine practical realizability of stored knowledge."""
from dataclasses import dataclass, field, asdict
from math import isfinite
from typing import Mapping

@dataclass(frozen=True)
class Capability:
    acquire_cost: float = 0.0
    acquire_lead: int = 0
    validity: int | None = None
    description: str = ''
    def validate(self):
        if not isfinite(self.acquire_cost) or self.acquire_cost < 0: raise ValueError('Invalid capability acquisition cost')
        if not isinstance(self.acquire_lead,int) or self.acquire_lead<0: raise ValueError('Invalid capability acquisition lead')
        if self.validity is not None and (not isinstance(self.validity,int) or self.validity<1): raise ValueError('Invalid capability validity')
        return self

@dataclass(frozen=True)
class DesignRequirement:
    build: tuple[str,...]=()
    operate: tuple[str,...]=()
    maintain: tuple[str,...]=()

@dataclass(frozen=True)
class SupportWindow:
    build_until: int|None=None
    operate_until: int|None=None
    maintain_until: int|None=None
    def permits(self,stage,epoch):
        x=getattr(self,stage+'_until'); return x is None or epoch<=x

@dataclass(frozen=True)
class CapabilityGrant:
    capability:str; acquired:int; ready_from:int; ready_until:int|None
    def ready(self,k): return self.ready_from<=k and (self.ready_until is None or k<=self.ready_until)

@dataclass(frozen=True)
class RealizabilitySpec:
    capabilities: Mapping[str,Capability]
    requirements: Mapping[str,DesignRequirement]=field(default_factory=dict)
    initially_ready: tuple[str,...]=()
    initial_ready_until: Mapping[str,int|None]=field(default_factory=dict)
    support: Mapping[str,SupportWindow]=field(default_factory=dict)
    def validate(self,sc):
        if set(self.initially_ready)-set(self.capabilities): raise ValueError('Unknown initially ready capability')
        if set(self.initial_ready_until)-set(self.initially_ready): raise ValueError('initial_ready_until requires initially_ready')
        if set(self.requirements)-set(sc.designs) or set(self.support)-set(sc.designs): raise ValueError('Unknown design in realizability spec')
        for c in self.capabilities.values(): c.validate()
        for n,r in self.requirements.items():
            if (set(r.build)|set(r.operate)|set(r.maintain))-set(self.capabilities): raise ValueError(f'Unknown capability required by {n}')
        return self
    def manifest(self): return asdict(self)

def _active(cap,j,k):
    a=j+cap.acquire_lead; b=None if cap.validity is None else a+cap.validity-1
    return a<=k and (b is None or k<=b)

def add_realizability_constraints(prob,sc,traj,epochs,build,raw_alive,spec,grants,shared,tag=''):
    from .backend import lp
    spec.validate(sc); epochs=list(epochs); grants=list(grants or ()); acquire={}
    for ci,c in enumerate(sorted(spec.capabilities)):
        cap=spec.capabilities[c]
        for k in epochs:
            if k==epochs[0] and ('cap_acquire',c) in shared:q=shared[('cap_acquire',c)]
            else:
                q=lp.LpVariable(f'capacq{tag}_{ci}_{k}',cat='Binary')
                if k==epochs[0]:shared[('cap_acquire',c)]=q
            acquire[c,k]=q
        for k in epochs:
            active=[q for (cc,j),q in acquire.items() if cc==c and _active(cap,j,k)]
            inherited=sum(g.ready(k) for g in grants if g.capability==c)
            initial=int(c in spec.initially_ready and (spec.initial_ready_until.get(c) is None or k<=spec.initial_ready_until[c]))
            if active and inherited+initial:prob+=lp.lpSum(active)<=0
            elif len(active)>1:prob+=lp.lpSum(active)<=1
    def ready(c,k):
        cap=spec.capabilities[c]
        terms=[q for (cc,j),q in acquire.items() if cc==c and _active(cap,j,k)]
        const=sum(g.ready(k) for g in grants if g.capability==c)
        const+=int(c in spec.initially_ready and (spec.initial_ready_until.get(c) is None or k<=spec.initial_ready_until[c]))
        return const+lp.lpSum(terms)
    for (n,k),x in build.items():
        req=spec.requirements.get(n,DesignRequirement()); sup=spec.support.get(n,SupportWindow())
        if not sup.permits('build',k):prob+=x==0
        for c in req.build:prob+=x<=sc.designs[n].max_cap*ready(c,k)
    usable={}
    for (n,k),terms in raw_alive.items():
        raw=lp.lpSum(terms); req=spec.requirements.get(n,DesignRequirement());sup=spec.support.get(n,SupportWindow());M=sc.designs[n].max_cap
        if not sup.permits('maintain',k):prob+=raw==0
        for c in req.maintain:prob+=raw<=M*ready(c,k)
        u=lp.LpVariable(f'usable{tag}_{n}_{k}',0,M);prob+=u<=raw
        if not sup.permits('operate',k):prob+=u==0
        else:
            blockers=[]
            for c in req.operate:
                prob+=u<=M*ready(c,k);blockers.append(1-ready(c,k))
            prob+=u>=raw-M*lp.lpSum(blockers) if blockers else u==raw
        usable[n,k]=u
    return {'spec':spec,'acquire':acquire,'ready':ready,'usable':usable,'grants':grants,'designs':tuple(sc.designs)}

def extract_realizability(h,k,V):
    spec=h['spec']; acq=[]
    for (c,j),q in h['acquire'].items():
        if j==k and V(q)>0.5:
            cap=spec.capabilities[c];a=j+cap.acquire_lead
            acq.append({'capability':c,'acquired':j,'ready_from':a,'ready_until':None if cap.validity is None else a+cap.validity-1,'cost':cap.acquire_cost})
    ready=[]
    for c in spec.capabilities:
        if V(h['ready'](c,k))>0.5:ready.append(c)
    rset=set(ready); stages={}
    designs=set(h.get('designs',()))
    for stage in ('build','operate','maintain'):
        ok=[]
        for n in sorted(designs):
            req=spec.requirements.get(n,DesignRequirement());sup=spec.support.get(n,SupportWindow())
            if sup.permits(stage,k) and set(getattr(req,stage))<=rset:ok.append(n)
        stages[stage+'_realizable']=ok
    return {'acquired':acq,'ready':sorted(ready),'reconstitution_cost':sum(x['cost'] for x in acq),**stages}
