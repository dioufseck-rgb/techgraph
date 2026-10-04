from copy import deepcopy
from dataclasses import replace
import pytest
from techgraph.catalog import Design, Scenario
from techgraph.dynamic import Params, Trajectory, solve_window_stochastic, path_cost
from techgraph.accounting import independent_path_ledger
from techgraph.integration import (IntegrationSpec, IntegrationTask, DeploymentRequirement,
                                 run_integrated_policy, audit_integration_run)
from techgraph.integration_examples import two_component_world, relabel
from techgraph.representation import Capacity, capacity_inputs, expand_selection


def run_fixture(world=None, horizon=99, **kwargs):
    sc,tr,prm,hist,spec=world or two_component_world()
    return run_integrated_policy(sc,tr,prm,hist,spec,horizon=horizon,**kwargs)


def test_staging_uses_two_real_task_completions():
    sc,tr,prm,hist,spec=two_component_world()
    run=run_fixture((sc,tr,prm,hist,spec))
    log=audit_integration_run(sc,hist,spec,run)
    assert [e['effort'] for e in log['completion_events']]==[1,1]
    assert [e['epoch'] for e in log['completion_events']]==[0,1]
    assert run['epochs'][0]['throughput']['REMOTE']==pytest.approx(0)
    assert run['epochs'][1]['throughput']['REMOTE']==pytest.approx(240)
    assert sum(e['unmet_MWh'] for e in run['epochs'])==pytest.approx(0)


def test_myopic_does_not_get_free_early_tasks():
    sc,tr,prm,hist,spec=two_component_world()
    run=run_fixture((sc,tr,prm,hist,spec),horizon=1)
    assert all(not e['integration']['completed_tasks'] for e in run['epochs'])
    assert all(e['capacity'].get('REMOTE',0)<1e-6 for e in run['epochs'])
    audit_integration_run(sc,hist,spec,run)


def test_two_tasks_in_one_design_still_cost_two_effort_units():
    sc,tr,prm,hist,spec=two_component_world()
    ds=dict(sc.designs);ds['REMOTE']=replace(ds['REMOTE'],loc='D')
    sc=replace(sc,designs=ds)
    deps=dict(spec.deployments)
    deps['REMOTE']=replace(deps['REMOTE'],tasks=('remote_operation','corridor_integration'))
    spec=replace(spec,deployments=deps)
    # Forbid the line: no separate pilot can acquire the second capability first.
    constrained=run_fixture((sc,tr,prm,hist,spec),selection=['OLD','REMOTE'])
    assert all(e['capacity'].get('REMOTE',0)<1e-6 for e in constrained['epochs'])
    unlocked=run_fixture((sc,tr,prm,hist,replace(spec,capacity=2)),selection=['OLD','REMOTE'])
    assert unlocked['epochs'][0]['integration']['effort']==pytest.approx(2)
    assert unlocked['epochs'][0]['throughput']['REMOTE']==pytest.approx(240)


def test_two_designs_can_reuse_one_task():
    sc,tr,prm,hist,spec=two_component_world()
    solar=sc.designs['REMOTE']
    sc=replace(sc,designs={'A':replace(solar,name='A',loc='D'),'B':replace(solar,name='B',loc='R')},extra_demand={'R':[10.]})
    tr=replace(tr,K=1,fuel_price=[25.],demand_mult=[1.])
    prm=replace(prm,life={'A':6,'B':6})
    spec=IntegrationSpec({'solar':IntegrationTask()},
                         {n:DeploymentRequirement(('solar',),Capacity(10,'MW'),.1) for n in ['A','B']},capacity=1)
    run=run_integrated_policy(sc,tr,prm,[],spec,horizon=99)
    assert set(run['epochs'][0]['integration']['first_deployments'])=={'A','B'}
    assert run['epochs'][0]['integration']['effort']==1
    assert run['epochs'][0]['unmet_MWh']==pytest.approx(0)
    audit_integration_run(sc,[],spec,run)


@pytest.mark.parametrize('budget', [0.0,0.5,1.0,2.0,None])
def test_effort_budgets(budget):
    sc,tr,prm,hist,spec=two_component_world(effort_budget=budget)
    run=run_fixture((sc,tr,prm,hist,spec))
    audit_integration_run(sc,hist,spec,run)
    if budget is not None:
        assert all(e['integration']['effort']<=budget+1e-6 for e in run['epochs'])


def test_noninteger_effort_not_design_count():
    sc,tr,prm,hist,spec=two_component_world()
    spec=replace(spec,tasks={t:replace(s,effort=.5) for t,s in spec.tasks.items()})
    run=run_fixture((sc,tr,prm,hist,spec))
    assert run['epochs'][0]['integration']['effort']==pytest.approx(1)
    assert len(run['epochs'][0]['integration']['completed_tasks'])==2
    assert run['epochs'][0]['throughput']['REMOTE']==pytest.approx(240)


@pytest.mark.parametrize('unit,factor',[('MW',1),('kW',1000),('W',1e6)])
def test_capacity_units_entire_input(unit,factor):
    sc,tr,prm,hist,spec=two_component_world()
    base=run_fixture((sc,tr,prm,hist,spec))
    units={n:unit for n in sc.designs}
    encoded,encoded_hist=capacity_inputs(sc,hist,units,encode=True)
    assert encoded.designs['REMOTE'].max_cap==pytest.approx(sc.designs['REMOTE'].max_cap*factor)
    converted=replace(spec,deployments={n:replace(d,reference_capacity=Capacity(10*factor,unit)) for n,d in spec.deployments.items()})
    alt=run_integrated_policy(encoded,tr,prm,encoded_hist,converted,capacity_units=units,horizon=99)
    assert path_cost(tr,base)==pytest.approx(path_cost(tr,alt),rel=1e-9)
    for a,b in zip(base['epochs'],alt['epochs']):
        assert a['capacity']==pytest.approx(b['capacity'],abs=1e-6)
        assert a['integration']==b['integration']
    assert audit_integration_run(sc,hist,spec,alt)['passed']


@pytest.mark.parametrize('unit,factor',[('MWh',1),('kWh',1000),('Wh',1e6)])
def test_storage_capacity_input_roundtrip(unit,factor):
    sc,tr,prm,hist,spec=two_component_world()
    store=Design('B','store',annual_cost=30000.,form='elec',loc='D',duration_h=4,max_cap=500)
    sc=replace(sc,designs=dict(sc.designs,B=store))
    encoded,hs=capacity_inputs(sc,hist,{'B':unit},encode=True)
    decoded,h2=capacity_inputs(encoded,hs,{'B':unit})
    assert encoded.designs['B'].max_cap==pytest.approx(500*factor)
    assert decoded.designs['B']==store
    assert h2==hist
    assert Capacity(100*factor,unit).canonical('energy')==pytest.approx(100)


@pytest.mark.parametrize('rename', [{'REMOTE':'zzz','LINE':'aaa','OLD':'incumbent'},
                                 {'REMOTE':'solar_A'}])
def test_design_alias_invariance(rename):
    world=two_component_world();base=run_fixture(world)
    altered=relabel(*world,rename);alt=run_fixture(altered)
    assert path_cost(world[1],base)==pytest.approx(path_cost(altered[1],alt),rel=1e-9)
    for a,b in zip(base['epochs'],alt['epochs']):
        translated={rename.get(n,n):v for n,v in a['capacity'].items()}
        assert translated==pytest.approx(b['capacity'],abs=1e-6)
        assert a['integration']['completed_tasks']==b['integration']['completed_tasks']


@pytest.mark.parametrize('packages,selection',[
    ({'supply':['REMOTE','LINE']},['OLD','supply']),
    ({'supply':['REMOTE','LINE'],'whole':['OLD','supply']},['whole']),
    ({'supply':['REMOTE','LINE']},['OLD','supply','REMOTE','supply']),
])
def test_lossless_package_compiles_to_same_problem(packages,selection):
    world=two_component_world();base=run_fixture(world)
    view=run_fixture(world,packages=packages,selection=selection)
    assert view['representation']['expanded_selection']==['LINE','OLD','REMOTE']
    assert path_cost(world[1],base)==pytest.approx(path_cost(world[1],view),rel=1e-10)
    for a,b in zip(base['epochs'],view['epochs']):
        assert a['integration']==b['integration']
        assert a['capacity']==pytest.approx(b['capacity'],abs=1e-7)


@pytest.mark.parametrize('fraction',[.01,.1,.25,1.0])
def test_reference_pilot_fraction_enforced(fraction):
    world=two_component_world(pilot_fraction=fraction)
    sc,tr,prm,hist,spec=world;run=run_fixture(world)
    audit_integration_run(sc,hist,spec,run)
    first=next(e for e in run['epochs'] if e['integration']['first_deployments'])
    for n in first['integration']['first_deployments']:
        assert first['builds'][n]>=10*fraction-1e-6


def test_completion_cost_replayed_once_not_each_epoch():
    sc,tr,prm,hist,spec=two_component_world(completion_cost=123.0)
    run=run_fixture((sc,tr,prm,hist,spec))
    assert sum(e['integration_cost'] for e in run['epochs'])==pytest.approx(246.)
    ledger=independent_path_ledger(sc,tr,prm,run)
    assert ledger['path_cost']==pytest.approx(run['window_objective'])
    assert ledger['path_cost']==pytest.approx(path_cost(tr,run))
    audit_integration_run(sc,hist,spec,run)
    corrupted=deepcopy(run)
    for e in corrupted['epochs']:e['integration_cost']=-999
    assert independent_path_ledger(sc,tr,prm,corrupted)['path_cost']==pytest.approx(ledger['path_cost'])


def test_knowledge_survives_retirement_and_rolling_windows():
    sc,tr,prm,hist,spec=two_component_world()
    solar=replace(sc.designs['REMOTE'],loc='D')
    sc=replace(sc,designs={'A':replace(solar,name='A'),'B':replace(solar,name='B')})
    tr=replace(tr,K=3,fuel_price=[25.]*3,demand_mult=[1.]*3,avail_from={'B':1},avail_until={'A':0})
    prm=replace(prm,life={'A':1,'B':3})
    spec=IntegrationSpec({'solar':IntegrationTask(completion_cost=20.)},
                        {n:DeploymentRequirement(('solar',),Capacity(10,'MW'),.1) for n in ['A','B']},
                        capacity=(1.,0.,0.),infer_from_history=False)
    run=run_integrated_policy(sc,tr,prm,[],spec,horizon=1)
    assert run['epochs'][0]['integration']['completed_tasks']==['solar']
    assert run['epochs'][1]['capacity']['A']==pytest.approx(0)
    assert run['epochs'][1]['capacity']['B']==pytest.approx(10)
    assert run['epochs'][1]['integration']['completed_tasks']==[]
    assert sum(e['unmet_MWh'] for e in run['epochs'])==pytest.approx(0)
    audit_integration_run(sc,[],spec,run)
    assert independent_path_ledger(sc,tr,prm,run)['path_cost']==pytest.approx(path_cost(tr,run))


def test_identical_stochastic_tasks_share_first_stage():
    sc,tr,prm,hist,spec=two_component_world(completion_cost=100)
    a=run_fixture((sc,tr,prm,hist,spec))
    b=solve_window_stochastic(sc,[tr,tr],[.4,.6],prm,0,3,hist,integration=spec)
    assert a['window_objective']==pytest.approx(b['objective'],rel=1e-9)
    assert a['epochs'][0]['integration']==b['epochs'][0]['integration']


def test_auditor_detects_fabricated_event():
    sc,tr,prm,hist,spec=two_component_world();run=run_fixture((sc,tr,prm,hist,spec))
    run['epochs'][3]['integration']['completed_tasks']=['corridor_integration']
    with pytest.raises(ValueError):audit_integration_run(sc,hist,spec,run)


@pytest.mark.parametrize('which',['coverage','unknown_task','duplicate_task','bad_fraction','dimension',
                                  'negative_effort','negative_cost','bad_budget','wrong_budget_length',
                                  'unknown_initial','undeclared_inherited','nan_reference'])
def test_invalid_integration_rejected(which):
    sc,tr,prm,hist,spec=two_component_world();deps=dict(spec.deployments);tasks=dict(spec.tasks)
    if which=='coverage':deps.pop('LINE');spec=replace(spec,deployments=deps)
    if which=='unknown_task':deps['LINE']=replace(deps['LINE'],tasks=('missing',));spec=replace(spec,deployments=deps)
    if which=='duplicate_task':deps['LINE']=replace(deps['LINE'],tasks=('corridor_integration',)*2);spec=replace(spec,deployments=deps)
    if which=='bad_fraction':deps['LINE']=replace(deps['LINE'],pilot_fraction=0);spec=replace(spec,deployments=deps)
    if which=='dimension':deps['LINE']=replace(deps['LINE'],reference_capacity=Capacity(1,'MWh'));spec=replace(spec,deployments=deps)
    if which=='negative_effort':tasks['remote_operation']=IntegrationTask(-1);spec=replace(spec,tasks=tasks)
    if which=='negative_cost':tasks['remote_operation']=IntegrationTask(completion_cost=-1);spec=replace(spec,tasks=tasks)
    if which=='bad_budget':spec=replace(spec,capacity=-1)
    if which=='wrong_budget_length':spec=replace(spec,capacity=(1,1))
    if which=='unknown_initial':spec=replace(spec,initially_known=('missing',))
    if which=='undeclared_inherited':spec=replace(spec,infer_from_history=False)
    if which=='nan_reference':deps['LINE']=replace(deps['LINE'],reference_capacity=Capacity(float('nan'),'MW'));spec=replace(spec,deployments=deps)
    with pytest.raises(ValueError):run_fixture((sc,tr,prm,hist,spec))


@pytest.mark.parametrize('packages,selected',[
    ({'a':['b'],'b':['a']},['a']),({'a':['missing']},['a']),({'a':[]},['a']),
    ({'OLD':['LINE']},['OLD']),({'a':'LINE'},['a'])])
def test_bad_package_rejected(packages,selected):
    with pytest.raises(ValueError):expand_selection(selected,['OLD','LINE'],packages)


def test_mixed_integration_regimes_rejected():
    with pytest.raises(ValueError):run_fixture(m_new=1)


@pytest.mark.parametrize('power_unit,energy_unit,factor',[('MW','MWh',1),('kW','kWh',1000),('W','Wh',1e6)])
def test_solved_storage_world_is_unit_invariant(power_unit,energy_unit,factor):
    solar=Design('PV','renewable',annual_cost=20000,loc='D',profile='sun',max_cap=100)
    store=Design('B','store',annual_cost=5000,form='elec',loc='D',duration_h=12,
                 eta_c=.9,eta_d=.9,max_cap=1000)
    sc=Scenario(periods=2,hours=12,days=1,demand_D=[0.,10.],hub_energy=0,hub_max_rate=0,fuel_price_R=25.,voll=3000.,
                locations=('D',),fuel_sites=('D',),profiles={'sun':[1.,0.]},designs={'PV':solar,'B':store})
    tr=Trajectory(2,[25.,25.],[1.,1.]);prm=Params({'PV':4,'B':3})
    spec=IntegrationSpec({'production':IntegrationTask(),'storage':IntegrationTask()},
                         {'PV':DeploymentRequirement(('production',),Capacity(10,'MW'),.1),
                          'B':DeploymentRequirement(('storage',),Capacity(100,'MWh'),.1)},capacity=2)
    base=run_integrated_policy(sc,tr,prm,[],spec,horizon=99)
    units={'PV':power_unit,'B':energy_unit}
    represented,hs=capacity_inputs(sc,[],units,encode=True)
    dep={'PV':replace(spec.deployments['PV'],reference_capacity=Capacity(10*factor,power_unit)),
         'B':replace(spec.deployments['B'],reference_capacity=Capacity(100*factor,energy_unit))}
    alt=run_integrated_policy(represented,tr,prm,hs,replace(spec,deployments=dep),capacity_units=units,horizon=99)
    assert path_cost(tr,alt)==pytest.approx(path_cost(tr,base),rel=1e-9)
    for a,b in zip(base['epochs'],alt['epochs']):
        assert a['capacity']==pytest.approx(b['capacity'],rel=1e-9)
        assert b['unmet_MWh']==pytest.approx(0)
    assert independent_path_ledger(sc,tr,prm,alt)['path_cost']==pytest.approx(path_cost(tr,alt))
    audit_integration_run(sc,[],spec,alt)


def test_no_acquisition_before_family_available():
    sc,tr,prm,hist,spec=two_component_world()
    tr=replace(tr,avail_from={'REMOTE':2,'LINE':2})
    run=run_fixture((sc,tr,prm,hist,spec))
    assert not run['epochs'][0]['integration']['completed_tasks']
    assert not run['epochs'][1]['integration']['completed_tasks']
    audit_integration_run(sc,hist,spec,run)


def test_one_off_cost_can_change_choice_without_changing_physics():
    base_world=two_component_world();base=run_fixture(base_world)
    expensive_world=two_component_world(completion_cost=1e6);expensive=run_fixture(expensive_world)
    assert any(e['integration']['completed_tasks'] for e in base['epochs'])
    assert all(not e['integration']['completed_tasks'] for e in expensive['epochs'])
    assert all(e['integration_cost']==0 for e in expensive['epochs'])


@pytest.mark.parametrize('units',[{'REMOTE':'MWh'},{'REMOTE':'horsepower'},{'missing':'MW'}])
def test_invalid_input_capacity_units(units):
    with pytest.raises(ValueError):run_fixture(capacity_units=units)


def test_small_qualifying_pilot_is_not_lost_from_the_ledger():
    # A pilot below the historical 1e-4 reporting cutoff must still be retained.
    sc,tr,prm,hist,spec=two_component_world(pilot_fraction=1e-6)
    run=run_fixture((sc,tr,prm,hist,spec))
    audit_integration_run(sc,hist,spec,run,tolerance=1e-8)
    assert run['epochs'][0]['builds']['LINE']==pytest.approx(1e-5,abs=1e-8)
    assert independent_path_ledger(sc,tr,prm,run)['path_cost']==pytest.approx(run['window_objective'],rel=1e-12)
