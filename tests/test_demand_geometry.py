import pytest
from techgraph.demand_geometry import make_demand_geometry_world,gini


def amounts(w,k):
    return {q.name:sum(q.rates)*w.scenario.hours*w.trajectory.demand(q.name,k) for q in w.scenario.flow_system.demands}


def test_gini_scale_invariant():
    assert gini([1,2,3])==pytest.approx(gini([10,20,30]))

@pytest.mark.parametrize('scale',[.75,1.,1.5])
def test_target_total_scale(scale):
    a=make_demand_geometry_world(scale=1.);b=make_demand_geometry_world(scale=scale)
    assert sum(amounts(b,23).values())/sum(amounts(a,0).values())==pytest.approx(scale)

@pytest.mark.parametrize('alpha',[0,.25,.5])
def test_concentration_controls_gini_independent_of_scale(alpha):
    a=make_demand_geometry_world(scale=.75,concentration=alpha)
    b=make_demand_geometry_world(scale=1.5,concentration=alpha)
    assert a.metadata['demand_geometry']['target_state']['gini']==pytest.approx(b.metadata['demand_geometry']['target_state']['gini'])

@pytest.mark.parametrize('alpha',[.25,.5])
def test_placement_preserves_gini_and_total(alpha):
    a=make_demand_geometry_world(concentration=alpha,placement='toward')
    b=make_demand_geometry_world(concentration=alpha,placement='away')
    x=a.metadata['demand_geometry']['target_state'];y=b.metadata['demand_geometry']['target_state']
    assert x['gini']==pytest.approx(y['gini']);assert x['total']==pytest.approx(y['total'])
    assert x['demand_weighted_distance_from_advantaged']<y['demand_weighted_distance_from_advantaged']

@pytest.mark.parametrize('share',[.65,.8,.9])
def test_composition_changes_primary_share_not_total_or_spatial_gini(share):
    w=make_demand_geometry_world(primary_share=share,concentration=.25)
    x=amounts(w,23);p=sum(v for n,v in x.items() if n.startswith('product_'))
    assert p/sum(x.values())==pytest.approx(share)
    ref=make_demand_geometry_world(primary_share=.8,concentration=.25)
    assert w.metadata['demand_geometry']['target_state']['gini']==pytest.approx(ref.metadata['demand_geometry']['target_state']['gini'])


def test_common_initial_state_across_targets():
    a=make_demand_geometry_world(scale=.75,concentration=.5,placement='away',primary_share=.65)
    b=make_demand_geometry_world(scale=1.5,concentration=0,placement='toward',primary_share=.9)
    assert amounts(a,0)==pytest.approx(amounts(b,0))
