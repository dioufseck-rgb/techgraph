from techgraph.evolving_networks import make_evolving_network_world
from techgraph.network_experiments import execute,audit_execution


def test_moving_demands_are_named_and_nonstationary():
    w=make_evolving_network_world(3,0,'rich',K=12,demand_mode='moving')
    names=[q.name for q in w.scenario.flow_system.demands]
    assert set(names)==set(w.trajectory.demand_scale)
    assert any(len(set(round(x,8) for x in w.trajectory.demand_scale[n]))>1 for n in names)
    assert all(q.scale_with_demand for q in w.scenario.flow_system.demands)


def test_optional_needs_are_recognized_later_and_not_required():
    w=make_evolving_network_world(3,0,'rich',K=12,demand_mode='moving',optional=True)
    assert len(w.scenario.need_system.needs)==6
    assert {n.recognized_from for n in w.scenario.need_system.needs}=={4,10}


def test_short_dynamic_run_audits():
    w=make_evolving_network_world(3,1,'rich',K=6,demand_mode='moving',optional=True)
    r=execute(w,horizon=1,time_limit=30)
    assert audit_execution(w,r)['passed']


def test_build_rate_is_recorded_and_limits_each_new_build():
    w=make_evolving_network_world(3,1,'rich',K=6,demand_mode='moving',adjustment_rate=4.)
    r=execute(w,horizon=1,time_limit=30)
    for e in r['epochs']:
        assert all(x<=4+1e-7 for x in e['builds'].values())
