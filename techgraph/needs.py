"""Optional, physically delivered service value on the common technological graph.

Fixed/penalized obligations remain FlowDemand. Optional needs are bounded choices,
not required demand with an arbitrary shortfall penalty. Expenditure and delivered
value are recorded separately. This first version is deterministic.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from math import isfinite
from numbers import Real
from typing import Sequence


@dataclass(frozen=True)
class ServiceProfile:
    form: str
    location: str
    rates: tuple[float, ...]  # canonical quantity/hour in each operational period
    attribute_requirement: str | None = None


@dataclass(frozen=True)
class OptionalNeed:
    name: str
    profiles: tuple[ServiceProfile, ...]
    value: float | tuple[float, ...]  # gross value of the complete scaled profile/block
    mode: str = 'divisible'  # divisible or indivisible, not inferred from names
    recognized_from: int = 0
    expires_at: int | None = None  # exclusive
    scale: float | tuple[float, ...] = 1.0
    description: str = ''

    def value_at(self, k):
        return _at(self.value, k)

    def scale_at(self, k):
        return _at(self.scale, k)

    def recognized(self, k):
        return k >= self.recognized_from

    def eligible(self, k, valuation_epoch=None):
        p = k if valuation_epoch is None else valuation_epoch
        return (self.recognized(k) and (self.expires_at is None or k < self.expires_at)
                and self.scale_at(p) > 0)


@dataclass(frozen=True)
class NeedSystem:
    needs: tuple[OptionalNeed, ...] = ()

    def manifest(self):
        return {'needs': [asdict(n) for n in self.needs],
                'scope': 'deterministic optional service; no commitment, bargaining, or preference formation',
                'value_units': 'gross value per fully delivered representative-block profile',
                'quantity_units': 'canonical registered quantity per hour'}

    @classmethod
    def from_manifest(cls, m):
        return cls(tuple(OptionalNeed(
            n['name'], tuple(ServiceProfile(p['form'],p['location'],tuple(p['rates']),p.get('attribute_requirement')) for p in n['profiles']),
            tuple(n['value']) if isinstance(n['value'],list) else n['value'],
            mode=n.get('mode','divisible'), recognized_from=n.get('recognized_from',0),
            expires_at=n.get('expires_at'),
            scale=tuple(n['scale']) if isinstance(n.get('scale'),list) else n.get('scale',1.0),
            description=n.get('description','')) for n in m['needs']))


def _at(v, k):
    return float(v if isinstance(v,Real) else v[k])


def enabled(sc):
    system=getattr(sc,'need_system',None)
    return system is not None and bool(system.needs)


def has_discrete_needs(sc):
    return enabled(sc) and any(n.mode=='indivisible' for n in sc.need_system.needs)


def validate_needs(sc, K=None, epoch=0, contingencies=None):
    system=getattr(sc,'need_system',None)
    if system is None: return
    if not isinstance(system,NeedSystem): raise TypeError('need_system must be NeedSystem')
    if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<0:
        raise ValueError('Need epoch must be a nonnegative integer')
    if not system.needs: return
    if sc.flow_system is None: raise ValueError('Optional needs require an explicit FlowSystem')
    if len({n.name for n in system.needs})!=len(system.needs):
        raise ValueError('Optional-need names must be unique')
    if set(n.name for n in system.needs)&set(n.name for n in sc.flow_system.demands):
        raise ValueError('Optional and required service names must be distinct')
    if not isfinite(sc.hours) or sc.hours<=0 or sc.periods<=0:
        raise ValueError('Positive operating duration required')
    for n in system.needs:
        if not isinstance(n,OptionalNeed) or not isinstance(n.name,str) or not n.name:
            raise ValueError('Named OptionalNeed objects required')
        if n.mode not in {'divisible','indivisible'}: raise ValueError('Unknown need mode')
        if not isinstance(n.recognized_from,int) or isinstance(n.recognized_from,bool) or n.recognized_from<0:
            raise ValueError('Recognition epoch must be a nonnegative integer')
        if n.expires_at is not None and (not isinstance(n.expires_at,int) or isinstance(n.expires_at,bool)
                                        or n.expires_at<=n.recognized_from):
            raise ValueError('Expiry must be later than recognition')
        if not n.profiles or len({(p.form,p.location) for p in n.profiles})!=len(n.profiles):
            raise ValueError('Service requires nonempty, unique form/location profiles')
        for profile in n.profiles:
            if profile.form not in sc.flow_system.form_units or profile.location not in sc.locations:
                raise ValueError('Unknown service form/location')
            if len(profile.rates)!=sc.periods or any(not isfinite(v) or v<0 for v in profile.rates):
                raise ValueError('Service profiles must be nonnegative and cover every operating period')
            if sum(profile.rates)<=0: raise ValueError('Every service component must require positive delivery')
        for label,v in [('value',n.value),('scale',n.scale)]:
            vals=[v] if isinstance(v,Real) else list(v)
            if not vals or any(isinstance(q,bool) or not isinstance(q,Real) or not isfinite(q) or q<0 for q in vals):
                raise ValueError(f'Need {label} must be finite and nonnegative')
            if not isinstance(v,Real) and (len(v)<=epoch or (K is not None and len(v)!=K)):
                raise ValueError(f'Need {label} schedule must cover the declared horizon')


def add_need_block(prob, sc, balance, *, epoch=0, valuation_epoch=None, tag=''):
    from .backend import lp
    handle={'epoch':epoch,'valuation_epoch':epoch if valuation_epoch is None else valuation_epoch,
            'choices':{},'benefits':[],'attribute_blocks':{}}
    if not enabled(sc): return handle
    p=handle['valuation_epoch']
    for i,n in enumerate(sc.need_system.needs):
        can_serve=n.eligible(epoch,p)
        x=lp.LpVariable(f'need_{tag}_{i}',0,1,cat='Binary' if n.mode=='indivisible' else 'Continuous')
        if not can_serve: prob += x==0, f'need_eligibility_{tag}_{i}'
        scale=n.scale_at(p)
        for j,profile in enumerate(n.profiles):
            if profile.attribute_requirement is not None:
                from .attributes import add_attribute_delivery
                handle['attribute_blocks'][n.name,j]=add_attribute_delivery(prob,sc,balance,
                    profile.form,profile.location,[rate*scale*x for rate in profile.rates],
                    profile.attribute_requirement,epoch=epoch,tag=f'{tag}_optional_{i}_{j}')
            else:
                for t,rate in enumerate(profile.rates):
                    balance[profile.form,profile.location,t].append(-sc.hours*rate*scale*x)
        handle['choices'][n.name]=x
        handle['benefits'].append(n.value_at(p)*x)
    return handle


def extract_need_block(sc, handle):
    from .backend import lp
    if not enabled(sc): return {}
    k,p=handle['epoch'],handle['valuation_epoch']
    output={'epoch':k,'valuation_epoch':p,'services':{},'benefit':0.0}
    for n in sc.need_system.needs:
        x=float(lp.value(handle['choices'][n.name]))
        service={'fraction':x,'mode':n.mode,'recognized':n.recognized(k),'eligible':n.eligible(k,p),
                 'value_of_full_profile':n.value_at(p),'benefit':n.value_at(p)*x,'profiles':[]}
        for j,prof in enumerate(n.profiles):
            target=[r*n.scale_at(p) for r in prof.rates]
            delivered=[r*x for r in target]
            service['profiles'].append({'form':prof.form,'location':prof.location,
                'quantity_unit':sc.flow_system.form_units[prof.form], 'target_rates':target,
                'delivered_rates':delivered,'quantities':[sc.hours*r for r in delivered]})
            if prof.attribute_requirement is not None:
                from .attributes import extract_attribute_delivery
                service['profiles'][-1]['attributes']=extract_attribute_delivery(sc,handle['attribute_blocks'][n.name,j])
        output['services'][n.name]=service;output['benefit']+=service['benefit']
    return output


def replay_need_block(sc, saved, *, epoch=None, valuation_epoch=None, tolerance=1e-6):
    """Derive fractions and value from delivered profiles, not saved benefit fields.

    This verifies the service interface. Physical feasibility of those deliveries
    is checked independently by the common state-balance audit.
    """
    if not enabled(sc):
        if saved: raise AssertionError('Unexpected optional service record')
        return {'benefit':0.0,'fractions':{},'quantities':{},'max_absolute_error':0.0,'passed':True}
    k=saved['epoch'] if epoch is None else epoch
    p=saved['valuation_epoch'] if valuation_epoch is None else valuation_epoch
    if k!=saved['epoch'] or p!=saved['valuation_epoch']: raise AssertionError('Service epoch changed')
    if set(saved['services'])!={n.name for n in sc.need_system.needs}:
        raise AssertionError('Missing or extra optional service')
    benefit=0.0; fractions={}; quantities={}; max_error=0.0
    def equal(a,b,label):
        nonlocal max_error
        if not isfinite(float(a)) or not isfinite(float(b)): raise AssertionError('Nonfinite '+label)
        error=abs(a-b);max_error=max(max_error,error)
        if error>tolerance: raise AssertionError(label)
    for n in sc.need_system.needs:
        s=saved['services'][n.name];pfs=s['profiles']
        if len(pfs)!=len(n.profiles): raise AssertionError('Missing service component')
        ratios=[]
        for pr,rec in zip(n.profiles,pfs):
            if (pr.form,pr.location)!=(rec['form'],rec['location']) or rec['quantity_unit']!=sc.flow_system.form_units[pr.form]:
                raise AssertionError('Service port or unit changed')
            for field in ['target_rates','delivered_rates','quantities']:
                if len(rec[field])!=sc.periods: raise AssertionError('Incomplete service time profile')
            from .attributes import audit_attribute_delivery
            ar=audit_attribute_delivery(sc,rec.get('attributes'),family=pr.form,location=pr.location,
                requirement=pr.attribute_requirement,delivered_rates=rec['delivered_rates'],epoch=k,tolerance=tolerance)
            max_error=max(max_error,ar['max_absolute_error'])
            for t,base in enumerate(pr.rates):
                target=base*n.scale_at(p);delivered=rec['delivered_rates'][t]
                if not isfinite(delivered) or delivered < -tolerance or delivered > target+tolerance:
                    raise AssertionError('Delivered service outside declared bound')
                equal(target,rec['target_rates'][t],'Service target changed')
                equal(sc.hours*delivered,rec['quantities'][t],'Service quantity mismatch')
                if target>0: ratios.append(delivered/target)
                else: equal(delivered,0.0,'Delivery at zero target')
        x=ratios[0] if ratios else 0.0
        for other in ratios: equal(x,other,'Partial service bundle claimed as complete')
        equal(x,s['fraction'],'Fraction disagrees with physical delivery')
        if n.mode=='indivisible' and min(abs(x),abs(x-1))>tolerance:
            raise AssertionError('Indivisible service was fractionally delivered')
        if not n.eligible(k,p) and abs(x)>tolerance: raise AssertionError('Service outside eligibility window')
        if s['eligible']!=n.eligible(k,p) or s['recognized']!=n.recognized(k) or s['mode']!=n.mode:
            raise AssertionError('Eligibility or mode metadata changed')
        # Do not trust stored price or benefit; audit_need_block compares them.
        benefit+=n.value_at(p)*x;fractions[n.name]=x
        quantities[n.name]=[sum(rec['quantities']) for rec in pfs]
    return {'benefit':benefit,'fractions':fractions,'quantities':quantities,
            'max_absolute_error':max_error,'passed':True}


def audit_need_block(sc,saved,*,epoch=None,valuation_epoch=None,tolerance=1e-6):
    replay=replay_need_block(sc,saved,epoch=epoch,valuation_epoch=valuation_epoch,tolerance=tolerance)
    if enabled(sc):
        p=saved['valuation_epoch'] if valuation_epoch is None else valuation_epoch
        for n in sc.need_system.needs:
            s=saved['services'][n.name]
            for actual,expected in [(s['value_of_full_profile'],n.value_at(p)),
                                    (s['benefit'],n.value_at(p)*replay['fractions'][n.name])]:
                if not isfinite(actual) or abs(actual-expected)>tolerance: raise AssertionError('Service value record changed')
        if not isfinite(saved['benefit']) or abs(saved['benefit']-replay['benefit'])>tolerance:
            raise AssertionError('Total benefit record changed')
    return replay


def audit_need_run(sc,run,tolerance=1e-6):
    values=[]
    for k,e in enumerate(run['epochs']):
        if len(e['operating_states'])!=1 or e['operating_states'][0]['probability']!=1:
            raise AssertionError('Optional needs require deterministic saved operation')
        record=e['operating_states'][0]['flow'].get('needs',{})
        values.append(audit_need_block(sc,record,epoch=k,valuation_epoch=k,tolerance=tolerance))
        if abs(values[-1]['benefit']-e['service_benefit'])>tolerance: raise AssertionError('Epoch benefit mismatch')
    return {'passed':True,'max_absolute_error':max((v['max_absolute_error'] for v in values),default=0.0),
            'benefit_by_epoch':[v['benefit'] for v in values],
            'fractions_by_epoch':[v['fractions'] for v in values]}
