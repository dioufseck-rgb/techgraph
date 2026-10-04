"""Per-state physical replay for explicitly recorded flow scenarios."""
from __future__ import annotations
from .operation import next_period as _next
from .flows import forms


def extract_physical(sc, raw):
    from .backend import lp
    V=lambda e:float(lp.value(e))
    return {
        'activities':{n:{s:[V(x) for x in xs] for s,xs in a.items()} for n,a in raw['activities'].items()},
        'capacities':{n:V(c) for n,c in raw['capacities'].items()},
        'fuel':{l:[V(x) for x in xs] for l,xs in raw['fuel'].items()},
        'electricity_demands':[{'location':l,'period':t,'target':q,'unmet':V(raw['shortfalls'][l,t])}
                               for (l,t),q in raw['demands'].items()],
        'hub_rates':[V(x) for x in raw['hub']], 'hub_target':raw['hub_target'], 'unmet_hub':V(raw['unmet_hub']),
        'profiles':raw['profiles'],
        'spills':[{'form':f,'location':l,'period':t,'rate':V(x)} for (f,l,t),x in raw['spills'].items()],
    }


def audit_operating_state(sc, state, tolerance=1e-6):
    """Reconstruct state balances and limits from primitive activities, not totals."""
    from .interfaces import audit_interfaces
    audit_interfaces(sc,state['flow'],tolerance)
    r=state['physical'];H,T=sc.hours,sc.periods
    net={(f,l,t):0.0 for f in forms(sc) for l in sc.locations for t in range(T)}
    violations=[]
    def bounded(value,limit,label):
        if value < -tolerance or value>limit+tolerance:violations.append(label)
    for n,a in r['activities'].items():
        d=sc.designs[n];c=r['capacities'][n]
        for t in range(T):
            if d.kind=='process':
                rate=a['activity'][t];bounded(rate,c,n)
                for p in d.input_ports:net[p.form,p.location,t]-=H*p.coefficient*rate
                for p in d.output_ports:net[p.form,p.location,t]+=H*p.coefficient*rate
            elif d.kind=='withdraw':
                rate=a['activity'][t];bounded(rate,c,n);net[d.form,d.loc,t]+=H*rate
            elif d.kind=='sink':
                rate=a['activity'][t];bounded(rate,c,n);net[d.form,d.loc,t]-=H*rate
            elif d.kind=='convert':
                rate=a['output'][t];bounded(rate,c,n)
                net[d.form_out,d.loc,t]+=H*rate;net[d.form_in,d.loc,t]-=H*rate/d.eff
            elif d.kind=='renewable':
                rate=a['output'][t];bounded(rate,c*r['profiles'][d.profile][t],n);net['elec',d.loc,t]+=H*rate
            elif d.kind=='transport':
                for key,origin,dest in [('forward',d.loc_from,d.loc_to),('backward',d.loc_to,d.loc_from)]:
                    if key not in a:continue
                    rate=a[key][t];bounded(rate,c,n)
                    net[d.form,origin,t]-=H*rate;net[d.form,dest,t]+=H*(1-d.loss)*rate
            elif d.kind=='store':
                ch,ds,so=a['charge'][t],a['discharge'][t],a['level'][t]
                bounded(ch,c/d.duration_h,n);bounded(ds,c/d.duration_h,n);bounded(so,c,n)
                error=a['level'][_next(sc,t)]-so-H*(d.eta_c*ch-ds/d.eta_d)
                if abs(error)>tolerance:violations.append('storage recurrence '+n)
                net[d.form,d.loc,t]+=H*(ds-ch)
    for site,xs in r['fuel'].items():
        for t,rate in enumerate(xs):
            if rate < -tolerance:violations.append('negative resource')
            net['fuel',site,t]+=H*rate
    for q in r['electricity_demands']:
        bounded(q['unmet'],q['target'],'unserved electricity')
        if sc.flow_system.hard_legacy_service and q['unmet']>tolerance:violations.append('hard electricity service')
        net['elec',q['location'],q['period']]+=H*(q['unmet']-q['target'])
    if r['hub_target']>0:
        for t,rate in enumerate(r['hub_rates']):net['elec',sc.hub_loc,t]-=H*rate
        if abs(H*sum(r['hub_rates'])+r['unmet_hub']-r['hub_target'])>tolerance:violations.append('hub requirement')
    for resource in state['flow']['resources'].values():
        for t,rate in enumerate(resource['rates']):net[resource['form'],resource['location'],t]+=H*rate
    from .attributes import audit_attribute_delivery
    def consume(profile, family, location, requirement):
        allocation=audit_attribute_delivery(sc,profile.get('attributes'),family=family,location=location,
             requirement=requirement,delivered_rates=profile['delivered_rates'],tolerance=tolerance)['physical_rates']
        for form,rates in allocation.items():
            for t,rate in enumerate(rates): net[form,location,t]-=H*rate
    for demand in sc.flow_system.demands:
        consume(state['flow']['demands'][demand.name],demand.form,demand.location,demand.attribute_requirement)
    if sc.need_system is not None:
        for need in sc.need_system.needs:
            service=state['flow']['needs']['services'][need.name]
            for definition,profile in zip(need.profiles,service['profiles']):
                consume(profile,definition.form,definition.location,definition.attribute_requirement)
    for sp in r['spills']:
        if sp['form'] not in sc.flow_system.spill_forms or sp['rate'] < -tolerance:violations.append('undeclared spill')
        net[sp['form'],sp['location'],sp['period']]-=H*sp['rate']
    bad={str(k):v for k,v in net.items() if abs(v)>tolerance}
    if violations or bad:raise AssertionError({'constraints':violations,'balances':bad})
    return {'passed':True,'max_absolute_balance_error':max(map(abs,net.values()),default=0.0),
            'balance_count':len(net)}
