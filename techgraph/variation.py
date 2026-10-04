"""Bounded variation operators, independent of economic selection.

Generated recipes/costs are synthetic. Feasibility envelopes are supplied by the
experiment; no chemistry or new physical form is inferred by this module.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from math import exp, isfinite
import random
from typing import Mapping
from .catalog import Design
from .flows import Port, validate_flow_system


def keyed_rng(seed: int, *keys) -> random.Random:
    raw=json.dumps([seed,*keys],sort_keys=True,separators=(',',':')).encode()
    return random.Random(int.from_bytes(sha256(raw).digest()[:16],'big'))


def fingerprint(design: Design) -> str:
    raw=asdict(design);raw.pop('name')
    for key in ['input_ports','output_ports']:
        raw[key]=sorted(raw[key],key=lambda p:(p['form'],p['location'],p['coefficient']))
    return sha256(json.dumps(raw,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class MutationRule:
    family: str
    seed_design: str
    cost_log_sigma: float = .25
    cost_log_drift: float = 0.0
    cost_bounds: tuple[float,float] = (.25,3.0)  # relative to original seed, every generation
    variable_sigma: float = .15
    vary_fixed: bool = True
    output_pair: tuple[int,int] | None = None
    yield_sigma: float = .04
    yield_bounds: tuple[float,float] = (.05,.99)
    lifetime: int | None = None

    def validate(self,sc):
        if not self.family or self.seed_design not in sc.designs:raise ValueError('Unknown mutation seed/family')
        vals=[self.cost_log_sigma,self.variable_sigma,self.yield_sigma]
        if any(not isfinite(x) or x<0 for x in vals) or not isfinite(self.cost_log_drift):raise ValueError('Invalid variation scale')
        if len(self.cost_bounds)!=2 or any(not isfinite(v) for v in self.cost_bounds) or not 0<self.cost_bounds[0]<=self.cost_bounds[1]:raise ValueError('Invalid cost envelope')
        if self.lifetime is not None and (not isinstance(self.lifetime,int) or self.lifetime<1):raise ValueError('Invalid lifetime')
        d=sc.designs[self.seed_design]
        if self.output_pair is not None:
            i,j=self.output_pair
            if d.kind!='process' or i==j or min(i,j)<0 or max(i,j)>=len(d.output_ports):raise ValueError('Output pair must identify two process outputs')
            fs=sc.flow_system
            if fs is None or fs.form_units[d.output_ports[i].form]!=fs.form_units[d.output_ports[j].form]:raise ValueError('Conserved output pair must have the same quantity unit')
            if any(not isfinite(v) for v in self.yield_bounds) or not 0<self.yield_bounds[0]<=self.yield_bounds[1]:raise ValueError('Invalid yield envelope')
        return self


@dataclass(frozen=True)
class RecombinationRule:
    family: str
    upstream_family: str
    downstream_family: str
    form: str
    location: str
    cost_factor_bounds: tuple[float,float] = (.85,1.15)

    def validate(self):
        lo,hi=self.cost_factor_bounds
        if not self.family or not self.form or not self.location or not (isfinite(lo) and isfinite(hi) and 0<lo<=hi):raise ValueError('Invalid composition rule')
        return self


@dataclass(frozen=True)
class Candidate:
    design: Design
    family: str
    parents: tuple[str,...]
    operator: str
    epoch: int
    slot: int
    life: int
    metadata: Mapping

    def manifest(self):return asdict(self)


def validate_candidate(sc,candidate):
    d=candidate.design
    if not d.name or d.name in sc.designs:raise ValueError('Candidate name collides with existing design')
    if not candidate.parents or not candidate.family or candidate.life<1 or candidate.epoch<0 or candidate.slot<0:raise ValueError('Invalid candidate provenance')
    if any(p not in sc.designs for p in candidate.parents):raise ValueError('Unknown parent')
    for f in ['annual_cost','fixed_cost','var_cost','max_cap']:
        v=getattr(d,f)
        if not isfinite(v) or v<0 or (f=='max_cap' and v<=0):raise ValueError('Invalid candidate cost/capacity')
    if d.kind=='convert' and not 0<d.eff<=1:raise ValueError('Invalid efficiency')
    if d.kind=='transport' and not 0<=d.loss<1:raise ValueError('Invalid loss')
    if d.kind=='store' and not (0<d.eta_c<=1 and 0<d.eta_d<=1 and d.duration_h>0):raise ValueError('Invalid storage performance')
    validate_flow_system(replace(sc,designs={**sc.designs,d.name:d}))
    return True


def mutate(sc, parent, rule, *, seed, epoch, slot, life, name=None):
    """Return a proposed variant or raise for an envelope violation.

    Failure is retained in the proposal record by the VSR runner. Sampling is not
    repeated until success; invalid draws consume the declared search budget.
    """
    rule.validate(sc)
    d=sc.designs[parent];base=sc.designs[rule.seed_design]
    rng=keyed_rng(seed,'mutation',epoch,slot)
    cap_factor=exp(rng.gauss(rule.cost_log_drift,rule.cost_log_sigma))
    var_factor=exp(rng.gauss(rule.cost_log_drift,rule.variable_sigma))
    kw={'name':name or f'V_{epoch:03}_{slot:03}', 'annual_cost':d.annual_cost*cap_factor,
        'fixed_cost':d.fixed_cost*(cap_factor if rule.vary_fixed else 1), 'var_cost':d.var_cost*var_factor}
    for field in ['annual_cost','fixed_cost','var_cost']:
        original=getattr(base,field);v=kw[field]
        if original==0:
            if v!=0:raise ValueError('Mutation cannot create an unbounded price from zero seed')
        elif not rule.cost_bounds[0]-1e-12<=v/original<=rule.cost_bounds[1]+1e-12:
            raise ValueError(f'{field} outside seed-family envelope')
    if rule.output_pair is not None:
        i,j=rule.output_pair
        if len(d.output_ports)!=len(base.output_ports):raise ValueError('Parent recipe not in declared family')
        ps=list(d.output_ports);total=ps[i].coefficient+ps[j].coefficient
        y=ps[i].coefficient+rng.gauss(0,rule.yield_sigma)
        if not rule.yield_bounds[0]<=y<=rule.yield_bounds[1] or total-y<=0:raise ValueError('Yield outside feasibility envelope')
        ps[i]=replace(ps[i],coefficient=y);ps[j]=replace(ps[j],coefficient=total-y)
        kw['output_ports']=tuple(ps)
    c=Candidate(replace(d,**kw),rule.family,(parent,),'mutation',epoch,slot,rule.lifetime or life,
                {'seed_design':rule.seed_design,'capacity_price_factor':cap_factor,'activity_price_factor':var_factor})
    validate_candidate(sc,c);return c


def _merge_ports(ports):
    amounts={}
    for p in ports:amounts[p.form,p.location]=amounts.get((p.form,p.location),0)+p.coefficient
    return tuple(Port(f,l,c) for (f,l),c in sorted(amounts.items()) if c>1e-12)


def recombine(sc, upstream, downstream, rule, *, seed, epoch, slot, lives, name=None):
    """Compose a declared serial interface without deleting any external residual.

    The second process is scaled to consume all of the first process's matched
    output. No second matched input or feedback into that internal state is allowed.
    """
    rule.validate();a,b=sc.designs[upstream],sc.designs[downstream]
    if upstream==downstream or a.kind!='process' or b.kind!='process':raise ValueError('Composition requires two distinct processes')
    if a.activity_unit!=b.activity_unit:raise ValueError('Composition requires common activity units')
    key=(rule.form,rule.location)
    first=[p for p in a.output_ports if (p.form,p.location)==key]
    second=[p for p in b.input_ports if (p.form,p.location)==key]
    if len(first)!=1 or len(second)!=1:raise ValueError('Serial interface must occur once on each side')
    if any((p.form,p.location)==key for p in a.input_ports+b.output_ports):raise ValueError('Feedback through the internal state is not supported')
    ratio=first[0].coefficient/second[0].coefficient
    inputs=list(a.input_ports)+[replace(p,coefficient=p.coefficient*ratio) for p in b.input_ports if (p.form,p.location)!=key]
    outputs=[p for p in a.output_ports if (p.form,p.location)!=key]+[replace(p,coefficient=p.coefficient*ratio) for p in b.output_ports]
    factor=keyed_rng(seed,'recombine',epoch,slot).uniform(*rule.cost_factor_bounds)
    d=Design(name or f'V_{epoch:03}_{slot:03}','process',factor*(a.annual_cost+ratio*b.annual_cost),
             fixed_cost=factor*(a.fixed_cost+b.fixed_cost),var_cost=factor*(a.var_cost+ratio*b.var_cost),
             input_ports=_merge_ports(inputs),output_ports=_merge_ports(outputs),activity_unit=a.activity_unit,
             max_cap=min(a.max_cap,b.max_cap/ratio),conserve_mass=a.conserve_mass and b.conserve_mass,
             conserve_energy=a.conserve_energy and b.conserve_energy)
    c=Candidate(d,rule.family,(upstream,downstream),'serial_composition',epoch,slot,min(lives[upstream],lives[downstream]),
                {'interface':[rule.form,rule.location],'downstream_activity_per_upstream':ratio,
                 'declared_cost_factor':factor,'fixed_ratio_operation':True})
    validate_candidate(sc,c);return c
