"""Mechanism fixtures and adversarial checks, not fitted empirical assertions."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest

from techgraph.catalog import Scenario, Design, default_scenario
from techgraph.flows import FlowSystem, FlowResource, FlowDemand, Destination, Port, audit_flow_block
from techgraph.needs import (NeedSystem, OptionalNeed, ServiceProfile, validate_needs, audit_need_run,
                             audit_need_block, replay_need_block)
from techgraph.need_examples import (joint_service_world, efficiency_need_world, residual_demand_world,
                                     inherited_resource_needs_world, simple_task_spec)
from techgraph.dynamic import (Params, Trajectory, Vintage, run_policy, solve_window,
                                solve_window_stochastic, path_cost, path_benefit, path_objective, path_net_value)
from techgraph.model import solve, check_balances
from techgraph.flow_audit import audit_operating_state
from techgraph.accounting import independent_path_ledger
from techgraph.analysis import operating_prices, value
from techgraph.integration import run_integrated_policy, audit_integration_run
from techgraph.representation import capacity_inputs
from techgraph.stocks import audit_stock_run


def small_world(*,mode='divisible',cap=10.,price=2.,benefit=3.,required=0.,K=1,periods=1):
    fs=FlowSystem(resources=(FlowResource('supply','elec','D',(cap,)*periods,price),),hard_legacy_service=True)
    need=OptionalNeed('extra',(ServiceProfile('elec','D',(1.,)*periods),),benefit,mode=mode)
    sc=Scenario(periods,1.,[required]*periods,0.,0.,{},0.,3000.,{},days=periods/24.,
                locations=('D',),fuel_sites=(),flow_system=fs,need_system=NeedSystem((need,)))
    return sc,Trajectory(K,[0.]*K,[1.]*K,discount=.93),Params({},aging=0.),[]


def fraction(run,name='extra',k=0):
    return run['epochs'][k]['operating_states'][0]['flow']['needs']['services'][name]['fraction']


def exercise(sc,tr,p,h,**kwargs):
    r=run_policy(sc,tr,p,h,**kwargs)
    a=audit_need_run(sc,r)
    for e in r['epochs']:
        for state in e['operating_states']:
            audit_flow_block(sc,state['flow'],e['capacity']);audit_operating_state(sc,state)
    ledger=independent_path_ledger(sc,tr,p,r)
    assert ledger['path_cost']==pytest.approx(path_cost(tr,r),abs=1e-6)
    assert ledger['path_benefit']==pytest.approx(path_benefit(tr,r),abs=1e-6)
    assert ledger['path_objective']==pytest.approx(path_objective(tr,r),abs=1e-6)
    assert ledger['path_net_value']==pytest.approx(path_net_value(tr,r),abs=1e-6)
    if r['status']=='Optimal':assert ledger['path_objective']==pytest.approx(r['window_objective'],abs=1e-6)
    return r


@pytest.mark.parametrize('customers,expected',[ (('A',),0.), (('B',),0.), (('A','B'),3.) ])
@pytest.mark.parametrize('horizon',[1,99])
def test_joint_service_value(customers,expected,horizon):
    sc,tr,p,h=joint_service_world(customers=customers)
    r=exercise(sc,tr,p,h,horizon=horizon)
    assert path_net_value(tr,r)==pytest.approx(expected)
    assert sum(v['fraction'] for v in r['epochs'][0]['operating_states'][0]['flow']['needs']['services'].values())==(2 if expected else 0)


def test_gross_cost_is_not_optimized_objective():
    sc,tr,p,h=joint_service_world()
    r=exercise(sc,tr,p,h,horizon=99)
    assert path_cost(tr,r)==pytest.approx(13)
    assert path_benefit(tr,r)==pytest.approx(16)
    assert path_objective(tr,r)==pytest.approx(-3)
    assert r['window_objective']!=path_cost(tr,r)


def test_sunk_shared_connection_changes_single_customer_uptake():
    sc,tr,p,h=joint_service_world(customers=('A',))
    r=solve(sc,sc.designs,existing={'TRUNK':2})
    assert r.expenses==pytest.approx(1.5)
    assert r.service_benefit==pytest.approx(8)
    assert not check_balances(sc,r)


@pytest.mark.parametrize('mode,cap,expected',[('divisible',.5,.5),('indivisible',.5,0.),('indivisible',1.,1.)])
def test_service_granularity(mode,cap,expected):
    sc,tr,p,h=small_world(mode=mode,cap=cap)
    r=exercise(sc,tr,p,h,horizon=99)
    assert fraction(r)==pytest.approx(expected)
    assert r['epochs'][0]['unmet_MWh']==pytest.approx(0)


@pytest.mark.parametrize('benefit,expected',[(0.,0.),(1.,0.),(3.,1.)])
def test_refusal_is_not_shortfall(benefit,expected):
    sc,tr,p,h=small_world(benefit=benefit)
    r=exercise(sc,tr,p,h,horizon=99)
    assert fraction(r)==pytest.approx(expected)
    assert r['epochs'][0]['unmet_MWh']==0


def test_zero_net_value_is_not_assumed_to_activate():
    sc,tr,p,h=small_world(price=3.,benefit=3.)
    r=exercise(sc,tr,p,h,horizon=99)
    assert path_objective(tr,r)==pytest.approx(0)
    assert 0<=fraction(r)<=1  # either optimum is permitted, no invented tie-breaking rule


def test_physical_delivery_not_output_creates_benefit():
    sc,tr,p,h=small_world(cap=0.,benefit=100.)
    r=exercise(sc,tr,p,h,horizon=99)
    assert path_benefit(tr,r)==0


def test_required_service_precedes_optional_when_hard():
    sc,tr,p,h=small_world(cap=1.5,required=1.,benefit=100.)
    r=exercise(sc,tr,p,h,horizon=99)
    assert fraction(r)==pytest.approx(.5)
    assert r['epochs'][0]['unmet_MWh']==0


def test_soft_obligation_keeps_its_explicit_penalty():
    sc,tr,p,h=small_world(cap=1.,required=1.,benefit=100.)
    sc=replace(sc,voll=5.,flow_system=replace(sc.flow_system,hard_legacy_service=False))
    r=exercise(sc,tr,p,h,horizon=99)
    assert fraction(r)==1
    assert r['epochs'][0]['unmet_MWh']==1
    assert path_cost(tr,r)==pytest.approx(7)  # cost 2 plus declared penalty 5, not negative utility


def test_multiform_bundle_cannot_collect_value_for_one_component():
    sc,tr,p,h=small_world(benefit=100.)
    fs=replace(sc.flow_system,form_units={**sc.flow_system.form_units,'water':'tonne'},
        resources=sc.flow_system.resources+(FlowResource('water','water','D',(.25,),0.),))
    n=replace(sc.need_system.needs[0],profiles=sc.need_system.needs[0].profiles+(ServiceProfile('water','D',(1.,)),))
    sc=replace(sc,flow_system=fs,need_system=NeedSystem((n,)))
    r=exercise(sc,tr,p,h,horizon=99)
    assert fraction(r)==pytest.approx(.25)
    assert path_benefit(tr,r)==pytest.approx(25.)


def test_temporal_service_bundle_requires_all_periods():
    sc,tr,p,h=small_world(periods=2,mode='indivisible',benefit=100.)
    sc=replace(sc,flow_system=replace(sc.flow_system,resources=(FlowResource('supply','elec','D',(10.,0.),0.),)))
    r=exercise(sc,tr,p,h,horizon=99)
    assert fraction(r)==0


def test_zero_rate_period_in_nonzero_service_profile():
    sc,tr,p,h=small_world(periods=2,benefit=3.)
    n=replace(sc.need_system.needs[0],profiles=(ServiceProfile('elec','D',(0.,1.)),))
    r=exercise(replace(sc,need_system=NeedSystem((n,))),tr,p,h,horizon=99)
    assert fraction(r)==1


@pytest.mark.parametrize('horizon',[1,99])
def test_supply_change_causes_uptake_not_recognition_date(horizon):
    sc,tr,p,h=joint_service_world(K=5,trunk_cost=20.,cheap_at=2)
    r=exercise(sc,tr,p,h,horizon=horizon)
    assert [fraction(r,'customer_A',k) for k in range(5)]==pytest.approx([0,0,1,1,1])
    assert all(e['operating_states'][0]['flow']['needs']['services']['customer_A']['recognized'] for e in r['epochs'])


@pytest.mark.parametrize('horizon',[1,99])
def test_recognition_and_expiry(horizon):
    sc,tr,p,h=small_world(K=4)
    n=replace(sc.need_system.needs[0],recognized_from=1,expires_at=3)
    r=exercise(replace(sc,need_system=NeedSystem((n,))),tr,p,h,horizon=horizon)
    assert [fraction(r,k=k) for k in range(4)]==pytest.approx([0,1,1,0])


def test_values_can_change_without_scripting_adoption():
    sc,tr,p,h=small_world(K=3,benefit=(1.,5.,1.))
    r=exercise(sc,tr,p,h,horizon=99)
    assert [fraction(r,k=k) for k in range(3)]==[0,1,0]


def test_known_structural_eligibility_but_static_forecast_of_value():
    sc,tr,p,h=small_world(K=2,benefit=(1.,5.))
    a=solve_window(sc,tr,p,0,1,h,expectations='true')
    b=solve_window(sc,tr,p,0,1,h,expectations='static')
    assert a['epochs'][1]['service_benefit']==pytest.approx(5)
    assert b['epochs'][1]['service_benefit']==0
    # The next actual decision sees its realized value, not the prior frozen projection.
    r=exercise(sc,tr,p,h,horizon=2,expectations='static')
    assert fraction(r,k=1)==1


@pytest.mark.parametrize('scale',[0.,.5,2.,(0.,.5,2.)])
def test_quantity_scale_has_independent_gross_profile_value(scale):
    sc,tr,p,h=small_world(K=3,benefit=100.)
    n=replace(sc.need_system.needs[0],scale=scale)
    r=exercise(replace(sc,need_system=NeedSystem((n,))),tr,p,h,horizon=99)
    for k in range(3):
        expected=scale[k] if isinstance(scale,tuple) else scale
        rec=r['epochs'][k]['operating_states'][0]['flow']['needs']['services']['extra']
        assert rec['profiles'][0]['delivered_rates']==pytest.approx([expected])
        assert rec['benefit']==pytest.approx(100 if expected>0 else 0)


@pytest.mark.parametrize('mode',['divisible','indivisible'])
@pytest.mark.parametrize('periods',[1,2,3])
def test_static_dynamic_equivalence(mode,periods):
    sc,tr,p,h=small_world(mode=mode,periods=periods,benefit=5.*periods)
    a=solve(sc,sc.designs);b=solve_window(sc,tr,p,0,0,h)
    assert a.objective==pytest.approx(b['objective'],abs=1e-7)
    assert a.expenses==pytest.approx(b['epochs'][0]['ops_cost'])
    assert sum(a.costs.values())==pytest.approx(a.objective)
    assert not check_balances(sc,a)


def test_static_evaluates_requested_need_epoch():
    sc,tr,p,h=small_world(K=3,benefit=(1.,5.,1.))
    assert solve(sc,[],need_epoch=0).objective==0
    assert solve(sc,[],need_epoch=1).objective==pytest.approx(-3)


def test_fixed_assets_do_not_remove_integer_service_choice():
    sc,tr,p,h=small_world(mode='indivisible')
    a=solve(sc,[],fixed=True)
    assert a.service_benefit==3
    assert a.prices=={}
    assert a.solver['integer_variables']==1
    with pytest.raises(ValueError,match='Indivisible'): operating_prices(sc,{})


def test_continuous_optional_service_allows_fixed_lp_prices():
    sc,tr,p,h=small_world()
    a=operating_prices(sc,{})
    assert a.prices['elec','D',0]==pytest.approx(2)


@pytest.mark.parametrize('horizon',[1,99])
def test_efficiency_fixed_vs_variable_service(horizon):
    quantities=[]
    for optional in [False,True]:
        sc,tr,p,h=efficiency_need_world(optional=optional)
        r=run_policy(sc,tr,p,h,horizon=horizon)
        quantities.append([s['operating_states'][0]['fuel_purchased_MWh'] for s in r['epochs']])
        for e in r['epochs']:audit_operating_state(sc,e['operating_states'][0])
    assert quantities[0]==pytest.approx([4,4,2,2,2])
    assert quantities[1]==pytest.approx([4,4,6,6,6])


@pytest.mark.parametrize('horizon',[1,99])
def test_optional_service_obeys_stock_limits(horizon):
    sc,tr,p,h,stocks=residual_demand_world()
    r=exercise(sc,tr,p,h,horizon=horizon,stocks=stocks)
    assert audit_stock_run(sc,stocks,r)['passed']
    assert max(e['stocks']['pile']['stock_end'] for e in r['epochs'])<=5.+1e-6


@pytest.mark.parametrize('horizon,expected',[ (1,[1,0,1]),(99,[0,0,1]) ])
def test_stock_can_be_reserved_for_future_more_valuable_use(horizon,expected):
    sc,tr,p,h,stocks=inherited_resource_needs_world()
    r=exercise(sc,tr,p,h,horizon=horizon,stocks=stocks,forbid=('OLD',))
    assert [fraction(r,'optional_product',k) for k in range(3)]==pytest.approx(expected)
    assert audit_stock_run(sc,stocks,r)['passed']


def test_full_horizon_compared_on_net_value_not_expense_or_output_alone():
    sc,tr,p,h,stocks=inherited_resource_needs_world()
    r1=exercise(sc,tr,p,h,horizon=1,stocks=stocks,forbid=('OLD',))
    r2=exercise(sc,tr,p,h,horizon=99,stocks=stocks,forbid=('OLD',))
    assert path_net_value(tr,r2)>path_net_value(tr,r1)
    assert sum(fraction(r2,'optional_product',k) for k in range(3))<sum(fraction(r1,'optional_product',k) for k in range(3))


def test_high_value_does_not_delete_a_closed_residual():
    sc,tr,p,h,stocks=residual_demand_world(capacity=0.)
    sc=replace(sc,flow_system=replace(sc.flow_system,demands=()),
               need_system=NeedSystem((replace(sc.need_system.needs[0],value=1000.),)))
    r=exercise(sc,tr,p,[],horizon=99,stocks=stocks,forbid=('CLEAN',))
    assert path_benefit(tr,r)==0


def test_small_service_keeps_small_builds_in_rolling_history_and_ledger():
    sc,tr,p,h=small_world(K=2,benefit=1.)
    sc=replace(sc,flow_system=replace(sc.flow_system,resources=()),profiles={'flat':[1.]},
        designs={'S':Design('S','renewable',8760.,loc='D',profile='flat',max_cap=1.)},
        need_system=NeedSystem((replace(sc.need_system.needs[0],profiles=(ServiceProfile('elec','D',(1e-5,)),)),)))
    p=Params({'S':5},aging=0.)
    r=exercise(sc,tr,p,h,horizon=1)
    assert r['epochs'][0]['builds']['S']==pytest.approx(1e-5)
    assert r['epochs'][1]['builds'].get('S',0)==pytest.approx(0)
    assert r['epochs'][1]['capacity']['S']==pytest.approx(1e-5)


@pytest.mark.parametrize('units',['MW','kW','W'])
def test_capacity_unit_and_nested_package_invariance(units):
    sc,tr,p,h=joint_service_world(K=3)
    spec=simple_task_spec(sc)
    a=run_integrated_policy(sc,tr,p,h,spec,horizon=99)
    encoded,history=capacity_inputs(sc,h,{n:units for n in sc.designs},encode=True)
    b=run_integrated_policy(encoded,tr,p,history,spec,horizon=99,capacity_units={n:units for n in sc.designs},
                           selection=['all'],packages={'all':['lines'],'lines':list(sc.designs)})
    assert path_objective(tr,a)==pytest.approx(path_objective(tr,b),abs=1e-8)
    assert audit_integration_run(sc,h,spec,b)['passed']
    assert audit_need_run(sc,b)['passed']


@pytest.mark.parametrize('capacity',[1.,2.,None])
def test_acquisition_limit_restricts_service_route(capacity):
    sc,tr,p,h=joint_service_world(K=3)
    spec=simple_task_spec(sc,effort_capacity=capacity)
    r=run_integrated_policy(sc,tr,p,h,spec,horizon=99)
    assert audit_integration_run(sc,h,spec,r)['passed']
    assert audit_need_run(sc,r)['passed']
    assert independent_path_ledger(sc,tr,p,r)['path_objective']==pytest.approx(path_objective(tr,r))
    if capacity==1: assert fraction(r,'customer_A',0)+fraction(r,'customer_B',0)==0


def test_one_off_integration_charge_is_not_subtracted_twice():
    sc,tr,p,h=joint_service_world(K=3)
    spec=simple_task_spec(sc)
    spec=replace(spec,tasks={n:replace(t,completion_cost=.3) for n,t in spec.tasks.items()})
    r=run_integrated_policy(sc,tr,p,h,spec,horizon=99)
    assert r['epochs'][0]['integration_cost']==pytest.approx(.9)
    assert independent_path_ledger(sc,tr,p,r)['path_objective']==pytest.approx(r['window_objective'])


@pytest.mark.parametrize('empty',[None,NeedSystem()])
def test_disabled_recovers_original_problem(empty):
    sc,tr,p,h=joint_service_world(K=1)
    base=replace(sc,need_system=None);candidate=replace(sc,need_system=empty)
    a=solve(base,base.designs);b=solve(candidate,candidate.designs)
    assert a.objective==b.objective==0
    assert a.capacity==b.capacity


def test_optout_preserves_weak_improvement_of_adding_a_landscape_option():
    sc,tr,p,h=joint_service_world()
    v,r=value(sc,{},('SPUR_A','SPUR_B'),('TRUNK',))
    assert v==pytest.approx(3.)


def test_manifest_round_trip():
    sc,tr,p,h=small_world(K=3,benefit=(1.,5.,1.))
    assert NeedSystem.from_manifest(json.loads(json.dumps(sc.need_system.manifest())))==sc.need_system


def test_replay_does_not_trust_reported_benefit_or_cost():
    sc,tr,p,h=joint_service_world(K=3)
    r=exercise(sc,tr,p,h,horizon=99)
    truth=independent_path_ledger(sc,tr,p,r)
    for e in r['epochs']:
        e['ops_cost']=e['service_benefit']=-99
        nb=e['operating_states'][0]['flow']['needs'];nb['benefit']=-999
        for s in nb['services'].values():s['benefit']=s['value_of_full_profile']=-99
    replay=independent_path_ledger(sc,tr,p,r)
    assert replay['path_objective']==pytest.approx(truth['path_objective'])
    with pytest.raises(AssertionError):audit_need_run(sc,r)


@pytest.mark.parametrize('tamper',['quantity','fraction','eligibility','benefit','profile','epoch','nonfinite'])
def test_corrupted_need_records_rejected(tamper):
    sc,tr,p,h=small_world()
    r=exercise(sc,tr,p,h,horizon=99)
    q=r['epochs'][0]['operating_states'][0]['flow']['needs'];s=q['services']['extra']
    if tamper=='quantity':s['profiles'][0]['quantities'][0]+=1
    if tamper=='fraction':s['fraction']=.2
    if tamper=='eligibility':s['eligible']=False
    if tamper=='benefit':s['benefit']+=1
    if tamper=='profile':s['profiles'][0]['location']='unknown'
    if tamper=='epoch':q['epoch']=1
    if tamper=='nonfinite':s['profiles'][0]['delivered_rates'][0]=float('nan')
    with pytest.raises(AssertionError):audit_need_run(sc,r)


@pytest.mark.parametrize('changes',[{'value':-1.},{'value':float('inf')},{'value':(1.,)},
    {'scale':-1.},{'scale':()},{'mode':'unknown'},{'recognized_from':-1},{'recognized_from':1.5},
    {'expires_at':0},{'profiles':()},{'profiles':(ServiceProfile('unknown','D',(1.,)),)},
    {'profiles':(ServiceProfile('elec','unknown',(1.,)),)},
    {'profiles':(ServiceProfile('elec','D',(-1.,)),)},
    {'profiles':(ServiceProfile('elec','D',(0.,)),)},
    {'profiles':(ServiceProfile('elec','D',(1.,1.)),)}])
def test_invalid_need_rejected(changes):
    sc,tr,p,h=small_world(K=3)
    sc=replace(sc,need_system=NeedSystem((replace(sc.need_system.needs[0],**changes),)))
    with pytest.raises((ValueError,TypeError)):run_policy(sc,tr,p,h,horizon=99)


def test_duplicate_names_and_required_name_collision():
    sc,tr,p,h=small_world()
    with pytest.raises(ValueError):validate_needs(replace(sc,need_system=NeedSystem(sc.need_system.needs*2)))
    fs=replace(sc.flow_system,demands=(FlowDemand('extra','elec','D',(1.,)),))
    with pytest.raises(ValueError):validate_needs(replace(sc,flow_system=fs))


def test_missing_physical_registry_rejected():
    sc,tr,p,h=small_world()
    with pytest.raises(ValueError):validate_needs(replace(sc,flow_system=None))


@pytest.mark.parametrize('mode',['contingency','stochastic'])
def test_optional_service_composes_with_uncertainty(mode):
    sc,tr,p,h=small_world()
    if mode=='contingency':
        r=solve_window(sc,tr,p,0,0,h,contingencies=[{'name':'stress','p':.1}])
        assert len(r['epochs'][0]['operating_states'])==2
        expected=sum(s['probability']*s['flow']['needs']['benefit'] for s in r['epochs'][0]['operating_states'])
        assert r['epochs'][0]['service_benefit']==pytest.approx(expected)
    else:
        r=solve_window_stochastic(sc,[tr,tr],[.5,.5],p,0,0,h)
        assert len(r['scenarios'])==2
        assert all(x['epochs'][0]['operating_states'][0]['flow']['needs']['benefit']>=0 for x in r['scenarios'])


def test_fabricated_optional_delivery_is_rejected_by_physical_audit():
    sc,tr,p,h=small_world(cap=0.,benefit=100.)
    r=exercise(sc,tr,p,h,horizon=99)
    state=r['epochs'][0]['operating_states'][0]
    nb=state['flow']['needs'];s=nb['services']['extra']
    s['fraction']=1.;s['benefit']=100.;nb['benefit']=100.
    s['profiles'][0]['delivered_rates']=[1.];s['profiles'][0]['quantities']=[1.]
    assert audit_need_block(sc,nb)['passed']  # A consistent service claim is not a physical proof.
    with pytest.raises(AssertionError):audit_operating_state(sc,state)


@pytest.mark.parametrize('currency_factor',[.1,1000.])
def test_currency_change_preserves_uptake(currency_factor):
    sc,tr,p,h=joint_service_world()
    original=solve(sc,sc.designs)
    f=currency_factor
    ds={n:replace(d,annual_cost=d.annual_cost*f,fixed_cost=d.fixed_cost*f,var_cost=d.var_cost*f)
        for n,d in sc.designs.items()}
    fs=replace(sc.flow_system,resources=tuple(replace(r,unit_cost=r.unit_cost*f) for r in sc.flow_system.resources))
    ns=NeedSystem(tuple(replace(n,value=n.value*f) for n in sc.need_system.needs))
    changed=solve(replace(sc,designs=ds,flow_system=fs,need_system=ns,voll=sc.voll*f),sc.designs)
    assert changed.objective==pytest.approx(original.objective*f)
    assert changed.capacity==pytest.approx(original.capacity)


def test_need_labels_do_not_change_physical_choices():
    sc,tr,p,h=joint_service_world()
    a=solve(sc,sc.designs)
    ns=NeedSystem(tuple(replace(n,name='alias_'+str(i)) for i,n in enumerate(sc.need_system.needs)))
    b=solve(replace(sc,need_system=ns),sc.designs)
    assert a.objective==b.objective and a.capacity==b.capacity


def test_indivisible_service_intermediate_fraction_is_rejected():
    sc,tr,p,h=small_world(mode='indivisible')
    r=exercise(sc,tr,p,h,horizon=99);nb=r['epochs'][0]['operating_states'][0]['flow']['needs'];s=nb['services']['extra']
    s['fraction']=.5;s['profiles'][0]['delivered_rates']=[.5];s['profiles'][0]['quantities']=[.5]
    with pytest.raises(AssertionError,match='Indivisible'):replay_need_block(sc,nb)


def test_optional_value_does_not_override_a_required_multiform_obligation():
    sc,tr,p,h=small_world(cap=1.,benefit=100.)
    fs=replace(sc.flow_system,demands=(FlowDemand('required_electricity','elec','D',(1.,),hard=True),))
    r=exercise(replace(sc,flow_system=fs),tr,p,h,horizon=99)
    assert fraction(r)==0
    assert r['epochs'][0]['unmet_MWh']==0
