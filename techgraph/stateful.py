"""Generic inherited-state adapter for recursive material worlds.

No event sequence or target motif is passed to the generator. Scarcity, stores,
construction and capability renewal are declared primitives. This remains an
abstract material grammar, not a chemical or cross-domain calibration.
"""
from dataclasses import dataclass, asdict, replace
from .generative import WorldConfig, make_generative_world
from .variation import keyed_rng
from .catalog import Design
from .flows import Destination, validate_flow_system
from .stocks import StockSpec, StockSystem
from .realizability import Capability, DesignRequirement, RealizabilitySpec
from .dynamic import Vintage, solve_window


@dataclass(frozen=True)
class StateConfig:
    inventories: bool = True
    capabilities: bool = True
    preparation: bool = True
    supply_margin: float = 1.3
    inventory_periods: float = 1.5
    shortfall_penalty: float = 100.
    # v4 opt-in fixes; defaults reproduce v3.
    relocation_fix: bool = False          # relocated designs need readiness at their destination
    capability_cost_scale: float = 1.0    # multiplies acquisition costs
    capability_domains: str = 'parity'    # parity (v3: form-index parity) | function (processing vs logistics)

    def validate(self):
        from math import isfinite
        if not isfinite(self.capability_cost_scale) or self.capability_cost_scale<=0:raise ValueError('Invalid capability cost scale')
        if self.capability_domains not in {'parity','function'}:raise ValueError('Unknown capability domains')
        for n in ('inventories','capabilities','preparation','relocation_fix'):
            if not isinstance(getattr(self,n),bool):raise ValueError('Invalid '+n)
        if not .5<=self.supply_margin<=4:raise ValueError('Invalid supply margin')
        if not 0<self.inventory_periods<=10:raise ValueError('Invalid stock bound')
        if not isfinite(self.shortfall_penalty) or self.shortfall_penalty<=0:raise ValueError('Invalid shortfall penalty')
        return self


@dataclass
class StatefulWorld:
    scenario: object
    trajectory: object
    params: object
    history: list
    stocks: StockSystem
    realizability: RealizabilitySpec | None
    candidate_context: object
    metadata: dict


class StatefulCandidates:
    """Union of parent capability requirements; bounded inherited build lead.

    Composition adds one assembly period up to the declared two-period bound.
    Capability is shared technical readiness, not erased documented knowledge.
    """
    def __init__(self, config=StateConfig()):self.config=config.validate()
    def manifest(self):return {'adapter':'stateful-material-v2',**asdict(self.config),
        'new_requirements':'union of parent requirements for each stage',
        'new_lead':'max parent lead; composition adds one, capped at two periods',
        'inventories':'initial forms at all locations; no automatic warehouse for new intermediate forms'}
    def _site(self,cap,c):
        """v4 relocation fix: readiness is local, so a relocated recipe needs the
        same domain at its destination rather than at its origin."""
        if not self.config.relocation_fix or c.operator!='relocation':return cap
        _,_,domain=cap.split('_',2)
        return f'skill_{c.metadata["destination"]}_{domain}'

    def extend(self,sc,tr,prm,realizability,candidates,epoch):
        lead=dict(tr.construction_lead)
        requirements={} if realizability is None else dict(realizability.requirements)
        for c in candidates:
            n=c.design.name
            value=max((tr.lead(p,epoch) for p in c.parents),default=0)
            if c.operator=='serial_composition':value=min(2,value+1)
            lead[n]=value if self.config.preparation else 0
            if realizability is not None:
                requirements[n]=DesignRequirement(**{stage:tuple(sorted({self._site(cap,c) for p in c.parents for cap in getattr(requirements.get(p,DesignRequirement()),stage)})) for stage in ('build','operate','maintain')})
        rs=None if realizability is None else replace(realizability,requirements=requirements)
        if rs is not None:rs.validate(sc)
        return replace(tr,construction_lead=lead),rs


def make_stateful_world(world_config=WorldConfig(epochs=64),config=StateConfig()):
    cfg=config.validate();w=make_generative_world(world_config);seed=world_config.seed
    sc,tr,prm=w.scenario,w.trajectory,w.params
    rng=keyed_rng(seed,'stateful-primitives-v2')
    base_need=sum(q.rates[0] for q in sc.flow_system.demands)
    supply=base_need*cfg.supply_margin
    shares=[rng.uniform(.4,1.6) for _ in sc.flow_system.resources]
    groups={}
    for q,a in zip(sc.flow_system.resources,shares):groups[q.form]=groups.get(q.form,0.)+a
    # v3 has one raw form, so this equals supply*a/sum(shares). With several raw
    # forms (v4) the margin applies to each raw form separately.
    resources=tuple(replace(q,max_rates=(supply*a/groups[q.form],)) for q,a in zip(sc.flow_system.resources,shares))
    demands=tuple(replace(q,hard=False,penalty=cfg.shortfall_penalty) for q in sc.flow_system.demands)
    maxcap=max(20.,3*base_need)
    ds={n:replace(d,max_cap=maxcap) for n,d in sc.designs.items()}
    destinations=dict(sc.flow_system.destinations);specs={};lives=dict(prm.life)
    # Same catalog in every inventory ablation: a zero capacity store disables
    # carry-over without perturbing recipe search or design identities.
    for form in sorted(sc.flow_system.form_units):
        for loc in sc.locations:
            sr=keyed_rng(seed,'store',form,loc);name=f'inventory_{form}_{loc}'
            retention=sr.uniform(.95,1.)
            destinations[name]=Destination('tonne','stock',bearer=name,initial_stock=0.,retention=retention,removal_account='accounted_storage_loss')
            limit=base_need*cfg.inventory_periods*sr.uniform(.3,1.) if cfg.inventories else 0.
            specs[name]=StockSpec(form,loc,limit,holding_charge=sr.uniform(.005,.04))
            for prefix,kind in [('IN','sink'),('OUT','withdraw')]:
                n=f'{prefix}_{form}_{loc}'
                ds[n]=Design(n,kind,8760*.015,var_cost=.015,form=form,loc=loc,destination=name,activity_unit='tonne/h',max_cap=maxcap)
                lives[n]=sr.randint(6,12)
    sc=replace(sc,designs=ds,flow_system=replace(sc.flow_system,demands=demands,resources=resources,destinations=destinations))
    prm=replace(prm,life=lives)
    stocks=StockSystem(specs,tuple([1.]*tr.K))
    # Inherited physical assets are a current-condition optimum, with independent
    # ages. No future demand or discovery values enter initialization.
    initial=solve_window(sc,tr,prm,0,0,[],stocks=stocks,time_limit=30)
    history=[]
    for n,x in sorted(initial['epochs'][0]['builds'].items()):
        if x<=1e-8:continue
        age=keyed_rng(seed,'initial-age',n).randrange(lives[n]);d=ds[n]
        history.append(Vintage(n,-age,x,x,d.annual_cost,d.fixed_cost,lives[n]))
    lead={}
    for n,d in ds.items():
        dr=keyed_rng(seed,'preparation',n)
        lead[n]=(dr.randint(0,2) if d.kind=='process' else 0) if cfg.preparation else 0
    tr=replace(tr,construction_lead=lead)
    realizability=None
    if cfg.capabilities:
        # Two generic handling/processing domains per location. Existing forms
        # map to a domain; discoveries inherit the expertise of their parents.
        caps={};requirements={}
        for loc in sc.locations:
            for group in range(2):
                name=f'skill_{loc}_{group}';cr=keyed_rng(seed,'capability',name)
                caps[name]=Capability(cr.uniform(.3,2.5)*cfg.capability_cost_scale,cr.randint(0,1),cr.randint(8,18),'local technical readiness; acquisition/renewal')
        roles=w.metadata['module_roles']
        def req(d):
            ports=[(p.form,p.location) for p in d.input_ports+d.output_ports]
            if not ports and d.form is not None:ports=[(d.form,d.loc)]
            if cfg.capability_domains=='function':
                # Same two domains per site and same cost draws; meaning differs:
                # group 0 = processing (recipes), group 1 = logistics (transport, stocks, disposal).
                group=0 if roles.get(d.name)=='recipe' else 1
                return tuple(sorted({f'skill_{l}_{group}' for f,l in ports}))
            return tuple(sorted({f'skill_{l}_{int(f[1:])%2}' for f,l in ports}))
        for n,d in ds.items():
            skills=req(d);requirements[n]=DesignRequirement(build=skills,operate=skills)
        initial_ready=tuple(sorted({c for v in history for c in requirements[v.design].operate+requirements[v.design].build}))
        initial_until={c:keyed_rng(seed,'initial-capability-age',c).randint(1,caps[c].validity-1) for c in initial_ready}
        realizability=RealizabilitySpec(caps,requirements,initial_ready,initial_until)
        realizability.validate(sc)
    validate_flow_system(sc);stocks.validate(sc,tr.K)
    metadata={'generator':'stateful-abstract-material-v2','world_config':asdict(world_config),'state_config':asdict(cfg),
        'spatial_edges':w.metadata['spatial_edges'],'initial_solver':initial['solver'],
        'initialization':'current-condition one-period optimum; independently aged physical assets and capability readiness',
        'total_input_rate':supply,'initial_required_rate':base_need,
        'knowledge':'persistent, free archival storage; documented designs remain distinct from ready capabilities',
        'demand':'constant or independently keyed clipped log AR(1); soft service with explicit penalty',
        'unsupported':['chemical and energy feasibility beyond mass','independent actors','information copying','endogenous needs','learning-by-doing','adaptive search effort','investment finance constraint'],
        'terminal':'existing horizon-truncated representative-period capital accounting, no salvage; compare longer runs and interior periods'}
    return StatefulWorld(sc,tr,prm,history,stocks,realizability,StatefulCandidates(cfg),metadata)


def audit_stateful(result,tolerance=2e-5):
    """Independent capability clocks, inherited-state continuity and stage checks.

    Complements core physical/stock/ledger audits. It checks realized first-period
    decisions and surviving WIP; it is not a proof of global dynamic optimality.
    """
    rs=result.get('realizability');run=result['run'];tr=result['trajectory']
    previous_projects=run.get('initial_projects',[])
    grants=list(run.get('initial_capability_grants',[]));acquisitions=0;orders=0
    for k,(e,event) in enumerate(zip(run['epochs'],result['events'])):
        due=[p for p in previous_projects if p['commission']<=k]
        outstanding=[p for p in previous_projects if p['commission']>k]
        if event['opening'].get('projects',[])!=outstanding:raise ValueError('WIP continuity error')
        if event['opening'].get('capability_grants',[])!=grants:raise ValueError('Capability grant continuity error')
        ready=set()
        if rs is not None:
            ready={c for c in rs.initially_ready if rs.initial_ready_until.get(c) is None or k<=rs.initial_ready_until[c]}
            for g in e.get('realizability',{}).get('acquired',[]):
                c=rs.capabilities[g['capability']]
                if g['acquired']!=k or g['ready_from']!=k+c.acquire_lead:raise ValueError('Capability acquisition clock error')
                until=None if c.validity is None else g['ready_from']+c.validity-1
                if g['ready_until']!=until:raise ValueError('Capability validity error')
                grants.append({key:g[key] for key in ('capability','acquired','ready_from','ready_until')});acquisitions+=1
            ready.update(g['capability'] for g in grants if g['ready_from']<=k and (g['ready_until'] is None or k<=g['ready_until']))
            if ready!=set(e['realizability']['ready']):raise ValueError('Incorrect realized capability readiness')
            for n,x in e['builds'].items():
                if x>tolerance and not set(rs.requirements.get(n,DesignRequirement()).build)<=ready:raise ValueError('Order without capability')
            for n,x in e['throughput'].items():
                if x>tolerance and not set(rs.requirements.get(n,DesignRequirement()).operate)<=ready:raise ValueError('Operation without capability')
        # All installed vintages must originate in inherited assets or a previous
        # order after its construction delay. Orders canceled as WIP cannot revive.
        initial=list(event['opening']['history'])
        for v in e['vintages']:
            if v['alive']<=tolerance:continue
            n=v['design'];built=v['built']
            allowance=sum(x['alive'] for x in initial if x['design']==n and x['built']==built and k<x['built']+x['life'])
            if built==k and tr.lead(n,k)==0:allowance+=e['builds'].get(n,0.)
            if v['alive']>allowance+tolerance:raise ValueError('Premature or ungrounded commissioned capacity')
        closing=event.get('projects_after',[])
        for p in closing:
            if p['commission']<=k:raise ValueError('Commissioned project still in WIP')
            if p['ordered']==k:
                if p['commission']!=k+tr.lead(p['design'],k):raise ValueError('Construction clock error')
                if abs(p['capacity']-e['builds'].get(p['design'],0.))>tolerance:raise ValueError('WIP order quantity error')
                orders+=1
            else:
                old=[q for q in outstanding if q['design']==p['design'] and q['ordered']==p['ordered'] and q['commission']==p['commission']]
                if len(old)!=1 or p['capacity']>old[0]['capacity']+tolerance:raise ValueError('Canceled WIP revived')
        previous_projects=closing
    return {'passed':True,'capability_acquisitions':acquisitions,'delayed_orders':orders,'epochs_checked':len(run['epochs'])}
