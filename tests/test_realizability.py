from dataclasses import replace
import pytest
from tests.test_generic_core import generic_mass_world
from techgraph.dynamic import Trajectory,Params,Vintage,run_policy,path_cost
from techgraph.realizability import Capability,DesignRequirement,SupportWindow,RealizabilitySpec


def spec(*,initial=(),initial_until=None,lead=1,validity=None,cost=5,support=None,stages=('build','operate')):
    req=DesignRequirement(build=('make_skill',) if 'build' in stages else (),
                          operate=('make_skill',) if 'operate' in stages else (),
                          maintain=('make_skill',) if 'maintain' in stages else ())
    return RealizabilitySpec({'make_skill':Capability(cost,lead,validity)}, {'MAKE':req},
                             tuple(initial), {} if initial_until is None else {'make_skill':initial_until},
                             {} if support is None else {'MAKE':support})

def world(K=5,demand=None,construction=0):
    sc=generic_mass_world(); demand=demand or [0,0,1,1,1]
    tr=Trajectory(K,[0]*K,[1.]*K,demand_scale={'product_service':demand},construction_lead={'MAKE':construction})
    return sc,tr,Params(life={'MAKE':5})

def test_known_design_requires_capability_reconstitution_before_build_and_operation():
    sc,tr,prm=world()
    r=run_policy(sc,tr,prm,[],horizon=2,realizability=spec(lead=1,cost=7))
    assert r['epochs'][1]['realizability']['acquired'][0]['capability']=='make_skill'
    assert r['epochs'][1]['realizability']['reconstitution_cost']==pytest.approx(7)
    assert r['epochs'][2]['builds']['MAKE']==pytest.approx(10)
    assert 'make_skill' in r['epochs'][2]['realizability']['ready']
    assert r['epochs'][2]['capacity']['MAKE']==pytest.approx(10)

def test_capability_can_expire_and_be_reconstituted_without_knowledge_loss():
    sc,tr,prm=world(K=4,demand=[1,0,0,1])
    rs=spec(initial=('make_skill',),initial_until=0,lead=0,validity=1,cost=3)
    r=run_policy(sc,tr,prm,[],horizon=2,realizability=rs)
    # initial capability supports first build; after expiry a later acquisition restores realizability
    assert 'make_skill' in r['epochs'][0]['realizability']['ready']
    assert any(e.get('realizability',{}).get('acquired') for e in r['epochs'][1:])
    assert set(sc.designs)=={'MAKE'}  # knowledge/catalogue unchanged

def test_operating_support_withdrawal_can_force_migration_or_infeasibility():
    sc,tr,prm=world(K=4,demand=[1,1,1,1])
    rs=spec(initial=('make_skill',),support=SupportWindow(operate_until=1),stages=('build','operate'))
    with pytest.raises(RuntimeError):
        run_policy(sc,tr,prm,[],horizon=4,realizability=rs)

def test_maintain_support_withdrawal_forces_installed_capacity_out_of_living_stock():
    sc,tr,prm=world(K=3,demand=[1,0,0])
    hist=[Vintage('MAKE',-1,10,10,10,0,10)]
    rs=spec(initial=('make_skill',),support=SupportWindow(maintain_until=0),stages=('maintain',))
    r=run_policy(sc,tr,prm,hist,horizon=3,realizability=rs)
    assert r['epochs'][0]['vintages'][0]['alive']==pytest.approx(10)
    assert r['epochs'][1]['vintages'][0]['alive']==pytest.approx(0)

def test_reconstitution_cost_is_in_path_cost_and_independent_ledger():
    from techgraph.accounting import independent_path_ledger
    sc,tr,prm=world()
    r=run_policy(sc,tr,prm,[],horizon=2,realizability=spec(lead=1,cost=7))
    ledger=independent_path_ledger(sc,tr,prm,r)
    assert any(e['realizability_cost']==pytest.approx(7) for e in ledger['epochs'])
    assert ledger['path_cost']==pytest.approx(path_cost(tr,r))

def test_standard_measurement_reports_realizability_history():
    from types import SimpleNamespace
    from techgraph.measurement.schema import standard_run_measurement
    sc,tr,prm=world();r=run_policy(sc,tr,prm,[],horizon=2,realizability=spec(lead=1,cost=7))
    m=standard_run_measurement(SimpleNamespace(scenario=sc,trajectory=tr,metadata={}),r).manifest()
    assert m['epochs'][1]['history']['capabilities_acquired']==1
    assert m['epochs'][1]['transition']['reconstitution_cost']==pytest.approx(7)

def test_capability_and_construction_leads_compose():
    sc,tr,prm=world(K=6,demand=[0,0,0,1,1,1],construction=2)
    # skill is required to order; acquiring it takes one epoch, then construction takes two.
    r=run_policy(sc,tr,prm,[],horizon=4,realizability=spec(lead=1,cost=2))
    assert r['epochs'][0]['realizability']['acquired']
    assert r['epochs'][1]['orders']['MAKE']==pytest.approx(10)
    assert r['epochs'][3]['commissioned']['MAKE']==pytest.approx(10)

def test_integration_pilot_and_construction_lead_compose_at_order_then_commission():
    from techgraph.integration import IntegrationSpec,IntegrationTask,DeploymentRequirement
    from techgraph.representation import Capacity
    sc,tr,prm=world(K=5,demand=[0,0,1,1,1],construction=2)
    integ=IntegrationSpec({'develop':IntegrationTask(1,2,'develop MAKE')},
                          {'MAKE':DeploymentRequirement(('develop',),Capacity(10,'tonne/h'),1.0)},capacity=1)
    r=run_policy(sc,tr,prm,[],horizon=3,integration=integ)
    assert r['epochs'][0]['integration']['completed_tasks']==['develop']
    assert r['epochs'][0]['orders']['MAKE']==pytest.approx(10)
    assert r['epochs'][2]['commissioned']['MAKE']==pytest.approx(10)
