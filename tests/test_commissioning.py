from dataclasses import replace
import pytest

from techgraph.dynamic import Trajectory, Params, Project, run_policy
from tests.test_generic_core import generic_mass_world


def world_and_params(K=4, demand=None, lead=2):
    sc=generic_mass_world()
    demand = demand or [0.0, 0.0, 1.0, 1.0]
    tr=Trajectory(K=K, fuel_price=[0.0]*K, demand_mult=[1.0]*K,
                  demand_scale={'product_service': demand},
                  construction_lead={'MAKE': lead})
    prm=Params(life={'MAKE':4})
    return sc,tr,prm


def test_lead_time_requires_anticipatory_order_and_commissions_later():
    sc,tr,prm=world_and_params()
    run=run_policy(sc,tr,prm,[],horizon=3)
    assert run['epochs'][0]['orders']['MAKE'] == pytest.approx(10.0)
    assert run['epochs'][0]['capacity'].get('MAKE',0.0) == pytest.approx(0.0)
    assert run['epochs'][0]['wip'][0]['commission'] == 2
    assert run['epochs'][1]['capacity'].get('MAKE',0.0) == pytest.approx(0.0)
    assert run['epochs'][2]['capacity']['MAKE'] == pytest.approx(10.0)
    assert run['epochs'][2]['operating_states'][0]['flow']['demands']['product_service']['delivered_rates'][0] == pytest.approx(10.0)


def test_one_epoch_planner_cannot_react_after_need_is_immediate():
    sc,tr,prm=world_and_params()
    with pytest.raises(RuntimeError):
        run_policy(sc,tr,prm,[],horizon=1)


def test_inherited_work_in_progress_can_be_canceled_and_is_stranded():
    sc,tr,prm=world_and_params(demand=[0.0]*4)
    p=Project('MAKE', ordered=-1, capacity=10.0, commission=2,
              annual_cost=10.0, fixed_cost=0.0, life=4)
    run=run_policy(sc,tr,prm,[],horizon=3,projects0=[p])
    assert run['epochs'][0]['stranded_work'] == pytest.approx(10.0)
    assert run['epochs'][2]['capacity'].get('MAKE',0.0) == pytest.approx(0.0)


def test_zero_lead_preserves_same_epoch_commissioning():
    sc=generic_mass_world()
    tr=Trajectory(K=1,fuel_price=[0.0],demand_mult=[1.0],construction_lead={'MAKE':0})
    prm=Params(life={'MAKE':4})
    run=run_policy(sc,tr,prm,[],horizon=1)
    assert run['epochs'][0]['orders']['MAKE'] == pytest.approx(10.0)
    assert run['epochs'][0]['capacity']['MAKE'] == pytest.approx(10.0)

def test_capital_commitment_runs_from_order_through_commissioned_life():
    from techgraph.accounting import capital_charges_by_epoch
    sc,tr,prm=world_and_params(K=8,demand=[0,0,1,1,1,1,1,1],lead=2)
    fake={'epochs':[{'builds':{'MAKE':10.0},'lump_builds':{}}]+[{'builds':{},'lump_builds':{}} for _ in range(7)]}
    charges=capital_charges_by_epoch(sc,tr,prm,fake)
    # order at 0, commission at 2, four-epoch operating life => commitment through epoch 5
    assert all(x>0 for x in charges[:6])
    assert charges[6:] == [0.0,0.0]


def test_standard_measurement_reports_construction_state():
    from types import SimpleNamespace
    from techgraph.measurement.schema import standard_run_measurement
    sc,tr,prm=world_and_params()
    run=run_policy(sc,tr,prm,[],horizon=3)
    world=SimpleNamespace(scenario=sc,trajectory=tr,metadata={})
    m=standard_run_measurement(world,run).manifest()
    assert m['epochs'][0]['transition']['ordered_capacity'] == pytest.approx(10.0)
    assert m['epochs'][0]['transition']['wip_capacity'] == pytest.approx(10.0)
    assert m['epochs'][2]['transition']['commissioned_capacity'] == pytest.approx(10.0)
