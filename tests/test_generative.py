from dataclasses import replace
import copy
import pytest
from techgraph.generative import WorldConfig,SearchConfig,RecipeSearch,make_generative_world
from techgraph.flows import validate_flow_system
from techgraph.vsr import VSRConfig,run_vsr,audit_vsr
from techgraph.dynamic import run_policy,path_objective
from techgraph.variation import recombine,RecombinationRule


@pytest.mark.parametrize('seed',range(5))
def test_generated_world_is_balanced_and_initially_service_feasible(seed):
    w=make_generative_world(WorldConfig(seed=seed,epochs=8,locations=2,forms=5,extra_recipes=4))
    validate_flow_system(w.scenario)
    assert w.metadata['initial_solver']['status']=='Optimal'
    assert w.history and not w.trajectory.avail_from and not w.trajectory.avail_until
    for d in w.scenario.designs.values():
        if d.kind=='process':
            assert sum(p.coefficient for p in d.input_ports)==pytest.approx(sum(p.coefficient for p in d.output_ports))
    assert all(0<=-v.built<v.life for v in w.history)


def test_world_randomness_separates_initial_state_from_future_process():
    a=make_generative_world(WorldConfig(seed=4,epochs=8,locations=2,demand_volatility=0))
    b=make_generative_world(WorldConfig(seed=4,epochs=8,locations=2,demand_volatility=.25))
    assert a.scenario.designs==b.scenario.designs and a.history==b.history
    assert a.trajectory.demand_scale!=b.trajectory.demand_scale


def test_factorization_is_balanced_and_recomposes_to_the_parent_interface():
    w=make_generative_world(WorldConfig(epochs=4,locations=2,forms=4,extra_recipes=1))
    cfg=SearchConfig(seed=3,mean_attempts=30,max_attempts=1,mutation_share=0,composition_share=0,factorization_share=1,composition_factor=(1,1))
    batch=RecipeSearch(cfg).propose(w.scenario,w.params.life,frozenset(w.scenario.designs),0,{})
    assert len(batch.forms)==1 and len(batch.candidates)==2
    a,b=batch.candidates;parent=w.scenario.designs[a.parents[0]]
    sc=replace(w.scenario,designs={**w.scenario.designs,a.design.name:a.design,b.design.name:b.design},
               flow_system=replace(w.scenario.flow_system,form_units={**w.scenario.flow_system.form_units,**batch.forms}))
    validate_flow_system(sc)
    inter=next(iter(batch.forms));loc=a.design.output_ports[0].location
    combined=recombine(sc,a.design.name,b.design.name,RecombinationRule('x','x','x',inter,loc,(1,1)),seed=1,epoch=1,slot=0,
                       lives={**w.params.life,a.design.name:a.life,b.design.name:b.life})
    assert sorted(combined.design.input_ports,key=repr)==sorted(parent.input_ports,key=repr)
    assert sorted(combined.design.output_ports,key=repr)==sorted(parent.output_ports,key=repr)
    assert combined.design.annual_cost==pytest.approx(parent.annual_cost)
    assert combined.design.var_cost==pytest.approx(parent.var_cost)


def test_no_search_recovers_the_same_static_expectations_policy():
    w=make_generative_world(WorldConfig(seed=3,epochs=6,locations=2,forms=4,extra_recipes=2))
    cfg=VSRConfig(selection='none',full_archive_access=True,expectations='static',adoption_horizon=3)
    result=run_vsr(w.scenario,w.trajectory,w.params,w.history,(),config=cfg,proposal_source=RecipeSearch())
    baseline=run_policy(w.scenario,w.trajectory,w.params,w.history,horizon=3,expectations='static')
    assert audit_vsr(result)['path_objective']==pytest.approx(path_objective(w.trajectory,baseline))
    assert result['research_cost']==0 and not result['lineage']


def test_recursive_search_retains_knowledge_and_can_create_intermediates():
    w=make_generative_world(WorldConfig(seed=1,epochs=8,locations=2,forms=4,extra_recipes=2))
    cfg=VSRConfig(full_archive_access=True,expectations='static',adoption_horizon=2)
    source=RecipeSearch(SearchConfig(seed=6,mean_attempts=3,mutation_share=.2,composition_share=.3,factorization_share=.4))
    result=run_vsr(w.scenario,w.trajectory,w.params,w.history,(),config=cfg,proposal_source=source)
    assert audit_vsr(result)['passed']
    assert result['proposal_cost']>0 and result['research_cost']==pytest.approx(result['proposal_cost'])
    assert len(result['scenario'].flow_system.form_units)>len(w.scenario.flow_system.form_units)
    assert any(c['metadata']['generation']>1 for c in result['lineage'].values())
    known=set(w.scenario.designs)
    for e in result['events']:
        assert set(e['opening']['knowledge'])==known
        for c in e['proposals']:
            if c['status']=='feasible':assert set(c['candidate']['parents'])<=known
        known.update(e['knowledge_added'])
    assert set(result['knowledge_final'])==known


def test_source_order_invariance_and_no_input_mutation():
    w=make_generative_world(WorldConfig(seed=2,epochs=4,locations=2,forms=4,extra_recipes=2))
    snapshot=copy.deepcopy(w.scenario);cfg=SearchConfig(seed=9,mean_attempts=4)
    a=RecipeSearch(cfg).propose(w.scenario,w.params.life,frozenset(w.scenario.designs),0,{})
    sc=replace(w.scenario,designs=dict(reversed(list(w.scenario.designs.items()))))
    b=RecipeSearch(cfg).propose(sc,w.params.life,frozenset(sc.designs),0,{})
    assert a==b and w.scenario==snapshot


def test_generation_limit_records_rejections_without_resampling():
    w=make_generative_world(WorldConfig(epochs=4,locations=2,forms=4,extra_recipes=1))
    source=RecipeSearch(SearchConfig(seed=4,mean_attempts=50,max_attempts=2,mutation_share=1,composition_share=0,factorization_share=0,max_generation=1))
    source.generation={n:1 for n in w.scenario.designs}
    b=source.propose(w.scenario,w.params.life,frozenset(w.scenario.designs),0,{})
    assert not b.candidates and len(b.attempts)==2 and b.charge==pytest.approx(.02)
    assert all(x['reason']=='generation_envelope' for x in b.attempts)


def test_generated_and_scheduled_sources_cannot_mix():
    w=make_generative_world(WorldConfig(epochs=3,locations=2,forms=4))
    with pytest.raises(ValueError,match='cannot be mixed'):
        run_vsr(w.scenario,w.trajectory,w.params,w.history,(),proposal_source=RecipeSearch(),scheduled_candidates={})


def test_tampered_proposal_charges_are_rejected():
    w=make_generative_world(WorldConfig(epochs=3,locations=2,forms=4,extra_recipes=0))
    r=run_vsr(w.scenario,w.trajectory,w.params,w.history,(),config=VSRConfig(full_archive_access=True),proposal_source=RecipeSearch())
    r['events'][0]['proposal_charge']+=1
    with pytest.raises(ValueError,match='proposal effort'):audit_vsr(r)
