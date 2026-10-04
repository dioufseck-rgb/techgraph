from dataclasses import replace
import pytest

from techgraph.dynamic import run_policy, solve_window_stochastic, Project
from techgraph.network_worlds import make_network_world
from techgraph.needs import NeedSystem, OptionalNeed, ServiceProfile
from techgraph.realizability import Capability, DesignRequirement, RealizabilitySpec
from techgraph.stocks import audit_stock_run
from techgraph.attributes import audit_attribute_run
from techgraph.accounting import independent_path_ledger


def composed_world(n=2, K=4, integration=False):
    w=make_network_world(n_sites=n,seed=0,connectivity='rich',K=K,residual_capacity=8,
                         shock_site=0,shock_epoch=2,enable_integration=integration,
                         integration_budget=10 if integration else None)
    sc=w.scenario; loc=sc.locations[0]
    need=OptionalNeed('extra',(ServiceProfile('product',loc,tuple([1.]*sc.periods),'grade_'+loc),),
                      value=8.,recognized_from=1)
    sc=replace(sc,need_system=NeedSystem((need,)))
    inherited={v.design for v in w.history}
    tr=replace(w.trajectory,construction_lead={name:1 for name in sc.designs if name not in inherited})
    req={name:DesignRequirement(build=('modern',),operate=('modern',),maintain=('modern',))
         for name in sc.designs if name not in inherited}
    rs=RealizabilitySpec({'modern':Capability(0,0,None)},req,initially_ready=('modern',))
    roles=w.metadata['module_roles']; a,b=w.metadata['allowed_edges'][0]; la,lb=sc.locations[a],sc.locations[b]
    fail=[name for name,r in roles.items() if r['role']=='LINK' and {r['origin'],r['destination']}=={la,lb}]
    cont=[{'name':'corridor_loss','p':.01,'fail':fail}]
    return w,sc,tr,rs,cont


def test_all_modern_mechanisms_compose_in_one_reliability_run():
    w,sc,tr,rs,cont=composed_world(integration=True)
    r=run_policy(sc,tr,w.params,w.history,horizon=99,forbid=w.forbid,stocks=w.stocks,
                 contingencies=cont,integration=w.integration,realizability=rs)
    assert len(r['epochs'][0]['operating_states'])==2
    assert audit_stock_run(sc,w.stocks,r)['passed']
    assert audit_attribute_run(sc,r,trajectory=tr)['passed']
    assert independent_path_ledger(sc,tr,w.params,r)['path_objective']==pytest.approx(r['window_objective'])
    assert any(e.get('wip') for e in r['epochs'])
    assert all('realizability' in e and 'integration' in e for e in r['epochs'])
    assert any(e['service_benefit']>0 for e in r['epochs'])


def test_stochastic_paths_compose_stocks_attributes_needs_commissioning_and_realizability():
    w,sc,tr,rs,_=composed_world(integration=False)
    name=sc.flow_system.demands[0].name
    tr2=replace(tr,demand_scale={name:[1.,1.15,1.3,1.3]})
    out=solve_window_stochastic(sc,[tr,tr2],[.5,.5],w.params,0,3,w.history,
                                stocks=w.stocks,realizability=rs)
    assert len(out['scenarios'])==2
    assert out['scenario_weights']==[.5,.5]
    for path in out['scenarios']:
        run={'epochs':[path['epochs'][k] for k in range(4)]}
        assert audit_attribute_run(sc,run,trajectory=tr)['passed']
        assert all(e['stocks'] for e in run['epochs'])
        assert all('realizability' in e for e in run['epochs'])


def test_contingency_stocks_share_opening_but_not_closing_state():
    w,sc,tr,rs,cont=composed_world(integration=False)
    r=run_policy(sc,tr,w.params,w.history,horizon=99,forbid=w.forbid,stocks=w.stocks,
                 contingencies=cont,realizability=rs)
    for e in r['epochs']:
        normal=e['operating_states'][0]
        stress=e['operating_states'][1]
        for stock in e['stocks']:
            assert normal['stocks'][stock]['stock_start']==pytest.approx(stress['stocks'][stock]['stock_start'])
            assert e['stocks'][stock]['stock_end']==pytest.approx(normal['stocks'][stock]['stock_end'])


def test_optional_benefit_is_probability_weighted_across_contingency_states():
    w,sc,tr,rs,cont=composed_world(integration=False)
    r=run_policy(sc,tr,w.params,w.history,horizon=99,forbid=w.forbid,stocks=w.stocks,
                 contingencies=cont,realizability=rs)
    for e in r['epochs']:
        expected=sum(s['probability']*s['flow']['needs']['benefit'] for s in e['operating_states'])
        assert e['service_benefit']==pytest.approx(expected)


def test_stochastic_inherited_wip_cancellation_is_first_stage_shared():
    w,sc,tr,rs,_=composed_world(integration=False)
    # A useless inherited project should be canceled identically before scenario-specific operation.
    name=next(n for n in sc.designs if n not in {v.design for v in w.history})
    d=sc.designs[name]
    project=Project(name,-1,1.,2,d.annual_cost,d.fixed_cost,w.params.life[name])
    # Remove service to make cancellation attractive in both paths.
    fs=replace(sc.flow_system,demands=())
    sc0=replace(sc,flow_system=fs,need_system=None,attribute_system=None)
    out=solve_window_stochastic(sc0,[tr,tr],[.5,.5],w.params,0,2,[],projects=[project],stocks=w.stocks)
    cancels=[p['epochs'][0]['stranded_work'] for p in out['scenarios']]
    assert cancels[0]==pytest.approx(cancels[1])

def test_standard_measurement_emits_reliability_metrics():
    from types import SimpleNamespace
    from techgraph.measurement.schema import standard_run_measurement
    w,sc,tr,rs,cont=composed_world(integration=False)
    r=run_policy(sc,tr,w.params,w.history,horizon=99,forbid=w.forbid,stocks=w.stocks,
                 contingencies=cont,realizability=rs)
    world=SimpleNamespace(scenario=sc,trajectory=tr,metadata=w.metadata)
    m=standard_run_measurement(world,r).manifest()
    assert m['epochs'][0]['service']['contingency_service_survival']==pytest.approx(1.)
    assert m['epochs'][0]['architecture']['installed_links']>=m['epochs'][0]['architecture']['active_normal_links']

def test_stochastic_stock_paths_diverge_with_scenario_operation():
    from techgraph.stock_examples import residual_world
    sc,tr,p,h,stocks=residual_world(K=3,capacity=20)
    tr2=replace(tr,demand_mult=[.5,.5,.5])
    out=solve_window_stochastic(sc,[tr,tr2],[.5,.5],p,0,2,h,stocks=stocks)
    paths=[[path['epochs'][k]['stocks']['pile']['stock_end'] for k in range(3)] for path in out['scenarios']]
    assert paths[0]==pytest.approx([2.5,5.,7.5])
    assert paths[1]==pytest.approx([1.25,2.5,3.75])
