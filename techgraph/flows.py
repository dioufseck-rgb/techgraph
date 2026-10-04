"""Opt-in coupled-output recipes, explicit destinations, and typed demands.

This module owns the *extension* constraints shared by static and dynamic engines.
It does not replace the old operating primitives or silently change old worlds.
All coefficients are declared engineering inputs. Canonical quantities are MWh
and tonnes; conversions conserve them only where the recipe explicitly says so.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Mapping


@dataclass(frozen=True)
class Port:
    form: str
    location: str
    coefficient: float = 1.0  # units of form per unit of integrated activity
    interface: str | None = None
    version: str | None = None
    compatible_with: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FlowDemand:
    name: str
    form: str
    location: str
    rates: tuple[float, ...]
    hard: bool = True
    penalty: float = 3000.0  # per unmet canonical quantity, not necessarily per MWh
    scale_with_demand: bool = True
    attribute_requirement: str | None = None


@dataclass(frozen=True)
class FlowResource:
    name: str
    form: str
    location: str
    max_rates: tuple[float, ...]
    unit_cost: float = 0.0


@dataclass(frozen=True)
class Destination:
    quantity_unit: str
    kind: str = 'release'  # release, disposal, stock
    bearer: str = 'environment'
    private_charge: float = 0.0  # per intake unit, added to sink operating cost
    block_limit: float | None = None  # common intake limit across sinks in one operating block
    impact_factors: Mapping[str, float] = field(default_factory=dict)
    initial_stock: float = 0.0
    retention: float = 1.0  # per decision epoch; passive accounts only
    removal_account: str | None = None


@dataclass(frozen=True)
class FlowSystem:
    form_units: Mapping[str, str] = field(default_factory=lambda: {'fuel':'MWh', 'elec':'MWh', 'h2':'MWh'})
    demands: tuple[FlowDemand, ...] = ()
    destinations: Mapping[str, Destination] = field(default_factory=dict)
    spill_forms: tuple[str, ...] = ()  # explicit opt-in only; empty means no implicit spill
    hard_legacy_service: bool = False
    resources: tuple[FlowResource, ...] = ()
    emissions_impact: str | None = None  # explicit mapping to legacy tonnes-CO2 field


def forms(sc):
    """Substances with balances. Without an explicit flow system: the catalog's standard forms, followed by any
    other substance referenced by designs or demands (in first-seen order), so that existing scenarios keep exactly
    the same balances."""
    from .catalog import FORMS
    if sc.flow_system is not None:
        return tuple(sc.flow_system.form_units)
    extra = []
    for d in sc.designs.values():
        for f in (getattr(d, 'form_in', None), getattr(d, 'form_out', None), getattr(d, 'form', None)):
            if f and f not in FORMS and f not in extra:
                extra.append(f)
    for dm in (getattr(sc, 'demands', ()) or ()):
        f = getattr(dm, 'form', 'elec')
        if f not in FORMS and f not in extra:
            extra.append(f)
    return tuple(FORMS) + tuple(extra)


def uses_legacy_contract(sc):
    """Whether a scenario uses the historical electricity-service compatibility layer."""
    legacy_kinds={'convert','renewable','transport','store'}
    return (any(d.kind in legacy_kinds for d in sc.designs.values())
            or bool(sc.fuel_sites)
            or any(abs(float(v))>0 for v in sc.demand_D)
            or bool(sc.extra_demand)
            or bool(getattr(sc, 'demands', ()))
            or sc.hub_energy>0)

def permits_spill(sc, form):
    return sc.flow_system is None or form in sc.flow_system.spill_forms


def hard_legacy_service(sc):
    return sc.flow_system is not None and sc.flow_system.hard_legacy_service


def validate_flow_system(sc):
    from .interfaces import validate_interfaces
    validate_interfaces(sc)
    fs = sc.flow_system
    if fs is None:
        if any(d.kind in {'process','sink','withdraw'} for d in sc.designs.values()):
            raise ValueError('Process and sink designs require an explicit FlowSystem')
        return
    if not isinstance(fs, FlowSystem):
        raise TypeError('flow_system must be a FlowSystem')
    if not isinstance(sc.periods,int) or sc.periods<=0 or not isfinite(sc.hours) or sc.hours<=0:
        raise ValueError('Positive operational period count and duration required')
    legacy = uses_legacy_contract(sc)
    if legacy and not {'fuel','elec','h2'} <= set(fs.form_units):
        raise ValueError('Legacy electricity-service scenarios require fuel/elec/h2 compatibility forms')
    if any(not isinstance(f,str) or not f or u not in {'MWh','tonne'} for f,u in fs.form_units.items()):
        raise ValueError('Forms require a name and supported canonical quantity unit')
    if legacy and any(fs.form_units[f]!='MWh' for f in ('fuel','elec','h2')):
        raise ValueError('Legacy compatibility carriers must use MWh')
    if set(fs.spill_forms)-set(fs.form_units) or len(set(fs.spill_forms))!=len(fs.spill_forms):
        raise ValueError('Invalid spill-form declaration')
    if len({q.name for q in fs.demands})!=len(fs.demands):
        raise ValueError('Demand names must be unique')
    def valid_port(f,l):
        if f not in fs.form_units or l not in sc.locations:
            raise ValueError(f'Unknown form/location: {(f,l)}')
    if len({q.name for q in fs.resources})!=len(fs.resources):
        raise ValueError('Resource names must be unique')
    for q in fs.resources:
        valid_port(q.form,q.location)
        if not q.name or len(q.max_rates)!=sc.periods or any(not isfinite(v) or v<0 for v in q.max_rates):
            raise ValueError('Resource requires nonnegative full-length availability')
        if not isfinite(q.unit_cost) or q.unit_cost<0:
            raise ValueError('Resource price must be finite and nonnegative')
    for q in fs.demands:
        valid_port(q.form,q.location)
        if not q.name or len(q.rates)!=sc.periods or any(not isfinite(v) or v<0 for v in q.rates):
            raise ValueError('Demand requires a name and nonnegative full-length rates')
        if not isinstance(q.hard,bool) or not isinstance(q.scale_with_demand,bool):
            raise ValueError('Demand flags must be Boolean')
        if not isfinite(q.penalty) or q.penalty<0:
            raise ValueError('Demand penalty must be finite and nonnegative')
    for name,dest in fs.destinations.items():
        if not name or dest.kind not in {'release','disposal','stock'} or dest.quantity_unit not in {'MWh','tonne'}:
            raise ValueError('Invalid named destination')
        if not dest.bearer:
            raise ValueError('Destination bearer must be explicit')
        if not isfinite(dest.private_charge) or dest.private_charge<0:
            raise ValueError('Destination charges must be nonnegative')
        if dest.block_limit is not None and (not isfinite(dest.block_limit) or dest.block_limit<0):
            raise ValueError('Destination limit must be nonnegative')
        if not isfinite(dest.initial_stock) or dest.initial_stock<0 or not isfinite(dest.retention) or not 0<=dest.retention<=1:
            raise ValueError('Invalid stock initial state or retention')
        if dest.retention<1 and not dest.removal_account:
            raise ValueError('Decaying stock must name its removal account')
        if dest.kind!='stock' and (dest.initial_stock!=0 or dest.retention!=1):
            raise ValueError('Only stock destinations have stock initial state/retention')
        if any(not k or not isfinite(v) or v<0 for k,v in dest.impact_factors.items()):
            raise ValueError('Impact factors require names and nonnegative coefficients')
    if fs.emissions_impact is not None and not any(fs.emissions_impact in d.impact_factors for d in fs.destinations.values()):
        raise ValueError('Emission mapping must name an explicitly declared impact dimension')
    for name,d in sc.designs.items():
        if d.kind=='corridor':
            # v4 shared transport infrastructure: capacity only, no ports or flows.
            if d.input_ports or d.output_ports or d.var_cost<0:raise ValueError('Corridor designs carry capacity only')
            continue
        if d.kind not in {'convert','renewable','transport','store','process','sink','withdraw'}:
            raise ValueError(f'Unknown module kind {d.kind!r}')
        if not isfinite(d.var_cost) or d.var_cost<0:
            raise ValueError('Explicit-flow examples require nonnegative variable costs')
        for f,l in d.inputs()+d.outputs(): valid_port(f,l)
        if d.kind=='process':
            if not d.input_ports or not d.output_ports:
                raise ValueError('A process needs both inputs and outputs; use a named sink for termination')
            if d.activity_unit not in {'MW','tonne/h'}:
                raise ValueError('Process activity must use canonical MW or tonne/h')
            if d.emis!=0:
                raise ValueError('Explicit processes record emissions through ports/destinations, not legacy emis')
            for ports in (d.input_ports,d.output_ports):
                if len({(p.form,p.location,p.interface,p.version) for p in ports})!=len(ports):
                    raise ValueError('Duplicate ports on one side of a process')
                if any(not isfinite(p.coefficient) or p.coefficient<=0 for p in ports):
                    raise ValueError('Port coefficients must be finite and positive')
            if d.conserve_energy:
                incoming=sum(p.coefficient for p in d.input_ports if fs.form_units[p.form]=='MWh')
                outgoing=sum(p.coefficient for p in d.output_ports if fs.form_units[p.form]=='MWh')
                if abs(incoming-outgoing)>1e-10*max(1,incoming,outgoing):
                    raise ValueError(f'Declared energy recipe for {name} does not balance')
            if d.conserve_mass:
                incoming=sum(p.coefficient for p in d.input_ports if fs.form_units[p.form]=='tonne')
                outgoing=sum(p.coefficient for p in d.output_ports if fs.form_units[p.form]=='tonne')
                if abs(incoming-outgoing)>1e-10*max(1,incoming,outgoing):
                    raise ValueError(f'Declared mass recipe for {name} does not balance')
        elif d.kind in {'sink','withdraw'}:
            if d.destination not in fs.destinations:
                raise ValueError('Every sink must have a registered destination')
            if d.input_ports or d.output_ports or d.emis!=0:
                raise ValueError('A sink has one form/location intake and no output/legacy emissions')
            if d.kind=='withdraw' and fs.destinations[d.destination].kind!='stock':
                raise ValueError('Withdrawal must name a stock destination')
            unit=fs.form_units[d.form]
            expected='MW' if unit=='MWh' else 'tonne/h'
            if d.activity_unit!=expected or fs.destinations[d.destination].quantity_unit!=unit:
                raise ValueError('Sink, form and destination units must agree')
        elif d.kind in {'store','transport'} and fs.form_units[d.form]!='MWh':
            raise ValueError('Legacy transport/storage are energy-only; use a process for mass transfer')
        elif d.kind=='convert' and (fs.form_units[d.form_in]!='MWh' or fs.form_units[d.form_out]!='MWh'):
            raise ValueError('Legacy conversions are energy-only; declare a process recipe for other units')


def add_flow_block(prob, sc, caps, balance, tag='', dm=1.0, epoch=0, demand_scale=None, resource_scale=None):
    """Attach extension operations and demands to a common state-balance problem."""
    from .backend import lp
    fs=sc.flow_system
    empty={'activities':{},'cost':[],'energy_unmet':[],'demands':{},'destinations':{},'cap_links':{},'resources':{},'emissions':[]}
    if fs is None: return empty
    H,T=sc.hours,sc.periods
    out=empty
    dest_exprs={name:[] for name in fs.destinations}
    for i,(name,c) in enumerate(caps.items()):
        d=sc.designs[name]
        if d.kind not in {'process','sink','withdraw'}: continue
        a=[lp.LpVariable(f'flow_a_{tag}_{i}_{t}',0) for t in range(T)]
        out['activities'][name]=a
        for t in range(T):
            cname=f'flow_cap_{tag}_{i}_{t}'
            prob += a[t]<=c,cname
            out['cap_links'].setdefault(name,[]).append((cname,1.0))
            if d.kind=='process':
                for p in d.input_ports:
                    if p.interface is None: balance[p.form,p.location,t].append(-H*p.coefficient*a[t])
                for p in d.output_ports:
                    if p.interface is None: balance[p.form,p.location,t].append(H*p.coefficient*a[t])
            elif d.kind=='withdraw':
                balance[d.form,d.loc,t].append(H*a[t])
            else:
                balance[d.form,d.loc,t].append(-H*a[t])
                dest_exprs[d.destination].append(H*a[t])
                out['cost'].append(H*fs.destinations[d.destination].private_charge*a[t])
            out['cost'].append(H*d.var_cost*a[t])
    from .interfaces import add_interface_block
    out["interfaces"] = add_interface_block(prob,sc,out["activities"],epoch,tag)
    for i,q in enumerate(fs.resources):
        rscale=1.0 if resource_scale is None else resource_scale.get(q.name,1.0)
        xs=[lp.LpVariable(f'flow_resource_{tag}_{i}_{t}',0,q.max_rates[t]*rscale) for t in range(T)]
        out['resources'][q.name]=xs
        if resource_scale is not None: out.setdefault('resource_limits',{})[q.name]=[q.max_rates[t]*rscale for t in range(T)]
        for t in range(T):
            balance[q.form,q.location,t].append(H*xs[t]);out['cost'].append(q.unit_cost*H*xs[t])
    for i,q in enumerate(fs.demands):
        multiplier = (demand_scale or {}).get(q.name, dm) if q.scale_with_demand else 1.0
        target=[v*multiplier for v in q.rates]
        u=[lp.LpVariable(f'flow_unmet_{tag}_{i}_{t}',0,0 if q.hard else target[t]) for t in range(T)]
        allocation = None
        if q.attribute_requirement is not None:
            from .attributes import add_attribute_delivery
            allocation = add_attribute_delivery(prob,sc,balance,q.form,q.location,
                [target[t]-u[t] for t in range(T)],q.attribute_requirement,epoch=epoch,tag=f'{tag}_required_{i}')
        for t in range(T):
            # Qualified services consume their physically allocated variants instead.
            if q.attribute_requirement is None:
                balance[q.form,q.location,t].extend([H*u[t],-H*target[t]])
            out['cost'].append(q.penalty*H*u[t])
            if fs.form_units[q.form]=='MWh': out['energy_unmet'].append(H*u[t])
        out['demands'][q.name]={'target_rates':target,'unmet_rates':u,'attribute_block':allocation}
    for i,(name,terms) in enumerate(dest_exprs.items()):
        quantity=lp.lpSum(terms)
        limit=fs.destinations[name].block_limit
        if limit is not None: prob += quantity<=limit,f'flow_dest_limit_{tag}_{i}'
        out['destinations'][name]=quantity
        if fs.emissions_impact is not None:
            out['emissions'].append(fs.destinations[name].impact_factors.get(fs.emissions_impact,0)*quantity)
    return out


def extract_flow_block(sc, block):
    """Save per-period primitive quantities and explicitly derived port quantities."""
    from .backend import lp
    if sc.flow_system is None: return {}
    val=lambda x:float(lp.value(x))
    fs=sc.flow_system; H=sc.hours
    from .needs import extract_need_block
    from .attributes import extract_attribute_delivery
    result={'needs':extract_need_block(sc,block.get('need_block',{})),
            'activity':{},'demands':{},'destinations':{},'form_units':dict(fs.form_units),
            'spill_forms':list(fs.spill_forms),'resources':{}}
    from .interfaces import extract_interfaces
    if "interfaces" in block: result["interfaces"] = extract_interfaces(sc,block["interfaces"])
    for name,xs in block['activities'].items():
        d=sc.designs[name]; rates=[val(x) for x in xs]
        ins=d.input_ports if d.kind=='process' else ((Port(d.form,d.loc),) if d.kind=='sink' else ())
        outs=d.output_ports if d.kind=='process' else ((Port(d.form,d.loc),) if d.kind=='withdraw' else ())
        result['activity'][name]={
            'rates':rates,'activity_unit':d.activity_unit,
            'inputs':[dict(form=p.form,location=p.location,quantity_unit=fs.form_units[p.form],
                           quantities=[H*p.coefficient*v for v in rates]) for p in ins],
            'outputs':[dict(form=p.form,location=p.location,quantity_unit=fs.form_units[p.form],
                            quantities=[H*p.coefficient*v for v in rates]) for p in outs],
        }
    for r in fs.resources:
        result['resources'][r.name]={'form':r.form,'location':r.location,'quantity_unit':fs.form_units[r.form],
                                     'rates':[val(x) for x in block['resources'][r.name]]}
        if r.name in block.get('resource_limits',{}):result['resources'][r.name]['limits']=list(block['resource_limits'][r.name])
    for q in fs.demands:
        dd=block['demands'][q.name]
        unmet=[val(x) for x in dd['unmet_rates']]; targets=dd['target_rates']
        result['demands'][q.name]={'form':q.form,'location':q.location,'quantity_unit':fs.form_units[q.form],
                                 'target_rates':targets,'unmet_rates':unmet,
                                 'delivered_rates':[v-u for v,u in zip(targets,unmet)]}
        if q.attribute_requirement is not None:
            result['demands'][q.name]['attributes']=extract_attribute_delivery(sc,dd['attribute_block'])
    for name,expression in block['destinations'].items():
        d=fs.destinations[name];quantity=val(expression)
        result['destinations'][name]={'quantity':quantity,'quantity_unit':d.quantity_unit,
             'kind':d.kind,'bearer':d.bearer,'private_charge':d.private_charge*quantity,
             'impacts':{k:v*quantity for k,v in d.impact_factors.items()}}
    return result


def replay_flow_cost(sc, quantities):
    """Reprice new operations from saved activity/unmet quantities, not cost fields."""
    if sc.flow_system is None: return {'cost':0.,'energy_unmet':0.,'intakes':{},'emissions':0.}
    fs=sc.flow_system; H=sc.hours; cost=0.;energy_unmet=0.
    intakes={k:0. for k in fs.destinations}
    for n,a in quantities['activity'].items():
        d=sc.designs[n];q=H*sum(a['rates'])
        cost+=d.var_cost*q
        if d.kind=='sink':
            intakes[d.destination]+=q
            cost+=fs.destinations[d.destination].private_charge*q
    for r in fs.resources:
        cost+=r.unit_cost*H*sum(quantities['resources'][r.name]['rates'])
    for d in fs.demands:
        q=H*sum(quantities['demands'][d.name]['unmet_rates']);cost+=d.penalty*q
        if fs.form_units[d.form]=='MWh': energy_unmet+=q
    em=sum(q*fs.destinations[n].impact_factors.get(fs.emissions_impact,0) for n,q in intakes.items()) if fs.emissions_impact is not None else 0.
    return {'cost':cost,'energy_unmet':energy_unmet,'intakes':intakes,'emissions':em}


def audit_flow_block(sc, quantities, capacities, tolerance=1e-6):
    """Check port ratios, capacities, demands and endpoint accounting independently.

    State balances involving legacy activities are checked separately. No solver
    is invoked and stored port totals/cost totals are not trusted as inputs.
    """
    if sc.flow_system is None: return {'passed':True,'scope':'legacy'}
    from .interfaces import audit_interfaces
    audit_interfaces(sc,quantities,tolerance)
    fs=sc.flow_system; H,T=sc.hours,sc.periods; max_error=0.
    def equal(a,b,message):
        nonlocal max_error
        err=abs(a-b);max_error=max(max_error,err)
        if err>tolerance: raise AssertionError(message)
    for n,a in quantities['activity'].items():
        d=sc.designs[n]
        if len(a['rates'])!=T: raise AssertionError('Incomplete activity record')
        if any(v < -tolerance or v>capacities.get(n,0)+tolerance for v in a['rates']):
            raise AssertionError('Activity outside installed capacity')
        for label,ports in [('inputs', d.input_ports if d.kind=='process' else ((Port(d.form,d.loc),) if d.kind=='sink' else ())),
                             ('outputs',d.output_ports if d.kind=='process' else ((Port(d.form,d.loc),) if d.kind=='withdraw' else ()))]:
            if len(ports)!=len(a[label]): raise AssertionError('Missing/extra port')
            for p,record in zip(ports,a[label]):
                if (p.form,p.location)!=(record['form'],record['location']): raise AssertionError('Port changed')
                if len(record['quantities'])!=T:raise AssertionError('Incomplete port series')
                for rate,quantity in zip(a['rates'],record['quantities']):
                    equal(H*p.coefficient*rate,quantity,'Broken co-product coupling')
    for r in fs.resources:
        rates=quantities['resources'][r.name]['rates']
        limits=quantities['resources'][r.name].get('limits',r.max_rates)
        if any(l>m+tolerance for l,m in zip(limits,r.max_rates)):raise AssertionError('Resource limit above declared maximum')
        if len(rates)!=T or any(v < -tolerance or v>lim+tolerance for v,lim in zip(rates,limits)):
            raise AssertionError('Invalid resource supply')
    for d in fs.demands:
        a=quantities['demands'][d.name]
        if any(len(a[key])!=T for key in ('target_rates','unmet_rates','delivered_rates')):
            raise AssertionError('Incomplete demand series')
        for tar,u,served in zip(a['target_rates'],a['unmet_rates'],a['delivered_rates']):
            if u < -tolerance or u>tar+tolerance or (d.hard and u>tolerance): raise AssertionError('Invalid service shortfall')
            equal(tar-u,served,'Bad delivered-service record')
        from .attributes import audit_attribute_delivery
        audit_attribute_delivery(sc,a.get('attributes'),family=d.form,location=d.location,
            requirement=d.attribute_requirement,delivered_rates=a['delivered_rates'],tolerance=tolerance)
    replay=replay_flow_cost(sc,quantities)
    for n,q in replay['intakes'].items():
        dest=fs.destinations[n]; saved=quantities['destinations'][n]
        equal(q,saved['quantity'],'Wrong destination intake')
        equal(q*dest.private_charge,saved['private_charge'],'Wrong destination charge')
        if dest.block_limit is not None and q>dest.block_limit+tolerance: raise AssertionError('Destination limit exceeded')
        for k,v in dest.impact_factors.items(): equal(q*v,saved['impacts'][k],'Wrong impact')
    return {'passed':True,'max_absolute_error':max_error,'intakes':replay['intakes']}


def impact_ledger(sc, run, *, block_weights):
    """Passive stock/impact replay with *explicit* representative-block weights.

    Probability-weighted operating states produce expected linear quantities.
    Stock accumulation does not constrain the optimizer in this release.
    """
    fs=sc.flow_system
    if run.get('stock_config') is not None:
        raise ValueError('Passive impact_ledger would ignore withdrawals: use audit_stock_run for active stocks')
    if fs is None: raise ValueError('Impact ledger requires an explicit flow system')
    if len(block_weights)!=len(run['epochs']) or any(not isfinite(w) or w<0 for w in block_weights):
        raise ValueError('Supply one finite nonnegative block weight per decision epoch')
    stock={n:d.initial_stock for n,d in fs.destinations.items() if d.kind=='stock'}
    totals={n:0. for n in fs.destinations}; rows=[]
    for k,(epoch,w) in enumerate(zip(run['epochs'],block_weights)):
        inflows={n:0. for n in fs.destinations}
        for state in epoch['operating_states']:
            replay=replay_flow_cost(sc,state['flow'])
            for n,q in replay['intakes'].items(): inflows[n]+=state['probability']*w*q
        entries={}
        for n,d in fs.destinations.items():
            q=inflows[n];totals[n]+=q
            e={'intake':q,'quantity_unit':d.quantity_unit,'bearer':d.bearer,
               'impacts':{j:f*q for j,f in d.impact_factors.items()}}
            if d.kind=='stock':
                previous=stock[n];removed=(1-d.retention)*previous
                stock[n]=previous-removed+q
                e.update(stock_start=previous,stock_end=stock[n],removed=removed,removal_account=d.removal_account)
            entries[n]=e
        rows.append({'epoch':k,'block_weight':w,'destinations':entries})
    return {'scope':'passive expected-quantity accounts; no stock-dependent optimization',
            'block_weights':list(block_weights),'epochs':rows,'destination_totals':totals,
            'destination_units':{n:d.quantity_unit for n,d in fs.destinations.items()},'final_stocks':stock}
