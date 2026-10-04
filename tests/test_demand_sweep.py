import numpy as np
from dataclasses import asdict
from demand_sweep import TREATMENTS, coordinates, prepare, specs
from techgraph.discovery import canonical

def test_independent_coordinates_and_shared_start():
    for t in TREATMENTS:
        c=coordinates(288,t,72,4,0,3)
        assert np.all(c['scale']>0)
        assert np.all((c['mix_a']>0)&(c['mix_a']<1))
        assert np.all(c['spatial']>0)
        np.testing.assert_allclose(c['spatial'].sum(axis=1),1)
        joint=c['scale'][:,None,None]*np.stack([c['mix_a'],1-c['mix_a']],axis=1)[:,:,None]*c['spatial'][:,None,:]
        np.testing.assert_allclose(joint.sum(axis=(1,2)),c['scale'])
        np.testing.assert_allclose(joint[:8],np.ones((8,2,4))/8)
        if t.startswith('geo_'):
            np.testing.assert_allclose(joint.sum(axis=2),.5)
        if t.startswith('mix_'):
            np.testing.assert_allclose(joint.sum(axis=1),.25)
        if not t.startswith(('geo_','mix_')):
            np.testing.assert_allclose(joint/c['scale'][:,None,None],1/8)

def test_geographic_placement_preserves_total_mix_concentration():
    for strength in (50,80):
        a=coordinates(288,f'geo_ref{strength}',72,4,0,3)
        b=coordinates(288,f'geo_far{strength}',72,4,0,3)
        np.testing.assert_allclose(np.sort(a['spatial'],axis=1),np.sort(b['spatial'],axis=1))
    a=coordinates(288,'geo_ref80',72,4,0,3)
    b=coordinates(288,'geo_return80',72,4,0,3)
    np.testing.assert_allclose(a['spatial'][:24],b['spatial'][:24])
    np.testing.assert_allclose(a['spatial'][48:],b['spatial'][48:])
    np.testing.assert_allclose(np.sort(a['spatial'],axis=1),np.sort(b['spatial'],axis=1))
    assert np.max(abs(a['spatial'][24:48]-b['spatial'][24:48]))>.7

def test_temporal_matching_and_prefixes():
    for seed in (288,289):
        a=coordinates(seed,'irregular0',72,4,0,3)['scale']
        b=coordinates(seed,'irregular85',72,4,0,3)['scale']
        np.testing.assert_allclose(np.sort(a),np.sort(b))
        assert not np.array_equal(a,b)
        for t in ('cycle16','cycle24','irregular0','irregular85'):
            c=coordinates(seed,t,72,4,0,3)
            np.testing.assert_allclose(c['scale'].sum(),72)
        for t in TREATMENTS:
            a=coordinates(seed,t,72,4,0,3)
            b=coordinates(seed,t,96,4,0,3)
            for k in a:np.testing.assert_allclose(a[k],b[k][:72])

def test_common_physical_initial_state_and_supplies():
    worlds=[prepare(dict(seed=288,treatment=t,epochs=72,horizon=4))[0]
            for t in ('constant','growth40','geo_far80','mix_a80')]
    for w in worlds[1:]:
        assert canonical(asdict(w.scenario))==canonical(asdict(worlds[0].scenario))
        assert canonical([asdict(v) for v in w.history])==canonical([asdict(v) for v in worlds[0].history])
        assert w.realizability==worlds[0].realizability
        assert w.stocks==worlds[0].stocks
    for w in worlds:
        for q in w.scenario.flow_system.demands:
            np.testing.assert_allclose(w.trajectory.demand_scale[q.name][:8],1)

def test_frozen_coverage():
    s=specs('main')
    assert len(s)==500
    assert sum(x['epochs'] for x in s)==36480
    assert len({x['seed'] for x in s})==24
