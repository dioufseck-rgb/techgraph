from dataclasses import replace,asdict
import pytest
from techgraph.network_worlds import make_network_world,quality_shock,EXTRA_ROLES
from techgraph.network_experiments import execute,audit_execution,measures,footprint
from techgraph.dynamic import run_policy,path_cost
from techgraph.model import solve,check_balances
from techgraph.flows import validate_flow_system

@pytest.mark.parametrize('n',[2,3,6,12,24])
def test_generated_recipes_and_nested_opportunities(n):
    ws=[make_network_world(n,7,c) for c in ['separated','sparse','rich']]
    for w in ws:validate_flow_system(w.scenario)
    assert all(asdict(w.scenario)==asdict(ws[0].scenario) for w in ws)
    assert all(w.history==ws[0].history and w.stocks==ws[0].stocks for w in ws)
    assert set(ws[2].forbid)<=set(ws[1].forbid)<=set(ws[0].forbid)
    assert len(ws[0].metadata['tree_edges'])==n-1
    assert len(ws[0].scenario.flow_system.demands)==2*n

@pytest.mark.parametrize('n',[2,3,6])
def test_deterministic_generation(n):
    assert make_network_world(n,12).manifest()==make_network_world(n,12).manifest()
    assert make_network_world(n,12).metadata['traits']!=make_network_world(n,13).metadata['traits']

@pytest.mark.parametrize('connectivity',['separated','sparse','rich'])
def test_initial_incumbent_can_supply_every_service_without_investment(connectivity):
    w=make_network_world(3,3,connectivity,K=1)
    cap={n:sum(v.alive for v in w.history if v.design==n) for n in w.scenario.designs}
    r=solve(w.scenario,[],existing=cap,fixed=True,stocks=w.stocks)
    assert r.status=='Optimal' and not check_balances(w.scenario,r)

@pytest.mark.parametrize('mode',['separated','sparse','rich'])
def test_static_dynamic_equivalence_without_history(mode):
    w=make_network_world(2,2,mode,K=1)
    sc=w.scenario
    a=solve(sc,[n for n in sc.designs if n not in w.forbid],stocks=w.stocks)
    b=execute(replace(w,history=[]),99)
    assert a.objective==pytest.approx(path_cost(w.trajectory,b),rel=1e-8)
    assert audit_execution(replace(w,history=[]),b)['passed']

@pytest.mark.parametrize('horizon',[1,2,99])
def test_runner_matches_common_engine(horizon):
    w=make_network_world(2,1,K=4)
    a=run_policy(w.scenario,w.trajectory,w.params,w.history,horizon=horizon,stocks=w.stocks,forbid=w.forbid)
    b=execute(w,horizon)
    assert path_cost(w.trajectory,a)==pytest.approx(path_cost(w.trajectory,b),rel=1e-9)
    assert audit_execution(w,b)['passed']

@pytest.mark.parametrize('seed',[0,1,2])
def test_nested_full_horizon_ordering(seed):
    costs=[]
    for c in ['separated','sparse','rich']:
        w=make_network_world(3,seed,c,K=3);r=execute(w,99)
        assert audit_execution(w,r)['passed'];costs.append(path_cost(w.trajectory,r))
    assert costs[2]<=costs[1]+1e-6<=costs[0]+2e-6

@pytest.mark.parametrize('hz',[1,99])
def test_no_event_branch_reproduces_continuation_and_past(hz):
    w=make_network_world(3,0,K=4);r=execute(w,hz)
    b=execute(w,hz,start=2,prefix=r)
    assert b['epochs'][:2]==r['epochs'][:2]
    assert path_cost(w.trajectory,b)==pytest.approx(path_cost(w.trajectory,r),rel=1e-8)
    assert audit_execution(w,b)['passed']

@pytest.mark.parametrize('hz',[1,99])
def test_quality_branch_no_foresight_of_event(hz):
    w=make_network_world(3,2,K=4);r=execute(w,hz)
    event=quality_shock(w,0,2);b=execute(event,hz,start=2,prefix=r)
    assert b['epochs'][:2]==r['epochs'][:2]
    assert audit_execution(event,b,prefix_world=w)['passed']
    assert event.scenario.flow_system==w.scenario.flow_system
    assert event.scenario.designs==w.scenario.designs

@pytest.mark.parametrize('kind',['loss','exclude'])
def test_loss_and_exclusion_preserve_past_and_accounting(kind):
    w=make_network_world(3,1,K=4);r=execute(w,1)
    name=max((n for n in r['epochs'][1]['capacity'] if w.metadata['module_roles'][n]['role']=='REFINE'),
             key=lambda n:r['epochs'][1]['capacity'][n])
    kw={'remove':(name,)} if kind=='loss' else {'exclude':(name,)}
    b=execute(w,99,start=2,prefix=r,**kw)
    assert b['epochs'][:2]==r['epochs'][:2]
    assert audit_execution(w,b)['passed']
    if kind=='exclude':assert all(e['capacity'].get(name,0)<1e-8 for e in b['epochs'][2:])

@pytest.mark.parametrize('seed',[0,1])
def test_full_horizon_loss_cheaper_than_permanent_exclusion(seed):
    w=make_network_world(3,seed,K=4);r=execute(w,1);n='REFINE_D'
    loss=execute(w,99,start=2,prefix=r,remove=(n,));exc=execute(w,99,start=2,prefix=r,exclude=(n,))
    assert path_cost(w.trajectory,loss)<=path_cost(w.trajectory,exc)+1e-6

@pytest.mark.parametrize('budget',[1.,3.,None])
def test_integration_and_stock_interoperability(budget):
    w=make_network_world(2,0,K=3,enable_integration=True,integration_budget=budget)
    r=execute(w,1)
    assert audit_execution(w,r)['passed']
    if budget is not None:
        assert all(e['integration']['effort']<=budget+1e-8 for e in r['epochs'])

@pytest.mark.parametrize('fixed',[0.,.2])
def test_explicit_link_lumps(fixed):
    w=make_network_world(2,2,K=2,link_fixed_charge=fixed);r=execute(w,99)
    assert audit_execution(w,r)['passed']
    assert any(s['integer_variables']>0 for s in r['solver_log'])==(fixed>0)


def test_separated_shock_stays_local():
    w=make_network_world(3,2,'separated',K=4);r=execute(w,1)
    event=quality_shock(w,0,2);b=execute(event,1,start=2,prefix=r)
    f=footprint(w,r,b,start=2)
    assert f['other_sites_over_2pct']==0

@pytest.mark.parametrize('args',[{'n_sites':1},{'connectivity':'bogus'},{'alternatives':'bogus'},
                                 {'residual_capacity':-1},{'link_fixed_charge':-1}])
def test_bad_generation_parameters(args):
    with pytest.raises(ValueError):make_network_world(**args)


def test_tampered_supply_fails_independent_audit():
    w=make_network_world(2,0,K=2);r=execute(w,1)
    state=r['epochs'][0]['operating_states'][0]
    first=next(n for n,x in state['physical']['activities'].items() if sum(x.get('activity',[]))>1e-4)
    state['physical']['activities'][first]['activity'][0]+=2
    with pytest.raises(AssertionError):audit_execution(w,r)


def test_numerical_stock_carry_tolerance():
    from techgraph.network_experiments import carry_inventory
    assert carry_inventory({'pile':{'stock_end':-1e-14}})=={'pile':0.}
    with pytest.raises(ValueError):carry_inventory({'pile':{'stock_end':-1e-4}})

def test_full_horizon_branch_handles_tiny_inventory_undershoot():
    w=make_network_world(6,0);r=execute(w,99)
    event=quality_shock(w,0,3);b=execute(event,99,start=3,prefix=r)
    assert audit_execution(event,b,prefix_world=w)['passed']

@pytest.mark.parametrize('con',['separated','rich'])
def test_persistent_vsr_runs_on_generated_network(con):
    from run_network_vsr_probe import inputs
    from techgraph.vsr import VSRConfig,run_vsr,audit_vsr
    w,sc,p,rules,recomb=inputs(2,con,K=2)
    r=run_vsr(sc,w.trajectory,p,w.history,rules,recombination_rules=recomb,stocks=w.stocks,
              config=VSRConfig(seed=7,parent_pool='seeds',proposals_per_epoch=2))
    assert audit_vsr(r)['passed']
    assert all(set(e['opening']['knowledge'])<=set(e['knowledge_after']) for e in r['events'])


def test_matched_network_proposals_do_not_depend_on_adoption():
    from run_network_vsr_probe import inputs
    from techgraph.vsr import VSRConfig,run_vsr
    signatures=[]
    for c in ['separated','rich']:
        w,sc,p,rules,recomb=inputs(2,c,K=2)
        r=run_vsr(sc,w.trajectory,p,w.history,rules,recombination_rules=recomb,stocks=w.stocks,
                  config=VSRConfig(seed=7,parent_pool='seeds',proposals_per_epoch=2))
        signatures.append([[p.get('candidate') for p in e['proposals']] for e in r['events']])
    assert signatures[0]==signatures[1]


def test_network_reference_capacities_convert_without_changing_solution():
    from techgraph.representation import capacity_inputs
    from techgraph.integration import run_integrated_policy
    w=make_network_world(2,0,K=2,enable_integration=True,integration_budget=2.)
    a=run_integrated_policy(w.scenario,w.trajectory,w.params,w.history,w.integration,
                            horizon=1,stocks=w.stocks,forbid=w.forbid)
    units={n:'kg/h' for n in w.scenario.designs}
    sc,h=capacity_inputs(w.scenario,w.history,units,encode=True)
    b=run_integrated_policy(sc,w.trajectory,w.params,h,w.integration,horizon=1,stocks=w.stocks,
                            forbid=w.forbid,capacity_units=units)
    assert path_cost(w.trajectory,a)==pytest.approx(path_cost(w.trajectory,b),rel=1e-8)
