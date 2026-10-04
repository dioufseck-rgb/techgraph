"""Independent exogenous demand coordinates over the frozen stateful-v2 core.

Treatment paths prescribe needs only. No operating outcome or invention is seeded.
"""
from dataclasses import asdict, replace
import math
import numpy as np
from techgraph.generative import WorldConfig, SearchConfig
from techgraph.stateful import StateConfig, make_stateful_world
from techgraph.flows import FlowDemand, validate_flow_system
from techgraph.dynamic import Vintage, solve_window
from techgraph.variation import keyed_rng
from techgraph.vsr import VSRConfig

TREATMENTS = (
    'constant', 'growth20', 'growth40', 'decline20', 'decline40',
    'cycle16', 'cycle24', 'irregular0', 'irregular85', 'pulse40',
    'geo_ref50', 'geo_ref80', 'geo_far50', 'geo_far80', 'geo_return80',
    'mix_a65', 'mix_a80', 'mix_b65', 'mix_b80', 'mix_return80',
)
LONG_TREATMENTS = ('constant', 'growth40', 'cycle16', 'geo_return80', 'mix_return80')

def specs(mode):
    if mode == 'smoke':
        return [dict(seed=s, treatment=t, epochs=72, horizon=4)
                for s in (290, 291) for t in ('constant', 'geo_return80')]
    return ([dict(seed=s, treatment=t, epochs=72, horizon=4)
             for s in range(300, 324) for t in TREATMENTS]
            + [dict(seed=s, treatment=t, epochs=96, horizon=4)
               for s in range(300, 304) for t in LONG_TREATMENTS])

def coordinates(seed, treatment, epochs, locations, reference, distant):
    """demand(service, site, t) = base_total * scale(t) * mix(service,t) * space(site,t)."""
    if treatment not in TREATMENTS: raise ValueError(treatment)
    if epochs < 72: raise ValueError('Demand schedules require at least 72 periods')
    k = np.arange(epochs)
    ramp = np.clip((k - 8) / 47, 0, 1)
    scale = np.ones(epochs)
    mix = np.full(epochs, .5)
    alpha = np.zeros(epochs)
    centers = np.full(epochs, reference)
    if treatment.startswith(('growth', 'decline')):
        sign = 1 if treatment.startswith('growth') else -1
        scale += sign * int(treatment[-2:]) / 100 * ramp
    elif treatment.startswith('cycle'):
        period = int(treatment[5:])
        scale[8:56] += .4 * np.sin(2 * np.pi * np.arange(48) / period)
    elif treatment.startswith('irregular'):
        rho = .85 if treatment.endswith('85') else 0.
        rg = keyed_rng(seed, 'demand-ordering-v3')
        x = 0.; values = []
        for _ in range(48):
            x = rho * x + rg.gauss(0, 1)
            values.append(x)
        # Equal realized marginal distribution, volume and RMS across the pair;
        # only ordering differs. This is not claimed to be an exact AR process.
        ordered = np.empty(48)
        ordered[np.argsort(values)] = np.linspace(-.4, .4, 48)
        scale[8:56] += ordered
    elif treatment == 'pulse40':
        scale[24:40] += .4
    elif treatment.startswith('geo_'):
        strength = int(treatment[-2:]) / 100
        alpha = strength * np.clip((k - 8) / 7, 0, 1)
        if treatment.startswith('geo_far'): centers[:] = distant
        if treatment == 'geo_return80': centers[24:48] = distant
    elif treatment.startswith('mix_'):
        if treatment == 'mix_return80':
            # Gradual outward and return legs; exactly baseline again at 56.
            excursion = np.maximum(0, 1 - np.abs((k - 32) / 24))
            mix += .3 * excursion
        else:
            target = int(treatment[-2:]) / 100
            mix += (1 if treatment.startswith('mix_a') else -1) * (target - .5) * ramp
    spatial = np.repeat(((1-alpha)/locations)[:, None], locations, axis=1)
    spatial[np.arange(epochs), centers] += alpha
    return {'scale': scale, 'mix_a': mix, 'spatial': spatial, 'alpha': alpha, 'center': centers}

def make_base(seed, epochs, realism=None):
    from techgraph.realism import RealismConfig, apply_bins, apply_lumps, add_corridors
    R = (realism or RealismConfig()).validate()
    large = seed % 2 == 1
    dense = (seed // 2) % 2 == 1
    wc = WorldConfig(seed=seed, epochs=epochs, locations=4 if large else 3, forms=6,
                     extra_recipes=8 if dense else 4, edge_probability=.7 if dense else .1,
                     demand_volatility=0., raw_forms=R.raw_forms)
    rg = keyed_rng(seed, 'demand-world-primitives-v3')
    state = StateConfig(supply_margin=rg.uniform(.95, 1.65), inventory_periods=rg.uniform(.5, 2.),
                        relocation_fix=R.relocation_fix, capability_cost_scale=R.capability_cost_scale,
                        capability_domains=R.capability_domains)
    w = make_stateful_world(wc, state)
    sc, tr, prm = w.scenario, w.trajectory, w.params
    old_demands = sc.flow_system.demands
    total = sum(q.rates[0] for q in old_demands)
    forms = [q.form for q in old_demands]
    demands = tuple(FlowDemand(f'need{i}_{loc}', f, loc, (total/(2*len(sc.locations)),),
                               hard=False, penalty=state.shortfall_penalty)
                    for i,f in enumerate(forms) for loc in sc.locations)
    sc = replace(sc, flow_system=replace(sc.flow_system, demands=demands))
    tr = replace(tr, demand_scale={q.name:[1.]*epochs for q in demands})
    # Reinitialize once for distributed equal-mix demand, retaining the original
    # current-condition rule: initial assets are acquired with zero build lead,
    # then independently aged; no future demand/invention enters initialization.
    # v4 transformations precede the initial allocation, so inherited assets
    # are optimal for the transformed world. Defaults leave sc unchanged.
    runtime = {}
    sc = apply_bins(sc, R.bins, R.intra_amplitude)
    if R.corridors:
        sc, lives, members = add_corridors(sc, prm.life, R.corridor_share)
        prm = replace(prm, life=lives)
        lead = dict(tr.construction_lead)
        for c in members: lead[c] = 1 if w.metadata['state_config']['preparation'] else 0
        tr = replace(tr, construction_lead=lead)
        runtime = {'corridors': members, 'congestion': (R.congestion_threshold, R.congestion_cost)}
    if R.lump_share > 0:
        ref = R.lump_reference * total / len(sc.locations)
        sc = apply_lumps(sc, R.lump_share, ref,
                         include=lambda n, d: (d.kind == 'corridor') or (R.lump_scope == 'all' and d.kind == 'process' and not (R.corridors and n.startswith('T_'))))
    extras = {'corridors': {'members': runtime['corridors'], 'congestion': runtime['congestion']}} if runtime else None
    initial = solve_window(sc, replace(tr, construction_lead={}), prm, 0, 0, [],
                           stocks=w.stocks, time_limit=30., extras=extras)
    history=[]
    for n,x in sorted(initial['epochs'][0]['builds'].items()):
        if x <= 1e-8: continue
        d=sc.designs[n]; life=prm.life[n]
        age=keyed_rng(seed,'initial-age',n).randrange(life)
        history.append(Vintage(n,-age,x,x,d.annual_cost,d.fixed_cost,life))
    rs = w.realizability
    if rs is not None and runtime:
        from techgraph.realizability import DesignRequirement
        # Corridors are shared infrastructure; their readiness is carried by the
        # member transport processes' logistics requirements.
        rs = replace(rs, requirements={**rs.requirements, **{c: DesignRequirement() for c in runtime['corridors']}})
    ready = tuple(sorted({c for v in history for c in rs.requirements[v.design].build + rs.requirements[v.design].operate}))
    until = {c:keyed_rng(seed,'initial-capability-age',c).randint(1,rs.capabilities[c].validity-1) for c in ready}
    rs = replace(rs, initially_ready=ready, initial_ready_until=until)
    # Reference is observed only in the initial one-period allocation; all sites
    # retain local resources. It is not a uniquely endowed source or target hub.
    flow=initial['epochs'][0]['operating_states'][0]['flow']
    resource_use={q.location:sum(flow['resources'][q.name]['rates']) for q in sc.flow_system.resources}
    reference=max(sc.locations, key=lambda l:(resource_use[l], l))
    distance=lambda l:math.dist(sc.coords[l],sc.coords[reference])
    distant=max(sc.locations,key=lambda l:(distance(l),l))
    w.scenario=sc; w.trajectory=tr; w.params=prm; w.history=history; w.realizability=rs
    w.realism_runtime = runtime or None
    if not R.is_default():
        w.metadata['realism'] = asdict(R)
    w.metadata.update(generator='demand-coordinates-v3 over frozen stateful-v2',
        demand='factorized total x service mix x geographic shares',
        demand_base_total=total, demand_forms=forms, initial_service_mix=[.5,.5],
        initial_spatial_shares=[1/len(sc.locations)]*len(sc.locations),
        reference_site=reference, distant_site=distant, initial_resource_use=resource_use,
        reference_separation=distance(distant), initial_solver=initial['solver'])
    validate_flow_system(sc); rs.validate(sc)
    return w

V4_TREATMENTS = ('resource_shift50',)


def prepare(spec):
    from techgraph.realism import RealismConfig
    R = RealismConfig(**{k:(tuple(v) if isinstance(v,list) else v) for k,v in spec.get('realism',{}).items()}).validate()
    from techgraph import backend
    backend.MIP_GAP = 2e-3 if R.lump_share > 0 else 1e-8
    w = make_base(spec['seed'], spec['epochs'], R)
    locs=list(w.scenario.locations)
    treatment = 'constant' if spec['treatment'] in V4_TREATMENTS else spec['treatment']
    c=coordinates(spec['seed'],treatment,spec['epochs'],len(locs),
                  locs.index(w.metadata['reference_site']),locs.index(w.metadata['distant_site']))
    scale={}
    for i in range(2):
        mix = c['mix_a'] if i==0 else 1-c['mix_a']
        for j,loc in enumerate(locs):
            scale[f'need{i}_{loc}']=(c['scale']*mix*c['spatial'][:,j]*2*len(locs)).tolist()
    w.trajectory=replace(w.trajectory,demand_scale=scale)
    if spec['treatment']=='resource_shift50':
        # Raw supply at the reference site declines to half over periods 8-55
        # (scale <= 1, as the audit requires); demand stays constant.
        k=np.arange(spec['epochs']);ramp=np.clip((k-8)/47,0,1)
        ref=w.metadata['reference_site']
        w.trajectory=replace(w.trajectory,resource_scale={q.name:(1-.5*ramp).tolist()
            for q in w.scenario.flow_system.resources if q.location==ref})
    w.metadata['demand_treatment']=spec['treatment']
    w.metadata['demand_coordinates']={k:v.tolist() for k,v in c.items()}
    search=SearchConfig(seed=4000+spec['seed'],use_bias=R.use_bias,variant_share=R.variant_share,adapter_cost=tuple(R.adapter_cost))
    policy=VSRConfig(selection='all',full_archive_access=True,adoption_horizon=spec['horizon'],
                     evaluation_horizon=spec['horizon'],expectations='static',compact_history=True,time_limit=spec.get('time_limit',120. if R.lump_share>0 else 30.),
                     forecast=R.forecast,switching_cost=R.switching_cost,learning_rate=R.learning_rate,
                     learning_reference=R.learning_reference*w.metadata['demand_base_total'])
    return w,search,policy
