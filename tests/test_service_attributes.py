"""Acceptance and adversarial checks for the explicit attribute-service interface."""
from dataclasses import replace
from copy import deepcopy
import json
import pytest
from techgraph.attributes import (AttributeDefinition,FormVariant,NumericLimit,RequirementStage,
    ServiceRequirement,AttributeSystem,admissibility,audit_attribute_run,audit_attribute_delivery,validate_attributes)
from techgraph.attribute_examples import quality_world,integration_quality_world,inherited_quality_world
from techgraph.catalog import default_scenario
from techgraph.needs import NeedSystem,OptionalNeed,ServiceProfile,audit_need_run
from techgraph.flows import FlowDemand,FlowResource,Port,audit_flow_block
from techgraph.dynamic import run_policy,solve_window,solve_window_stochastic,path_objective,path_benefit
from techgraph.model import solve,check_balances
from techgraph.flow_audit import audit_operating_state
from techgraph.accounting import independent_path_ledger
from techgraph.stocks import audit_stock_run
from techgraph.integration import run_integrated_policy,audit_integration_run
from techgraph.integration_examples import relabel
from techgraph.representation import capacity_inputs


def exercise(args,horizon=99,**kwargs):
    sc,tr,p,h=args[:4]
    r=run_policy(sc,tr,p,h,horizon=horizon,**kwargs)
    assert audit_attribute_run(sc,r,trajectory=tr)['passed']
    if sc.need_system is not None:assert audit_need_run(sc,r)['passed']
    for e in r['epochs']:
        for state in e['operating_states']:
            assert audit_flow_block(sc,state['flow'],e['capacity'])['passed']
            assert audit_operating_state(sc,state)['passed']
    ledger=independent_path_ledger(sc,tr,p,r)
    assert ledger['path_objective']==pytest.approx(path_objective(tr,r),abs=1e-6)
    if r['status']=='Optimal':assert ledger['path_objective']==pytest.approx(r['window_objective'],abs=1e-6)
    return r


def delivered(r,k=0,name='primary_service'):
    return r['epochs'][k]['operating_states'][0]['flow']['demands'][name]['attributes']['allocations']


def optional_fraction(r,k=0):
    return r['epochs'][k]['operating_states'][0]['flow']['needs']['services']['primary_optional']['fraction']


@pytest.mark.parametrize('horizon',[1,2,99])
def test_attribute_shock_changes_route_without_quantity_or_price_change(horizon):
    args=quality_world();r=exercise(args,horizon)
    assert [e['throughput']['OLD'] for e in r['epochs']]==pytest.approx([10,10,0,0,0,0])
    assert [e['throughput']['NEW'] for e in r['epochs']]==pytest.approx([0,0,10,10,10,10])
    assert all(sum(sum(v) for v in delivered(r,k).values())==pytest.approx(10) for k in range(6))
    assert args[1].avail_from=={} and args[1].cost_mult=={}


@pytest.mark.parametrize('horizon',[1,99])
def test_unchanged_requirement_preserves_old_route(horizon):
    r=exercise(quality_world(change_at=None),horizon)
    assert [e['throughput']['OLD'] for e in r['epochs']]==pytest.approx([10]*6)


@pytest.mark.parametrize('horizon',[1,99])
def test_upgrade_preserves_existing_route_but_accounts_for_residue(horizon):
    r=exercise(quality_world(upgrade=True),horizon)
    for k in range(2,6):
        e=r['epochs'][k]
        assert e['throughput']['OLD']==pytest.approx(10/.9)
        assert e['throughput']['UPGRADE']==pytest.approx(10/.9)
        assert e['throughput']['NEW']==pytest.approx(0)
        assert e['operating_states'][0]['flow']['destinations']['inert']['quantity']==pytest.approx(10/9)
        assert delivered(r,k)['high']==pytest.approx([10])


@pytest.mark.parametrize('minimum',[.8,.9,.925,.95,.98,1.])
@pytest.mark.parametrize('mode',['each','average'])
def test_each_and_mean_semantics(minimum,mode):
    r=exercise(quality_world(K=1,change_at=0,minimum=minimum,aggregation=mode))
    expected=0 if minimum<=.9 else 10 if mode=='each' else 10*(minimum-.9)/.1
    assert delivered(r)['high'][0]==pytest.approx(expected,abs=1e-6)


def test_upper_numeric_limit_and_mean_have_opposite_orientation():
    sc,tr,p,h=quality_world(K=1,change_at=0,new_cost=.1)
    for mode in ['each','average']:
        req=replace(sc.attribute_system.requirements['primary'],stages=(RequirementStage(0,(NumericLimit('assay',upper=.95,aggregation=mode),)),))
        s=replace(sc,attribute_system=replace(sc.attribute_system,requirements={'primary':req}))
        r=exercise((s,tr,p,h))
        assert delivered(r)['high'][0]==pytest.approx(0 if mode=='each' else 5)


def test_category_cannot_be_offset_by_a_high_average():
    r=exercise(quality_world(K=1,change_at=0,minimum=.95,aggregation='average',certified_only=True))
    assert delivered(r)['high']==pytest.approx([10])
    assert delivered(r)['low']==pytest.approx([0])


@pytest.mark.parametrize('field',['numeric','categorical'])
@pytest.mark.parametrize('mode',['each','average'])
def test_unknown_required_attribute_is_not_assumed_favorable(field,mode):
    sc,tr,p,h=quality_world(K=1,change_at=0,minimum=.8,aggregation=mode,certified_only=field=='categorical')
    # Make low supply otherwise acceptable, but remove a required property.
    low=replace(sc.attribute_system.variants['low'],categorical={'certificate':'verified'})
    low=replace(low,**{field:{}})
    s=replace(sc,attribute_system=replace(sc.attribute_system,variants={**sc.attribute_system.variants,'low':low}))
    r=exercise((s,tr,p,h))
    assert delivered(r)['low']==pytest.approx([0])
    assert delivered(r)['high']==pytest.approx([10])


@pytest.mark.parametrize('horizon',[1,99])
def test_new_requirement_does_not_apply_to_other_service(horizon):
    r=exercise(quality_world(secondary=True),horizon)
    assert [e['throughput']['OLD'] for e in r['epochs']]==pytest.approx([15,15,5,5,5,5])
    for k in range(2,6):
        assert delivered(r,k)['low']==pytest.approx([0])
        service=r['epochs'][k]['operating_states'][0]['flow']['needs']['services']['secondary_optional']
        assert service['profiles'][0]['attributes']['allocations']['low']==pytest.approx([5])


@pytest.mark.parametrize('value,last_fraction',[(12.,0.),(40.,1.)])
@pytest.mark.parametrize('mode',['divisible','indivisible'])
def test_optional_acceptance_does_not_relax_quality(value,last_fraction,mode):
    sc,tr,p,h=quality_world(optional=True,value=value)
    sc=replace(sc,need_system=NeedSystem((replace(sc.need_system.needs[0],mode=mode),)))
    r=exercise((sc,tr,p,h),1)
    assert optional_fraction(r,0)==pytest.approx(1)
    assert optional_fraction(r,2)==pytest.approx(last_fraction)
    assert all(e['unmet_MWh']==0 for e in r['epochs'])


def test_absent_qualified_route_is_infeasible_for_hard_need_but_optional_can_decline():
    sc,tr,p,h=quality_world(K=1,change_at=0)
    with pytest.raises(RuntimeError,match='Infeasible'):
        run_policy(sc,tr,p,h,horizon=99,forbid=('NEW',))
    sc,tr,p,h=quality_world(K=1,change_at=0,optional=True,value=10000.)
    r=exercise((sc,tr,p,h),forbid=('NEW',))
    assert optional_fraction(r)==pytest.approx(0)
    assert path_benefit(tr,r)==0


def test_soft_service_may_shortfall_but_never_accept_invalid_delivery():
    sc,tr,p,h=quality_world(K=1,change_at=0)
    sc=replace(sc,flow_system=replace(sc.flow_system,demands=(replace(sc.flow_system.demands[0],hard=False,penalty=.1),)))
    r=exercise((sc,tr,p,h),forbid=('NEW',))
    demand=r['epochs'][0]['operating_states'][0]['flow']['demands']['primary_service']
    assert demand['unmet_rates']==pytest.approx([10])
    assert delivered(r)['low']==pytest.approx([0])


def test_zero_optional_delivery_has_no_defined_average():
    r=exercise(quality_world(K=1,change_at=0,minimum=.95,aggregation='average',optional=True,value=0.))
    attr=r['epochs'][0]['operating_states'][0]['flow']['needs']['services']['primary_optional']['profiles'][0]['attributes']
    assert attr['averages']['assay']==[None]


@pytest.mark.parametrize('optional',[False,True])
def test_quality_cannot_be_borrowed_from_a_later_period(optional):
    sc,tr,p,h=quality_world(K=1,change_at=0,minimum=.95,aggregation='average',optional=optional,value=1000.)
    # Whole-block average would be .95, but first-period service is unacceptable.
    fs=replace(sc.flow_system,resources=(FlowResource('early','low','D',(10.,0.)),FlowResource('late','high','D',(0.,10.))))
    ns=sc.need_system
    if optional:ns=NeedSystem((replace(ns.needs[0],profiles=(ServiceProfile('product','D',(10.,10.),'primary'),)),))
    else:fs=replace(fs,demands=(replace(fs.demands[0],rates=(10.,10.)),))
    sc=replace(sc,periods=2,days=2/24,demand_D=[0.,0.],designs={},flow_system=fs,need_system=ns)
    p=replace(p,life={})
    if optional:
        r=exercise((sc,tr,p,[]));assert optional_fraction(r)==pytest.approx(0)
    else:
        with pytest.raises(RuntimeError,match='Infeasible'):run_policy(sc,tr,p,[],horizon=99)


@pytest.mark.parametrize('strict,upgrade,withdraw,high_new',[(False,False,10,0),(True,False,0,10),(True,True,10,1)])
def test_old_stock_keeps_its_attributes(strict,upgrade,withdraw,high_new):
    args=inherited_quality_world(strict=strict,upgrade=upgrade)
    sc,tr,p,h,stocks=args;r=exercise(args,stocks=stocks)
    assert audit_stock_run(sc,stocks,r)['passed']
    assert r['epochs'][0]['throughput']['WITHDRAW']==pytest.approx(withdraw)
    assert r['epochs'][0]['throughput']['NEW']==pytest.approx(high_new)
    assert r['epochs'][0]['stocks']['pile']['stock_end']==pytest.approx(10-withdraw)


@pytest.mark.parametrize('horizon',[2,99])
def test_anticipation_can_stage_before_a_quality_deadline(horizon):
    sc,tr,p,h,spec=integration_quality_world()
    r=exercise((sc,tr,p,h),horizon,integration=spec)
    assert audit_integration_run(sc,h,spec,r)['passed']
    assert r['epochs'][1]['builds']['HIGH_LINE']==pytest.approx(1)
    assert r['epochs'][2]['builds']['NEW']==pytest.approx(10)
    assert [e['integration']['effort'] for e in r['epochs']]==pytest.approx([0,1,1,0,0])


def test_short_horizon_can_run_out_of_feasible_qualification_actions():
    sc,tr,p,h,spec=integration_quality_world()
    with pytest.raises(RuntimeError,match='Infeasible'):
        run_policy(sc,tr,p,h,horizon=1,integration=spec)
    r=exercise((sc,tr,p,h),1,integration=replace(spec,capacity=None))
    assert delivered(r,2)['high']==pytest.approx([10])


def test_static_expectations_do_not_hide_known_structural_standard():
    args=quality_world()
    a=exercise(args,3,expectations='true');b=exercise(args,3,expectations='static')
    assert path_objective(args[1],a)==pytest.approx(path_objective(args[1],b))
    assert delivered(b,2)['high']==pytest.approx([10])


def test_requirement_relaxation_does_not_permanently_ban_the_old_design():
    sc,tr,p,h=quality_world()
    req=sc.attribute_system.requirements['primary']
    req=replace(req,stages=req.stages+(RequirementStage(4,(NumericLimit('assay',lower=.8),)),))
    sc=replace(sc,attribute_system=replace(sc.attribute_system,requirements={**sc.attribute_system.requirements,'primary':req}))
    r=exercise((sc,tr,p,h))
    assert [e['throughput']['OLD'] for e in r['epochs']]==pytest.approx([10,10,0,0,10,10])


@pytest.mark.parametrize('epoch',[0,2])
@pytest.mark.parametrize('mode',['each','average'])
@pytest.mark.parametrize('optional',[False,True])
def test_static_dynamic_equivalence(epoch,mode,optional):
    sc,tr,p,h=quality_world(aggregation=mode,optional=optional,value=40.)
    a=solve(sc,sc.designs,need_epoch=epoch,attribute_epoch=epoch)
    b=solve_window(sc,tr,p,epoch,epoch,[])
    assert a.objective==pytest.approx(b['objective']/tr.discount**epoch,abs=1e-7)
    assert not check_balances(sc,a)
    assert audit_flow_block(sc,a.flow,a.capacity)['passed']


@pytest.mark.parametrize('unit',['tonne/h','kg/h'])
@pytest.mark.parametrize('wrapped',[False,True])
def test_units_and_lossless_packages_do_not_change_acceptance(unit,wrapped):
    sc,tr,p,h,spec=integration_quality_world()
    a=run_integrated_policy(sc,tr,p,h,spec,horizon=99)
    enc,hh=capacity_inputs(sc,h,{n:unit for n in sc.designs},encode=True)
    opts={'selection':['wrapped'],'packages':{'wrapped':['all'],'all':list(sc.designs)}} if wrapped else {}
    b=run_integrated_policy(enc,tr,p,hh,spec,horizon=99,capacity_units={n:unit for n in sc.designs},**opts)
    assert audit_attribute_run(sc,b,trajectory=tr)['passed']
    assert path_objective(tr,a)==pytest.approx(path_objective(tr,b),abs=1e-8)
    assert delivered(a,2)==delivered(b,2)


def test_design_relabeling_preserves_declared_variant_identity():
    sc,tr,p,h,spec=integration_quality_world()
    args=relabel(sc,tr,p,h,spec,{n:'x_'+n for n in sc.designs})
    a=run_integrated_policy(sc,tr,p,h,spec,horizon=99)
    b=run_integrated_policy(*args,horizon=99)
    assert path_objective(tr,a)==pytest.approx(path_objective(args[1],b))
    assert delivered(a,2)==delivered(b,2)


@pytest.mark.parametrize('field',['average','epoch','eligibility','quantity','missing'])
def test_fabricated_attribute_record_is_rejected(field):
    sc,tr,p,h=quality_world(K=1,change_at=0,minimum=.95,aggregation='average')
    r=exercise((sc,tr,p,h));rec=r['epochs'][0]['operating_states'][0]['flow']['demands']['primary_service']
    a=rec['attributes']
    if field=='average':a['averages']['assay'][0]=1.
    elif field=='epoch':a['epoch']=2
    elif field=='eligibility':a['rejected_candidates']['low']=['fake']
    elif field=='quantity':a['quantities']['high'][0]=0
    else:del rec['attributes']
    with pytest.raises(AssertionError):audit_attribute_run(sc,r,trajectory=tr)


def test_saved_target_cannot_be_changed_to_erase_required_service():
    sc,tr,p,h=quality_world(K=1);r=exercise((sc,tr,p,h))
    r['epochs'][0]['operating_states'][0]['flow']['demands']['primary_service']['target_rates']=[0.]
    with pytest.raises(AssertionError,match='target'):audit_attribute_run(sc,r,trajectory=tr)


def test_service_qualification_alone_does_not_prove_physical_supply():
    sc,tr,p,h=quality_world(K=1,change_at=0);r=exercise((sc,tr,p,h))
    e=r['epochs'][0];state=e['operating_states'][0]
    state['physical']['activities']['NEW']['activity']=[0.]
    assert audit_attribute_run(sc,r,trajectory=tr)['passed']
    with pytest.raises(AssertionError):audit_operating_state(sc,state)


def test_no_double_counting_one_physical_batch_for_two_qualified_services():
    sc,tr,p,h=quality_world(K=1,change_at=0,optional=True,value=100)
    sc=replace(sc,designs={},flow_system=replace(sc.flow_system,resources=(FlowResource('supply','high','D',(10.,)),)),
        need_system=NeedSystem((sc.need_system.needs[0],replace(sc.need_system.needs[0],name='other'))))
    p=replace(p,life={});r=exercise((sc,tr,p,[]))
    ss=r['epochs'][0]['operating_states'][0]['flow']['needs']['services']
    assert sum(s['fraction'] for s in ss.values())==pytest.approx(1.)


def test_manifest_round_trip_preserves_requirements_and_profiles():
    sc,*_=quality_world(optional=True,aggregation='average')
    assert AttributeSystem.from_manifest(json.loads(json.dumps(sc.attribute_system.manifest())))==sc.attribute_system
    assert NeedSystem.from_manifest(json.loads(json.dumps(sc.need_system.manifest())))==sc.need_system


@pytest.mark.parametrize('empty',[None,AttributeSystem()])
def test_disabled_recovers_legacy_world(empty):
    sc=default_scenario();a=solve(sc,sc.designs)
    # Empty metadata does not activate any qualified service and should be harmless.
    b=solve(replace(sc,attribute_system=empty),sc.designs)
    assert a.objective==pytest.approx(b.objective)


@pytest.mark.parametrize('optional',[False,True])
def test_attribute_services_compose_with_contingency_and_stochastic_paths(optional):
    sc,tr,p,h=quality_world(optional=optional)
    a=solve_window(sc,tr,p,0,1,h,contingencies=[{'name':'test','p':.1,'fail':['OLD']}])
    assert len(a['epochs'][0]['operating_states'])==2
    assert audit_attribute_run(sc,{'epochs':[a['epochs'][0],a['epochs'][1]]},trajectory=tr)['passed']
    b=solve_window_stochastic(sc,[tr,tr],[.5,.5],p,0,2,h)
    assert len(b['scenarios'])==2
    for path in b['scenarios']:
        assert audit_attribute_run(sc,{'epochs':[path['epochs'][k] for k in range(3)]},trajectory=tr)['passed']


def test_small_qualified_service_builds_are_retained_in_rolling_history():
    sc,tr,p,h=quality_world(K=2,change_at=0)
    sc=replace(sc,flow_system=replace(sc.flow_system,demands=(replace(sc.flow_system.demands[0],rates=(1e-5,)),)))
    r=exercise((sc,tr,p,[]),1)
    assert r['epochs'][0]['builds']['NEW']==pytest.approx(1e-5)
    assert r['epochs'][1]['builds'].get('NEW',0)==pytest.approx(0)


@pytest.mark.parametrize('case',[
    'no_system','bad_family','missing_variant','wrong_unit','unknown_definition','nonfinite',
    'negative_epoch','missing_stage_zero','duplicate_stage','duplicate_candidate',
    'forbidden_average','categorical_average','missing_bound','reversed_bound','wrong_aggregation',
    'unknown_category','empty_category','bare_string_category','unknown_requirement','wrong_profile_family'])
def test_invalid_attribute_declarations_fail_closed(case):
    sc,tr,p,h=quality_world(K=1,change_at=0)
    a=sc.attribute_system;r=a.requirements['primary'];s=r.stages[0]
    if case=='no_system':a=None
    elif case=='bad_family':a=replace(a,variants={**a.variants,'low':replace(a.variants['low'],family='absent')})
    elif case=='missing_variant':r=replace(r,candidates=('absent',))
    elif case=='wrong_unit':a=replace(a,variants={**a.variants,'fuel':FormVariant('product')})
    elif case=='unknown_definition':a=replace(a,variants={**a.variants,'low':replace(a.variants['low'],numeric={'absent':1.})})
    elif case=='nonfinite':a=replace(a,variants={**a.variants,'low':replace(a.variants['low'],numeric={'assay':float('nan')})})
    elif case=='negative_epoch':r=replace(r,stages=(replace(s,from_epoch=-1),))
    elif case=='missing_stage_zero':r=replace(r,stages=(replace(s,from_epoch=1),))
    elif case=='duplicate_stage':r=replace(r,stages=(s,s))
    elif case=='duplicate_candidate':r=replace(r,candidates=('low','low'))
    elif case=='forbidden_average':
        a=replace(a,definitions={**a.definitions,'assay':replace(a.definitions['assay'],allow_average=False)})
        r=replace(r,stages=(replace(s,numeric=(NumericLimit('assay',lower=.95,aggregation='average'),)),))
    elif case=='categorical_average':a=replace(a,definitions={**a.definitions,'certificate':AttributeDefinition('categorical',allow_average=True)})
    elif case=='missing_bound':r=replace(r,stages=(replace(s,numeric=(NumericLimit('assay'),)),))
    elif case=='reversed_bound':r=replace(r,stages=(replace(s,numeric=(NumericLimit('assay',lower=2,upper=1),)),))
    elif case=='wrong_aggregation':r=replace(r,stages=(replace(s,numeric=(NumericLimit('assay',lower=.9,aggregation='mystery'),)),))
    elif case=='unknown_category':r=replace(r,stages=(replace(s,categories={'absent':('yes',)}),))
    elif case=='empty_category':r=replace(r,stages=(replace(s,categories={'certificate':()}),))
    elif case=='bare_string_category':r=replace(r,stages=(replace(s,categories={'certificate':'verified'}),))
    elif case=='unknown_requirement':sc=replace(sc,flow_system=replace(sc.flow_system,demands=(replace(sc.flow_system.demands[0],attribute_requirement='missing'),)))
    elif case=='wrong_profile_family':sc=replace(sc,flow_system=replace(sc.flow_system,demands=(replace(sc.flow_system.demands[0],form='low'),)))
    if a is not None:a=replace(a,requirements={**a.requirements,'primary':r})
    sc=replace(sc,attribute_system=a)
    with pytest.raises((ValueError,TypeError)):solve(sc,sc.designs)


def test_scaled_qualified_requirement_audits_against_actual_trajectory():
    sc,tr,p,h=quality_world(K=3,change_at=1)
    sc=replace(sc,flow_system=replace(sc.flow_system,demands=(replace(sc.flow_system.demands[0],scale_with_demand=True),)))
    tr=replace(tr,demand_mult=[1.,1.5,2.])
    r=exercise((sc,tr,p,h),1)
    assert delivered(r,2)['high']==pytest.approx([20.])
    with pytest.raises(ValueError,match='trajectory'):audit_attribute_run(sc,r)


def test_qualified_optional_multi_component_bundle_cannot_drop_a_component():
    sc,tr,p,h=quality_world(K=1,change_at=0,optional=True,value=1000.)
    profiles=(ServiceProfile('product','D',(10.,),'primary'), ServiceProfile('product','S',(10.,),'primary'))
    sc=replace(sc,need_system=NeedSystem((replace(sc.need_system.needs[0],profiles=profiles),)))
    # Qualified high-grade supply exists only at D, and there is no route back to S.
    r=exercise((sc,tr,p,h))
    assert optional_fraction(r)==pytest.approx(0.)


def test_per_unit_definition_rejects_average_at_no_delivery_as_well():
    sc,tr,p,h=quality_world(K=1,change_at=0,optional=True,value=0.)
    attr=replace(sc.attribute_system,definitions={**sc.attribute_system.definitions,
                 'assay':AttributeDefinition('numeric','fraction',allow_average=False)})
    req=replace(attr.requirements['primary'],stages=(RequirementStage(0,(NumericLimit('assay',lower=.95,aggregation='average'),)),))
    sc=replace(sc,attribute_system=replace(attr,requirements={**attr.requirements,'primary':req}))
    with pytest.raises(ValueError,match='Averaging'):run_policy(sc,tr,p,h,horizon=99)
