"""The correction must preserve knowledge, not merely rename support expiry."""
from dataclasses import replace
import copy
import pytest
from techgraph.vsr import VSRConfig,run_vsr,audit_vsr
from techgraph.variation import Candidate,mutate
from techgraph.vsr_examples import complementary_prototypes,efficiency_search_world,circular_search_world
from techgraph.dynamic import run_policy,path_objective
from techgraph.need_examples import simple_task_spec


def run_energy(cfg,K=5):
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=K)
    return run_vsr(sc,tr,p,h,r,config=cfg)


def proposals(z):
    return [[p.get('candidate') for p in e['proposals']] for e in z['events']]


def test_default_is_persistent_knowledge_parenthood():
    c=VSRConfig()
    assert c.knowledge_mode=='persistent' and c.parent_pool=='knowledge' and c.retrieval=='archive'


@pytest.mark.parametrize('mode',['individual','portfolio','random','all','none'])
def test_lifecycle_and_physics(mode):
    z=run_energy(VSRConfig(selection=mode,seed=4,max_trials_per_epoch=500))
    assert audit_vsr(z)['passed']
    counts=[len(e['knowledge_after']) for e in z['events']]
    assert counts==sorted(counts)


def test_rejection_is_not_forgetting_or_blocked_parenthood():
    z=run_energy(VSRConfig(seed=5,support_hurdle=1e10))
    assert not z['admissions'] and z['knowledge_archive']
    assert any(parent in z['knowledge_archive'] for c in z['knowledge_archive'].values() for parent in c['parents'])
    assert audit_vsr(z)['known_never_considered']==len(z['knowledge_archive'])


@pytest.mark.parametrize('memory',[0,1,2])
def test_delayed_complement_no_longer_depends_on_prototype_expiry(memory):
    sc,tr,p,h,r,scheduled=complementary_prototypes(delay=True)
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates=scheduled,
              config=VSRConfig(selection='portfolio',prototype_memory=memory))
    assert set(z['events'][1]['retained'])=={'PROTO_LINE','PROTO_REMOTE'}
    assert z['run']['epochs'][1]['throughput']['PROTO_REMOTE']>1
    assert all(not e['prototype_expired'] for e in z['events'])
    assert audit_vsr(z)['passed']


def test_recent_attention_can_miss_combination_without_losing_knowledge():
    sc,tr,p,h,r,scheduled=complementary_prototypes(delay=True)
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates=scheduled,
              config=VSRConfig(selection='portfolio',retrieval='recent',prototype_memory=0))
    assert not z['admissions']
    assert set(z['knowledge_archive'])=={'PROTO_LINE','PROTO_REMOTE'}
    assert audit_vsr(z)['passed']


def test_full_archive_optimizer_finds_pair_without_individual_admission():
    sc,tr,p,h,r,scheduled=complementary_prototypes()
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates=scheduled,
              config=VSRConfig(selection='individual',full_archive_access=True))
    assert z['events'][0]['trials']==[]
    assert z['run']['epochs'][0]['throughput']['PROTO_REMOTE']>1
    assert audit_vsr(z)['passed']


def test_current_evaluator_can_recall_future_useful_knowledge():
    sc,tr,p,h,r,rr,st=circular_search_world(K=4,quality=True)
    c=Candidate(replace(sc.designs['UPGRADE'],name='DORMANT',var_cost=.01),
                'upgrade',('UPGRADE',),'scheduled_prototype',0,0,20,{})
    a=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[c]},config=VSRConfig(evaluation_horizon=1))
    b=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[c]},config=VSRConfig(evaluation_horizon=3))
    assert not a['events'][0]['retained']
    assert b['events'][0]['retained']==['DORMANT']
    assert a['events'][2]['retained']==['DORMANT']
    assert audit_vsr(a)['path_objective']==pytest.approx(audit_vsr(b)['path_objective'])


def test_proposal_stream_uses_knowledge_not_economic_acceptance():
    a=run_energy(VSRConfig(seed=3,selection='all'))
    b=run_energy(VSRConfig(seed=3,support_hurdle=1e10))
    assert proposals(a)==proposals(b)
    assert set(a['knowledge_archive'])==set(b['knowledge_archive'])
    assert len(a['admissions'])>len(b['admissions'])


def test_proposals_match_with_common_parent_pool_across_policy_horizons():
    a=run_energy(VSRConfig(seed=8,evaluation_horizon=1))
    b=run_energy(VSRConfig(seed=8,evaluation_horizon=3,selection='portfolio',max_trials_per_epoch=1000))
    assert proposals(a)==proposals(b)


def test_seed_only_is_search_control_not_lost_archive():
    z=run_energy(VSRConfig(seed=5,parent_pool='seeds',support_hurdle=1e10))
    assert z['knowledge_archive'] and not z['admissions']
    assert all(c['parents']==('OLD',) for c in z['knowledge_archive'].values())


def test_no_same_epoch_parent_even_when_scheduled():
    sc,tr,p,h,r,s=complementary_prototypes()
    a=s[0][0];b=replace(s[0][1],parents=(a.design.name,))
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[a,b]},config=VSRConfig(selection='all'))
    assert b.design.name not in z['knowledge_archive']
    assert any(q['status']=='invalid' for q in z['events'][0]['proposals'])


def test_scheduled_descendant_of_never_considered_parent():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    a=mutate(sc,'OLD',r[0],seed=2,epoch=0,slot=0,life=20,name='DORMANT')
    augmented=replace(sc,designs={**sc.designs,'DORMANT':a.design})
    b=mutate(augmented,'DORMANT',r[0],seed=3,epoch=1,slot=0,life=20,name='CHILD')
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[a],1:[b]},config=VSRConfig(support_hurdle=1e10))
    assert 'CHILD' in z['knowledge_archive'] and not z['admissions']
    assert audit_vsr(z)['passed']


def test_support_expiry_keeps_recipe_and_can_readmit():
    sc,tr,p,h,r,rr,st=circular_search_world(K=4,quality=True)
    c=Candidate(replace(sc.designs['UPGRADE'],name='DORMANT',var_cost=.01),
                'upgrade',('UPGRADE',),'scheduled_prototype',0,0,20,{})
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[c]},config=VSRConfig(selection='all',support_patience=0,support_cost=.01))
    assert z['events'][1]['support_expired']==['DORMANT']
    assert 'DORMANT' in z['events'][1]['knowledge_after']
    assert len(z['admissions']['DORMANT'])>1
    assert audit_vsr(z)['passed']


def test_unknown_parent_not_invented_by_label():
    sc,tr,p,h,r,s=complementary_prototypes()
    c=replace(s[0][0],parents=('NONEXISTENT',))
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[c]},config=VSRConfig(selection='all'))
    assert c.design.name not in z['knowledge_archive']


def test_invalid_physics_not_promoted_to_knowledge():
    sc,tr,p,h,r,s=complementary_prototypes()
    c=replace(s[0][0],design=replace(s[0][0].design,annual_cost=-1))
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[c]},config=VSRConfig(selection='all'))
    assert not z['knowledge_archive']
    assert z['events'][0]['proposals'][0]['status']=='invalid'


def test_archive_does_not_duplicate_rediscovered_recipe():
    sc,tr,p,h,r,s=complementary_prototypes()
    a=s[0][0];b=replace(a,design=replace(a.design,name='RENAMED'),epoch=1)
    z=run_vsr(sc,tr,p,h,r,scheduled_candidates={0:[a],1:[b]},config=VSRConfig(support_hurdle=1e10))
    assert list(z['knowledge_archive'])==[a.design.name]
    assert z['events'][1]['proposals'][0]['status']=='duplicate'


def test_trial_budget_defers_work_not_knowledge():
    z=run_energy(VSRConfig(seed=5,proposals_per_epoch=4,max_trials_per_epoch=1,selection='portfolio'))
    assert any(e.get('trials_deferred',0)>0 for e in z['events'])
    assert all(len(e['trials'])<=1 for e in z['events'])
    assert audit_vsr(z)['passed']


@pytest.mark.parametrize('quality',[False,True])
@pytest.mark.parametrize('mode',['individual','portfolio'])
def test_stock_quality_interoperability(quality,mode):
    sc,tr,p,h,r,rr,st=circular_search_world(K=4,quality=quality)
    z=run_vsr(sc,tr,p,h,r,recombination_rules=rr,stocks=st,
        config=VSRConfig(seed=6,selection=mode,max_trials_per_epoch=1000))
    assert audit_vsr(z)['passed']


@pytest.mark.parametrize('effort',[0.,1.])
def test_task_interoperability(effort):
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    z=run_vsr(sc,tr,p,h,r,integration=simple_task_spec(sc,effort_capacity=2),
              config=VSRConfig(seed=3,new_task_effort=effort))
    assert audit_vsr(z)['passed']


def test_disabled_vsr_recovers_physical_run():
    sc,tr,p,h,r,rr,st=efficiency_search_world(K=3)
    z=run_vsr(sc,tr,p,h,r,config=VSRConfig(selection='none'))
    b=run_policy(sc,tr,p,h,horizon=1)
    assert not z['knowledge_archive']
    assert audit_vsr(z)['path_objective']==pytest.approx(path_objective(tr,b))


@pytest.mark.parametrize('kw',[{'knowledge_mode':'no'},{'retrieval':'forget'},{'parent_pool':'installed_only'},
                              {'full_archive_access':True,'support_cost':1},{'full_archive_access':True,'support_patience':1}])
def test_invalid_modes(kw):
    with pytest.raises(ValueError):VSRConfig(**kw).validate()


@pytest.mark.parametrize('corruption',['archive','lineage','opening','knowledge_after','admission','charge'])
def test_fabricated_evidence_rejected(corruption):
    z=run_energy(VSRConfig(seed=3,selection='all'),K=3)
    if corruption=='archive':z['knowledge_archive'].pop(next(iter(z['knowledge_archive'])))
    elif corruption=='lineage':next(iter(z['knowledge_archive'].values()))['parents']=('UNKNOWN',)
    elif corruption=='opening':z['events'][1]['opening']['knowledge'].pop()
    elif corruption=='knowledge_after':z['events'][0]['knowledge_after'].append('FICTION')
    elif corruption=='admission':z['admissions']={}
    else:z['events'][0]['evaluation_charge']+=100
    with pytest.raises(ValueError):audit_vsr(z)
