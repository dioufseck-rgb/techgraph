from copy import deepcopy
from dataclasses import replace
import pytest
from techgraph.generative import WorldConfig,SearchConfig,RecipeSearch
from techgraph.stateful import StateConfig,make_stateful_world,audit_stateful
from techgraph.dynamic import run_policy,path_objective
from techgraph.vsr import run_vsr,VSRConfig,audit_vsr,serializable_result


def execute(w,search=True,horizon=4):
    return run_vsr(w.scenario,w.trajectory,w.params,w.history,(),
        config=VSRConfig(selection='all' if search else 'none',full_archive_access=True,
            adoption_horizon=horizon,evaluation_horizon=horizon,expectations='static'),
        stocks=w.stocks,realizability=w.realizability,candidate_context=w.candidate_context,
        proposal_source=RecipeSearch(SearchConfig(seed=2000+w.metadata['world_config']['seed'])) if search else None)

@pytest.mark.parametrize('seed',[100,103])
def test_no_search_stateful_vsr_matches_shared_policy(seed):
    w=make_stateful_world(WorldConfig(seed=seed,epochs=8,locations=2,forms=5,extra_recipes=3))
    a=execute(w,False)
    b=run_policy(w.scenario,w.trajectory,w.params,w.history,horizon=4,expectations='static',stocks=w.stocks,realizability=w.realizability)
    assert path_objective(w.trajectory,a['run'])==pytest.approx(path_objective(w.trajectory,b),rel=1e-8)
    assert audit_vsr(a)['passed']
    assert audit_stateful(a)['passed']
    for ea,eb in zip(a['run']['epochs'],b['epochs']):
        for n in ea['stocks']:assert ea['stocks'][n]['stock_end']==pytest.approx(eb['stocks'][n]['stock_end'],abs=1e-7)

@pytest.mark.parametrize('seed',[101,102])
def test_recursive_stateful_history_passes_independent_audits(seed):
    w=make_stateful_world(WorldConfig(seed=seed,epochs=10,locations=2,forms=5,extra_recipes=3))
    r=execute(w)
    assert audit_vsr(r)['passed']
    assert audit_stateful(r)['passed']
    assert len(r['events'])==10
    for n,c in r['lineage'].items():
        for stage in ('build','operate','maintain'):
            expected={x for parent in c['parents'] for x in getattr(r['realizability'].requirements[parent],stage)}
            assert set(getattr(r['realizability'].requirements[n],stage))==expected
    assert serializable_result(r)['audit']['passed']


def test_initialization_does_not_use_future_demand_or_horizon():
    from dataclasses import asdict
    cfg=WorldConfig(seed=104,epochs=8,locations=2,forms=5,extra_recipes=3,demand_volatility=0.)
    a=make_stateful_world(cfg);b=make_stateful_world(replace(cfg,epochs=12,demand_volatility=.25))
    assert asdict(a.scenario)==asdict(b.scenario)
    assert a.history==b.history
    assert a.realizability==b.realizability


def test_inventory_ablation_preserves_recipe_and_proposal_streams():
    wc=WorldConfig(seed=102,epochs=6,locations=2,forms=5,extra_recipes=3)
    a=make_stateful_world(wc);b=make_stateful_world(wc,StateConfig(inventories=False))
    assert a.scenario==b.scenario
    ra=execute(a);rb=execute(b)
    assert ra['lineage']==rb['lineage']
    assert all(s['stock_end']==pytest.approx(0) for e in rb['run']['epochs'] for s in e['stocks'].values())


def test_delays_capability_and_construction_compose_in_vsr():
    from tests.test_realizability import world,spec
    sc,tr,prm=world(K=6,demand=[0,0,0,1,1,1],construction=2)
    r=run_vsr(sc,tr,prm,[],(),config=VSRConfig(selection='none',full_archive_access=True,adoption_horizon=4,expectations='true'),realizability=spec(lead=1,cost=2))
    assert r['run']['epochs'][0]['realizability']['acquired']
    assert r['run']['epochs'][1]['orders']['MAKE']==pytest.approx(10.)
    assert r['run']['epochs'][3]['commissioned']['MAKE']==pytest.approx(10.)
    assert audit_stateful(r)['passed']
    assert audit_vsr(r)['passed']


def test_capability_audit_rejects_fabricated_readiness():
    w=make_stateful_world(WorldConfig(seed=100,epochs=6,locations=2,forms=5,extra_recipes=2))
    r=execute(w,False);bad=deepcopy(r)
    bad['run']['epochs'][0]['realizability']['ready'].append('fabricated')
    with pytest.raises(ValueError,match='readiness'):audit_stateful(bad)


def test_project_audit_rejects_unrecorded_work():
    w=make_stateful_world(WorldConfig(seed=103,epochs=6,locations=2,forms=5,extra_recipes=2))
    r=execute(w,False);bad=deepcopy(r)
    bad['events'][1]['opening']['projects'].append({'bogus':1})
    with pytest.raises(ValueError,match='WIP continuity'):audit_stateful(bad)


def test_all_state_channels_can_be_disabled_without_erasing_knowledge():
    w=make_stateful_world(WorldConfig(seed=101,epochs=6,locations=2,forms=5,extra_recipes=2),StateConfig(False,False,False))
    r=execute(w)
    assert audit_stateful(r)['passed']
    assert r['realizability'] is None
    assert all(v==0 for v in r['trajectory'].construction_lead.values())
    assert len(r['knowledge_final'])>len(w.scenario.designs)
    assert all(not e['projects_after'] for e in r['events'])


def test_scarcity_is_recorded_as_costly_shortfall_not_hidden_failure():
    w=make_stateful_world(WorldConfig(seed=101,epochs=6,locations=2,forms=5,extra_recipes=2,demand_volatility=0),StateConfig(False,False,False,supply_margin=.6))
    r=execute(w,False)
    assert r['run']['status']=='complete'
    unmet=sum(sum(q['unmet_rates']) for e in r['run']['epochs'] for q in e['operating_states'][0]['flow']['demands'].values())
    assert unmet>0
    assert audit_vsr(r)['passed']


def test_stock_continuation_handles_only_solver_scale_roundoff():
    from techgraph.stocks import validate_context
    w=make_stateful_world(WorldConfig(seed=105,epochs=6,locations=2,forms=5,extra_recipes=2))
    state=w.stocks.initial(w.scenario);n=next(iter(state));state[n]=-8.35e-7
    assert validate_context(w.scenario,w.stocks,6,1,state)[n]==0.
    state[n]=-1e-4
    with pytest.raises(ValueError):validate_context(w.scenario,w.stocks,6,1,state)


def test_closed_vintage_compaction_preserves_objective_and_service():
    w=make_stateful_world(WorldConfig(seed=102,epochs=12,locations=2,forms=5,extra_recipes=2))
    def run(compact):
        return run_vsr(w.scenario,w.trajectory,w.params,w.history,(),
            config=VSRConfig(selection='none',full_archive_access=True,adoption_horizon=4,expectations='static',compact_history=compact),
            stocks=w.stocks,realizability=w.realizability,candidate_context=w.candidate_context)
    a,b=run(False),run(True)
    assert audit_vsr(a)['all_in_objective']==pytest.approx(audit_vsr(b)['all_in_objective'],rel=1e-8)
    assert audit_stateful(b)['passed']
    for ea,eb in zip(a['run']['epochs'],b['run']['epochs']):
        for n,q in ea['operating_states'][0]['flow']['demands'].items():
            assert q['delivered_rates']==pytest.approx(eb['operating_states'][0]['flow']['demands'][n]['delivered_rates'])


def test_small_explicit_flow_orders_are_recorded_and_carried():
    from tests.test_generic_core import generic_mass_world
    from techgraph.dynamic import Trajectory,Params
    sc=generic_mass_world()
    sc=replace(sc,flow_system=replace(sc.flow_system,demands=tuple(replace(q,rates=(3e-5,)) for q in sc.flow_system.demands)))
    tr=Trajectory(2,[0.]*2,[1.]*2);prm=Params({'MAKE':4})
    r=run_policy(sc,tr,prm,[],horizon=1)
    assert r['epochs'][0]['builds']['MAKE']==pytest.approx(3e-5)
    assert r['epochs'][1]['capacity']['MAKE']==pytest.approx(3e-5)
    assert not r['epochs'][1]['builds']


def test_long_small_order_regression_passes_lifecycle_audit():
    from run_stateful_campaign import prepare
    w,_,_=prepare({'seed':131,'volatility':0.,'profile':'full','epochs':64,'horizon':4})
    r=execute(w)
    assert audit_stateful(r)['passed']
    assert audit_vsr(r)['passed']


def test_long_inventory_roundoff_regression_passes_stock_audit():
    from run_stateful_campaign import prepare
    w,search,cfg=prepare({'seed':134,'volatility':0.,'profile':'full','epochs':64,'horizon':4})
    r=run_vsr(w.scenario,w.trajectory,w.params,w.history,(),config=cfg,stocks=w.stocks,realizability=w.realizability,
        candidate_context=w.candidate_context,proposal_source=RecipeSearch(search))
    assert audit_stateful(r)['passed']
    assert audit_vsr(r)['passed']
