"""Finite supply variants and explicit, time-varying service-acceptance rules.

Variant allocation consumes real forms in the existing physical balances. This is
not a provenance inference engine, a generic quality-mixing model, or a new utility
function. All properties and meaningful averaging permissions are declared inputs.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from math import isfinite
from numbers import Real
from typing import Mapping


@dataclass(frozen=True)
class AttributeDefinition:
    kind: str                         # numeric or categorical
    unit: str | None = None            # explicit for numeric, absent for categorical
    allow_average: bool = False


@dataclass(frozen=True)
class FormVariant:
    family: str                       # registered base service family
    numeric: Mapping[str, float] = field(default_factory=dict)
    categorical: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NumericLimit:
    attribute: str
    lower: float | None = None
    upper: float | None = None
    aggregation: str = 'each'         # each candidate or delivered quantity-weighted average


@dataclass(frozen=True)
class RequirementStage:
    from_epoch: int = 0
    numeric: tuple[NumericLimit, ...] = ()
    categories: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceRequirement:
    family: str
    candidates: tuple[str, ...]
    stages: tuple[RequirementStage, ...] = (RequirementStage(),)

    def stage_at(self, epoch: int) -> RequirementStage:
        return next(s for s in reversed(self.stages) if s.from_epoch <= epoch)


@dataclass(frozen=True)
class AttributeSystem:
    definitions: Mapping[str, AttributeDefinition] = field(default_factory=dict)
    variants: Mapping[str, FormVariant] = field(default_factory=dict)
    requirements: Mapping[str, ServiceRequirement] = field(default_factory=dict)

    def manifest(self):
        return {**asdict(self), 'scope':'finite physical variants; deterministic staged service rules; no inferred provenance'}

    @classmethod
    def from_manifest(cls, m):
        return cls(
            {n: AttributeDefinition(**d) for n,d in m['definitions'].items()},
            {n: FormVariant(**d) for n,d in m['variants'].items()},
            {n: ServiceRequirement(d['family'],tuple(d['candidates']),tuple(
                RequirementStage(s['from_epoch'],tuple(NumericLimit(**b) for b in s.get('numeric',())),
                                 {a:tuple(v) for a,v in s.get('categories',{}).items()}) for s in d['stages']))
             for n,d in m['requirements'].items()})


def _references(sc):
    fs=getattr(sc,'flow_system',None)
    if fs is not None:
        for d in fs.demands:
            if getattr(d,'attribute_requirement',None) is not None:
                yield d.form,d.attribute_requirement
    ns=getattr(sc,'need_system',None)
    if ns is not None:
        for n in ns.needs:
            for p in n.profiles:
                if getattr(p,'attribute_requirement',None) is not None:
                    yield p.form,p.attribute_requirement


def enabled(sc):
    return any(True for _ in _references(sc))


def validate_attributes(sc, K=None, epoch=0, contingencies=None):
    """Reject silent fallback, incompatible forms and unjustified averaging."""
    refs=list(_references(sc)); a=getattr(sc,'attribute_system',None)
    if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<0:
        raise ValueError('Attribute epoch must be a nonnegative integer')
    if a is None:
        if refs: raise ValueError('Attribute service requires an AttributeSystem')
        return
    if not isinstance(a,AttributeSystem): raise TypeError('attribute_system must be AttributeSystem')
    if not refs and not a.definitions and not a.variants and not a.requirements:return
    if sc.flow_system is None: raise ValueError('Attribute variants require an explicit FlowSystem')
    fs=sc.flow_system
    for name,d in a.definitions.items():
        if not isinstance(name,str) or not name or not isinstance(d,AttributeDefinition):
            raise ValueError('Named attribute definitions required')
        if d.kind not in {'numeric','categorical'} or not isinstance(d.allow_average,bool):
            raise ValueError('Unknown attribute definition')
        if d.kind=='numeric':
            if not isinstance(d.unit,str) or not d.unit: raise ValueError('Numeric attributes require declared units')
        elif d.unit is not None or d.allow_average:
            raise ValueError('Categorical properties have no numeric units and cannot be averaged')
    for form,v in a.variants.items():
        if not isinstance(v,FormVariant): raise TypeError('Variants must be FormVariant')
        if form not in fs.form_units or v.family not in fs.form_units:
            raise ValueError('Variant and family must be registered forms')
        if fs.form_units[form]!=fs.form_units[v.family]:
            raise ValueError('A variant must share the family quantity unit')
        for name,value in v.numeric.items():
            if name not in a.definitions or a.definitions[name].kind!='numeric':
                raise ValueError('Unknown numeric attribute')
            if isinstance(value,bool) or not isinstance(value,Real) or not isfinite(value):
                raise ValueError('Numeric variant attributes must be finite numbers')
        for name,value in v.categorical.items():
            if name not in a.definitions or a.definitions[name].kind!='categorical':
                raise ValueError('Unknown categorical attribute')
            if not isinstance(value,str) or not value: raise ValueError('Categorical values must be nonempty strings')
    for name,r in a.requirements.items():
        if not isinstance(name,str) or not name or not isinstance(r,ServiceRequirement):
            raise ValueError('Named ServiceRequirement objects required')
        if r.family not in fs.form_units: raise ValueError('Unknown requirement family')
        if not r.candidates or len(set(r.candidates))!=len(r.candidates):
            raise ValueError('Nonempty distinct candidate variants required')
        if any(f not in a.variants or a.variants[f].family!=r.family for f in r.candidates):
            raise ValueError('Every candidate must be a variant of the required family')
        if not r.stages or any(not isinstance(s,RequirementStage) for s in r.stages):
            raise ValueError('Explicit requirement stages required')
        epochs=[s.from_epoch for s in r.stages]
        if any(not isinstance(k,int) or isinstance(k,bool) or k<0 for k in epochs) or epochs[0]!=0 or any(x>=y for x,y in zip(epochs,epochs[1:])):
            raise ValueError('Requirement stages must start at zero and increase strictly')
        for s in r.stages:
            if len({b.attribute for b in s.numeric})!=len(s.numeric):
                raise ValueError('Duplicate numeric rule in a stage')
            for b in s.numeric:
                if b.attribute not in a.definitions or a.definitions[b.attribute].kind!='numeric':
                    raise ValueError('Numeric bounds need a numeric definition')
                if b.aggregation not in {'each','average'}: raise ValueError('Unknown aggregation mode')
                if b.aggregation=='average' and not a.definitions[b.attribute].allow_average:
                    raise ValueError('Averaging this attribute is not declared meaningful')
                bounds=[v for v in (b.lower,b.upper) if v is not None]
                if not bounds or any(isinstance(v,bool) or not isinstance(v,Real) or not isfinite(v) for v in bounds):
                    raise ValueError('At least one finite numeric bound required')
                if b.lower is not None and b.upper is not None and b.lower>b.upper:
                    raise ValueError('Lower attribute bound exceeds upper bound')
            for key,allowed in s.categories.items():
                if key not in a.definitions or a.definitions[key].kind!='categorical':
                    raise ValueError('Categorical bounds need a categorical definition')
                if isinstance(allowed,str) or not allowed or any(not isinstance(v,str) or not v for v in allowed) or len(set(allowed))!=len(allowed):
                    raise ValueError('Categorical acceptance must be a nonempty set of strings')
    for family,name in refs:
        if name not in a.requirements or a.requirements[name].family!=family:
            raise ValueError('Service requirement must exist and match its requested family')


def admissibility(sc, requirement, epoch):
    """Per-variant qualification; a missing required field excludes the variant."""
    a=sc.attribute_system;r=a.requirements[requirement];s=r.stage_at(epoch)
    result={}
    for form in r.candidates:
        v=a.variants[form]; reasons=[]
        for key,allowed in s.categories.items():
            if key not in v.categorical: reasons.append('missing:'+key)
            elif v.categorical[key] not in allowed: reasons.append('category:'+key)
        for b in s.numeric:
            value=v.numeric.get(b.attribute)
            if value is None: reasons.append('missing:'+b.attribute)
            elif b.aggregation=='each' and ((b.lower is not None and value<b.lower) or (b.upper is not None and value>b.upper)):
                reasons.append('bound:'+b.attribute)
        result[form]=reasons
    return result


def add_attribute_delivery(prob, sc, balance, family, location, delivered_rates, requirement, *, epoch, tag):
    """Add typed physical allocations for exactly the specified delivered rates."""
    from .backend import lp
    r=sc.attribute_system.requirements[requirement];s=r.stage_at(epoch)
    rejected=admissibility(sc,requirement,epoch);xs={}
    for i,form in enumerate(r.candidates):
        xs[form]=[lp.LpVariable(f'attr_{tag}_{i}_{t}',0,0 if rejected[form] else None) for t in range(sc.periods)]
        for t in range(sc.periods): balance[form,location,t].append(-sc.hours*xs[form][t])
    for t,target in enumerate(delivered_rates):
        prob += lp.lpSum(xs[f][t] for f in r.candidates)==target, f'attr_sum_{tag}_{t}'
        for i,b in enumerate(s.numeric):
            if b.aggregation!='average':continue
            # Missing attributes are constrained to zero allocation; no invented
            # zero-valued eligible supply is introduced in the weighted expression.
            total=lp.lpSum(sc.attribute_system.variants[f].numeric[b.attribute]*xs[f][t]
                           for f in r.candidates if b.attribute in sc.attribute_system.variants[f].numeric)
            if b.lower is not None:prob += total >= b.lower*target,f'attr_lower_{tag}_{i}_{t}'
            if b.upper is not None:prob += total <= b.upper*target,f'attr_upper_{tag}_{i}_{t}'
    return {'requirement':requirement,'family':family,'location':location,'epoch':epoch,
            'stage_from':s.from_epoch,'allocations':xs}


def extract_attribute_delivery(sc, handle):
    from .backend import lp
    if handle is None:return None
    name,k=handle['requirement'],handle['epoch'];a=sc.attribute_system
    rates={f:[float(lp.value(x)) for x in xs] for f,xs in handle['allocations'].items()}
    totals=[sum(xs[t] for xs in rates.values()) for t in range(sc.periods)]
    stage=a.requirements[name].stage_at(k)
    averages={b.attribute:[None if q<=1e-10 else sum(a.variants[f].numeric.get(b.attribute,0)*xs[t] for f,xs in rates.items())/q
                           for t,q in enumerate(totals)] for b in stage.numeric if b.aggregation=='average'}
    return {'requirement':name,'family':handle['family'],'location':handle['location'],'epoch':k,
            'stage_from':stage.from_epoch,'quantity_unit':sc.flow_system.form_units[handle['family']],
            'allocations':rates,'quantities':{f:[sc.hours*x for x in xs] for f,xs in rates.items()},
            'rejected_candidates':admissibility(sc,name,k),'averages':averages}


def audit_attribute_delivery(sc, saved, *, family, location, requirement, delivered_rates, epoch=None, tolerance=1e-6):
    """Reconstruct compliance from allocated variants and declared input properties.

    Physical production/support for these allocations is independently checked by
    flow_audit; passing only this interface audit does not establish supply.
    """
    if requirement is None:
        if saved is not None:raise AssertionError('Unexpected attribute allocation')
        return {'passed':True,'max_absolute_error':0.,'physical_rates':{family:list(delivered_rates)}}
    if not isinstance(saved,dict):raise AssertionError('Missing attribute delivery record')
    k=saved.get('epoch') if epoch is None else epoch
    if not isinstance(k,int) or isinstance(k,bool) or k<0:raise AssertionError('Invalid attribute epoch')
    if (saved.get('requirement'),saved.get('family'),saved.get('location'),saved.get('epoch'))!=(requirement,family,location,k):
        raise AssertionError('Attribute service identity/epoch changed')
    r=sc.attribute_system.requirements[requirement];s=r.stage_at(k)
    if r.family!=family or saved.get('stage_from')!=s.from_epoch or saved.get('quantity_unit')!=sc.flow_system.form_units[family]:
        raise AssertionError('Attribute stage/family/unit changed')
    if len(delivered_rates)!=sc.periods or set(saved.get('allocations',{}))!=set(r.candidates) or set(saved.get('quantities',{}))!=set(r.candidates):
        raise AssertionError('Missing or extra variant allocation')
    rejected=admissibility(sc,requirement,k)
    if saved.get('rejected_candidates')!=rejected:raise AssertionError('Candidate eligibility was altered')
    err=0.
    def equal(a,b,msg):
        nonlocal err
        if not isfinite(float(a)) or not isfinite(float(b)):raise AssertionError('Nonfinite '+msg)
        err=max(err,abs(a-b))
        if abs(a-b)>tolerance:raise AssertionError(msg)
    for form,xs in saved['allocations'].items():
        qs=saved['quantities'][form]
        if len(xs)!=sc.periods or len(qs)!=sc.periods:raise AssertionError('Incomplete attribute allocation')
        for x,q in zip(xs,qs):
            if not isinstance(x,Real) or not isfinite(x) or x < -tolerance:raise AssertionError('Invalid variant quantity')
            if rejected[form] and x>tolerance:raise AssertionError('Ineligible variant delivered')
            equal(q,sc.hours*x,'Variant quantity mismatch')
    avkeys={b.attribute for b in s.numeric if b.aggregation=='average'}
    if set(saved.get('averages',{}))!=avkeys:raise AssertionError('Average attribute records changed')
    for t,q in enumerate(delivered_rates):
        if not isfinite(q) or q < -tolerance:raise AssertionError('Invalid service delivery')
        total=sum(xs[t] for xs in saved['allocations'].values())
        equal(total,q,'Physical allocations do not add to delivered service')
        for b in s.numeric:
            if b.aggregation!='average':continue
            weighted=sum(sc.attribute_system.variants[f].numeric.get(b.attribute,0)*xs[t]
                         for f,xs in saved['allocations'].items())
            if b.lower is not None and weighted < b.lower*q-tolerance:raise AssertionError('Average below required bound')
            if b.upper is not None and weighted > b.upper*q+tolerance:raise AssertionError('Average above required bound')
            rec=saved['averages'][b.attribute]
            if len(rec)!=sc.periods:raise AssertionError('Incomplete average record')
            if q<=1e-10:
                if rec[t] is not None:raise AssertionError('Average at zero delivery must be undefined')
            else:equal(rec[t],weighted/q,'Reported average changed')
    return {'passed':True,'max_absolute_error':err,'physical_rates':saved['allocations']}


def audit_attribute_run(sc,run,tolerance=1e-6,trajectory=None):
    errors=[];records=0
    for k,e in enumerate(run['epochs']):
        for state in e['operating_states']:
            flow=state['flow']
            for d in sc.flow_system.demands:
                saved=flow['demands'][d.name]
                if d.attribute_requirement is not None:
                    if d.scale_with_demand and trajectory is None:
                        raise ValueError('Scaled required service audit needs its trajectory')
                    multiplier=trajectory.demand(d.name,k) if d.scale_with_demand else 1.0
                    targets=[v*multiplier for v in d.rates]
                    if len(saved['target_rates'])!=len(targets) or any(abs(x-y)>tolerance for x,y in zip(saved['target_rates'],targets)):
                        raise AssertionError('Required service target changed')
                    if d.hard and any(u>tolerance for u in saved['unmet_rates']):
                        raise AssertionError('Mandatory qualified service was not supplied')
                    a=audit_attribute_delivery(sc,saved.get('attributes'),family=d.form,location=d.location,
                       requirement=d.attribute_requirement,delivered_rates=saved['delivered_rates'],epoch=k,tolerance=tolerance)
                    errors.append(a['max_absolute_error']);records+=1
            if sc.need_system is not None:
                for n in sc.need_system.needs:
                    for p,saved in zip(n.profiles,flow['needs']['services'][n.name]['profiles']):
                        if p.attribute_requirement is not None:
                            a=audit_attribute_delivery(sc,saved.get('attributes'),family=p.form,location=p.location,
                              requirement=p.attribute_requirement,delivered_rates=saved['delivered_rates'],epoch=k,tolerance=tolerance)
                            errors.append(a['max_absolute_error']);records+=1
    return {'passed':True,'service_records':records,'max_absolute_error':max(errors,default=0.)}
