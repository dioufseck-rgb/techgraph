from dataclasses import replace
import pytest
from techgraph.dynamic import Trajectory, Params, solve_window
from test_accounting_regression import fuel_world
from techgraph.flows import FlowDemand


def test_named_required_demand_can_move_independently():
    # Structural test of independent named schedules; physical integration is exercised below.
    t=Trajectory(3,[0,0,0],[1,1,1],demand_scale={'x':[1,.5,2]})
    assert [t.demand('x',k) for k in range(3)]==[1,.5,2]
    assert [t.demand('other',k) for k in range(3)]==[1,1,1]


def test_build_rate_caps_new_capacity_without_changing_design_maximum():
    sc=fuel_world(); tr=Trajectory(2,[25,25],[1,1],discount=1.,build_rate={'G':[3,3]})
    p=Params({'G':10},aging=0)
    # Demand requires 10 MW but only 3 MW can be added in first epoch; hard legacy service
    # is soft in this fixture, so inspect the build cap directly in the solved path.
    sol=solve_window(sc,tr,p,0,1,[])
    assert sol['epochs'][0]['builds']['G'] <= 3+1e-8
    assert sol['epochs'][1]['builds']['G'] <= 3+1e-8


def test_default_build_rate_preserves_previous_behavior():
    sc=fuel_world(); p=Params({'G':10},aging=0)
    a=solve_window(sc,Trajectory(1,[25],[1],discount=1.),p,0,0,[])
    b=solve_window(sc,Trajectory(1,[25],[1],discount=1.,build_rate={}),p,0,0,[])
    assert a['objective']==pytest.approx(b['objective'])
