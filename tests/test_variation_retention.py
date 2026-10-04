"""Historical support-gated tests retained as explicit legacy-control coverage."""
from dataclasses import replace
import copy
import pytest
from techgraph.variation import (MutationRule,RecombinationRule,Candidate,mutate,recombine,
                                validate_candidate,fingerprint,keyed_rng)
from techgraph._vsr_legacy import VSRConfig,run_vsr,audit_vsr
from techgraph.vsr_examples import efficiency_search_world,circular_search_world,complementary_prototypes
from techgraph.flows import Port
from techgraph.dynamic import run_policy,path_objective
from techgraph.need_examples import simple_task_spec


def test_reproducible_keyed_proposals():
    sc,tr,p,h,r,rr,st=efficiency_search_world()
    a=mutate(sc,'OLD',r[0],seed=4,epoch=0,slot=0,life=20)
    b=mutate(sc,'OLD',r[0],seed=4,epoch=0,slot=0,life=20)
    assert a==b
    assert abs(sum(x.coefficient for x in a.design.output_ports)-1)<1e-12


@pytest.mark.parametrize('seed',range(8))
def test_mutation_preserves_declared_recipe(seed):
    sc,tr,p,h,r,rr,st=circular_search_world()
    try:c=mutate(sc,'RECOVER',r[1],seed=seed,epoch=1,slot=0,life=20)
    except ValueError as exc:
        assert 'envelope' in str(exc);return
    assert sum(x.coefficient for x in c.design.output_ports)==pytest.approx(1.)
    assert validate_candidate(sc,c)


def test_invalid_mass_creation_rejected():
    sc,tr,p,h,r,rr,st=circular_search_world()
    d=replace(sc.designs['OLD'],name='bad',output_ports=(Port('product','D',1.),Port('residue','D',.3)))
    with pytest.raises(ValueError):validate_candidate(sc,Candidate(d,'production',('OLD',),'test',0,0,20,{}))


def test_seed_bounds_not_reset_each_generation():
    sc,tr,p,h,r,rr,st=efficiency_search_world()
    expensive=replace(sc.designs['OLD'],name='expensive',annual_cost=sc.designs['OLD'].annual_cost*2.99)
    sc=replace(sc,designs={**sc.designs,'expensive':expensive})
    rule=replace(r[0],cost_log_sigma=0,cost_log_drift=1.,output_pair=None)
    with pytest.raises(ValueError,match='envelope'):mutate(sc,'expensive',rule,seed=0,epoch=0,slot=0,life=20)


def test_name_does_not_change_recipe_fingerprint():
    sc,*_=efficiency_search_world()
    assert fingerprint(sc.designs['OLD'])==fingerprint(replace(sc.designs['OLD'],name='other'))


def test_serial_recombination_preserves_external_mass():
    sc,tr,p,h,r,rr,st=circular_search_world()
    c=recombine(sc,'OLD','RECOVER',replace(rr[0],cost_factor_bounds=(1.,1.)),seed=1,epoch=0,slot=0,lives=p.life)
    outputs={p.form:p.coefficient for p in c.design.output_ports}
    assert outputs['product']==pytest.approx(.9)
    assert outputs['inert']==pytest.approx(.1)
    assert 'residue' not in outputs
    assert c.design.var_cost==pytest.approx(sc.designs['OLD'].var_cost+.2*sc.designs['RECOVER'].var_cost)
    assert c.life==min(p.life['OLD'],p.life['RECOVER'])


@pytest.mark.parametrize('form,loc',[('residue','elsewhere'),('product','D'),('fuel','D')])
def test_recombination_requires_matching_port(form,loc):
    sc,tr,p,h,r,rr,st=circular_search_world()
    with pytest.raises(ValueError):recombine(sc,'OLD','RECOVER',replace(rr[0],form=form,location=loc),seed=0,epoch=0,slot=0,lives=p.life)


@pytest.mark.parametrize('mode',['individual','portfolio','all','random','none'])
def test_vsr_energy_physical_and_cost_audit(mode):
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection=mode,seed=4),stocks=st)
    assert audit_vsr(z)['passed']
    if mode=='none':assert not z['lineage']


@pytest.mark.parametrize('quality',[False,True])
@pytest.mark.parametrize('hz',[1,3])
def test_vsr_stocks_and_attributes(quality,hz):
    sc,tr,p,h,r,rr,st=circular_search_world(K=4,quality=quality)
    z=run_vsr(sc,tr,p,h,r,recombination_rules=rr,stocks=st,
               config=VSRConfig(seed=5,evaluation_horizon=hz,adoption_horizon=hz,selection='portfolio'))
    assert audit_vsr(z)['passed']


def test_no_variation_recovers_rolling_policy():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=4)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection='none',adoption_horizon=3))
    baseline=run_policy(sc,tr,p,h,horizon=3)
    assert audit_vsr(z)['path_objective']==pytest.approx(path_objective(tr,baseline))


def test_individual_filter_discards_complements():
    sc,tr,p,h,r,schedule=complementary_prototypes()
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates=schedule,config=VSRConfig(selection='individual'))
    assert z['events'][0]['retained']==[]
    assert all(abs(t['architectural_value'])<1e-8 for t in z['events'][0]['trials'])


def test_portfolio_recovers_complements():
    sc,tr,p,h,r,schedule=complementary_prototypes()
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates=schedule,config=VSRConfig(selection='portfolio'))
    assert set(z['events'][0]['retained'])=={'PROTO_REMOTE','PROTO_LINE'}
    assert z['run']['epochs'][0]['throughput']['PROTO_REMOTE']>1
    assert audit_vsr(z)['passed']


@pytest.mark.parametrize('memory,expect',[ (0,False),(1,True),(2,True)])
def test_prototype_memory_can_preserve_delayed_complement(memory,expect):
    sc,tr,p,h,r,schedule=complementary_prototypes(delay=True)
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates=schedule,
              config=VSRConfig(selection='portfolio',prototype_memory=memory,max_trials_per_epoch=100))
    assert bool(z['lineage'])==expect
    assert audit_vsr(z)['passed']


def test_dictionary_order_does_not_change_results():
    sc,tr,p,h,r,rr,st=circular_search_world(K=3)
    cfg=VSRConfig(seed=8,selection='portfolio',parent_pool='seeds')
    a=run_vsr(sc,tr,p,h,r,recombination_rules=rr,stocks=st,config=cfg)
    b=run_vsr(replace(sc,designs=dict(reversed(list(sc.designs.items())))),tr,p,h,tuple(reversed(r)),
              recombination_rules=rr,stocks=st,config=cfg)
    assert [e['proposals'] for e in a['events']]==[e['proposals'] for e in b['events']]
    assert audit_vsr(a)['path_objective']==pytest.approx(audit_vsr(b)['path_objective'])


def test_seed_only_controls_match_candidates_across_selection_rules():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    a=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection='all',parent_pool='seeds',seed=8))
    b=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection='individual',parent_pool='seeds',seed=8))
    aa=[[p.get('candidate') for p in e['proposals']] for e in a['events']]
    bb=[[p.get('candidate') for p in e['proposals']] for e in b['events']]
    assert aa==bb


def test_expiry_never_removes_installed_assets():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=4)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection='all',support_patience=0,seed=8))
    assert audit_vsr(z)['passed']
    assert any(e['support_expired'] for e in z['events'])


def test_supported_does_not_mean_used():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=4)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection='all',seed=8))
    a=audit_vsr(z)
    assert a['supported_never_used']>0


@pytest.mark.parametrize('effort',[0.,1.])
def test_variant_uses_explicit_task_engine(effort):
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    spec=simple_task_spec(sc,effort_capacity=2.)
    z=run_vsr(sc,tr,p,h,r,integration=spec,config=VSRConfig(seed=4,new_task_effort=effort))
    assert audit_vsr(z)['passed']


def test_charges_are_separate_from_operating_objective():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(seed=4,evaluation_cost=.2,support_cost=.3))
    a=audit_vsr(z)
    assert a['research_cost']>0
    assert a['all_in_objective']==pytest.approx(a['path_objective']+a['research_cost'])


def test_fabricated_trial_value_rejected():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(seed=4))
    z['events'][0]['trials'][0]['architectural_value']+=100
    with pytest.raises(ValueError,match='Bad trial'):audit_vsr(z)


@pytest.mark.parametrize('kw',[{'selection':'unknown'},{'evaluation_horizon':0},{'adoption_horizon':0},
                               {'sightedness':1.1},{'prototype_memory':-1},{'support_patience':-1},
                               {'evaluation_cost':-1},{'recombination_share':2},{'max_portfolio':5}])
def test_invalid_vsr_configuration(kw):
    with pytest.raises(ValueError):VSRConfig(**kw).validate()


def test_trial_horizon_can_preserve_future_attribute_opportunity():
    sc,tr,p,h,r,rr,st=circular_search_world(K=4,quality=True)
    d=replace(sc.designs['UPGRADE'],name='PROMISING',var_cost=.01)
    c=Candidate(d,'upgrade',('UPGRADE',),'scheduled_prototype',0,0,20,{})
    short=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[c]},config=VSRConfig(evaluation_horizon=1))
    long=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[c]},config=VSRConfig(evaluation_horizon=3))
    assert short['events'][0]['retained']==[]
    assert long['events'][0]['retained']==['PROMISING']
    assert 'PROMISING' not in long['events'][0]['used']
    assert audit_vsr(long)['all_in_objective']<audit_vsr(short)['all_in_objective']


def test_same_epoch_proposals_never_become_each_others_parents():
    sc,tr,p,h,r,rr,st=circular_search_world(K=5)
    z=run_vsr(sc,tr,p,h,r,recombination_rules=rr,stocks=st,config=VSRConfig(selection='all',seed=5))
    dates={n:c['epoch'] for n,c in z['lineage'].items()}
    for n,c in z['lineage'].items():
        assert all(parent not in dates or dates[parent]<c['epoch'] for parent in c['parents'])
    assert any(parent in dates for c in z['lineage'].values() for parent in c['parents'])


def test_rejected_prototypes_never_used_as_parents():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=4)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(support_hurdle=1e10,seed=5))
    assert not z['lineage']
    assert all(c['candidate']['parents']==('OLD',) for e in z['events'] for c in e['proposals'] if c['status']=='feasible')


def test_high_trial_cost_can_erase_realized_saving():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(evaluation_cost=1e5,seed=5))
    assert audit_vsr(z)['all_in_objective']>audit_vsr(z)['path_objective']


def test_invalid_generated_proposals_are_not_resampled_away():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=2)
    rule=replace(r[0],cost_log_sigma=0.,cost_log_drift=5.)
    z=run_vsr(sc,tr,p,h,(rule,),config=VSRConfig(proposals_per_epoch=3))
    assert sum(len(e['proposals']) for e in z['events'])==6
    assert all(c['status']=='invalid' for e in z['events'] for c in e['proposals'])
    assert not z['lineage']


def test_zero_search_budget_matches_no_variation():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    a=run_vsr(sc,tr,p,h,r,config=VSRConfig(proposals_per_epoch=0))
    b=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection='none'))
    assert audit_vsr(a)['path_objective']==pytest.approx(audit_vsr(b)['path_objective'])


def test_trial_portfolio_budget_fails_explicitly():
    sc,tr,p,h,r,schedule=complementary_prototypes()
    with pytest.raises(ValueError,match='Trial budget'):
        run_vsr(sc,tr,p,h,r,scheduled_candidates=schedule,config=VSRConfig(selection='portfolio',max_trials_per_epoch=1))


def test_admission_accounts_for_support_fee_not_only_later_reporting():
    sc,tr,p,h,r,schedule=complementary_prototypes()
    free=run_vsr(sc,tr,p,h,r,scheduled_candidates=schedule,config=VSRConfig(selection='portfolio'))
    expensive=run_vsr(sc,tr,p,h,r,scheduled_candidates=schedule,
        config=VSRConfig(selection='portfolio',support_cost=1e8))
    assert len(free['lineage'])==2
    assert not expensive['lineage']
    assert audit_vsr(expensive)['support_expired']==0


def test_unknown_parents_cannot_seed_unsupported_new_form():
    sc,tr,p,h,r,rr,st=efficiency_search_world()
    c=Candidate(replace(sc.designs['OLD'],name='invented'),'generation',(),'test',0,0,20,{})
    with pytest.raises(ValueError):validate_candidate(sc,c)


@pytest.mark.parametrize('bounds',[(.1,float('inf')),(0,1),(2,1)])
def test_unbounded_or_reversed_feasibility_envelope_rejected(bounds):
    sc,tr,p,h,r,rr,st=efficiency_search_world()
    with pytest.raises(ValueError):replace(r[0],cost_bounds=bounds).validate(sc)
