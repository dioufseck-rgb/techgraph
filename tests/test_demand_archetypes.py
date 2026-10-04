import pytest
from techgraph.demand_archetypes import ARCHETYPES,make_demand_archetype_world

@pytest.mark.parametrize('kind',ARCHETYPES)
def test_paths_positive_cover_horizon(kind):
    w=make_demand_archetype_world(6,0,'rich',K=24,archetype=kind)
    assert w.metadata['demand_experiment']['adoption_is_output'] is True
    assert set(w.trajectory.demand_scale)=={q.name for q in w.scenario.flow_system.demands}
    assert all(len(v)==24 and min(v)>0 for v in w.trajectory.demand_scale.values())

@pytest.mark.parametrize('kind',['flat','compound_growth','saturating_growth','decline','structural_break'])
def test_common_archetypes_same_multiplier_across_required_services(kind):
    w=make_demand_archetype_world(6,0,'rich',K=24,archetype=kind)
    vals=list(w.trajectory.demand_scale.values())
    assert all(v==vals[0] for v in vals[1:])

def test_regional_shift_preserves_aggregate_required_service_by_class():
    w=make_demand_archetype_world(6,0,'rich',K=24,archetype='regional_shift')
    q={x.name:sum(x.rates) for x in w.scenario.flow_system.demands}
    for sec in [False,True]:
        names=[n for n in q if n.startswith('secondary_')==sec]
        totals=[sum(q[n]*w.trajectory.demand_scale[n][k] for n in names) for k in range(24)]
        assert max(totals)-min(totals)<1e-9

def test_all_archetypes_share_same_initial_required_demand_vector():
    worlds=[make_demand_archetype_world(6,1,'rich',K=24,archetype=k) for k in ARCHETYPES]
    names=worlds[0].trajectory.demand_scale
    for w in worlds:
        assert all(w.trajectory.demand_scale[n][0]==pytest.approx(1.0) for n in names)
