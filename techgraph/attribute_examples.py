"""Declared synthetic service-attribute worlds, not measured quality technologies."""
from dataclasses import replace
from .catalog import Design, Scenario
from .flows import FlowSystem, FlowDemand, FlowResource, Port, Destination
from .needs import OptionalNeed, ServiceProfile, NeedSystem
from .attributes import (AttributeDefinition, FormVariant, NumericLimit,
                         RequirementStage, ServiceRequirement, AttributeSystem)
from .dynamic import Trajectory, Params, Vintage
from .stocks import StockSystem, StockSpec
from .integration import IntegrationSpec, IntegrationTask, DeploymentRequirement
from .representation import Capacity


def quality_world(*, K=6, change_at=2, minimum=.98, aggregation='each', upgrade=False,
                  upgrade_cost=.6, upgrade_yield=.9, optional=False, value=12.,
                  secondary=False, new_cost=3., certified_only=False):
    """10 tonnes per one-hour block; quality, not quantity, changes at change_at."""
    definitions={'assay':AttributeDefinition('numeric','fraction',allow_average=True),
                 'certificate':AttributeDefinition('categorical')}
    variants={'low':FormVariant('product',{'assay':.9},{'certificate':'unverified'}),
              'high':FormVariant('product',{'assay':1.},{'certificate':'verified'})}
    first=RequirementStage(0,(NumericLimit('assay',lower=.8,aggregation=aggregation),))
    final=RequirementStage(change_at or 0,(NumericLimit('assay',lower=minimum,aggregation=aggregation),),
                           {'certificate':('verified',)} if certified_only else {})
    stages=(first,) if change_at is None else (final,) if change_at==0 else (first,final)
    attrs=AttributeSystem(definitions,variants,{
        'primary':ServiceRequirement('product',('low','high'),stages),
        'secondary':ServiceRequirement('product',('low','high'),(first,))})
    designs={
        'OLD':Design('OLD','process',87.6,var_cost=1.,activity_unit='tonne/h',max_cap=100,
                     input_ports=(Port('feed','S'),),output_ports=(Port('low','S'),),conserve_mass=True),
        'CORRIDOR':Design('CORRIDOR','process',43.8,var_cost=.05,activity_unit='tonne/h',max_cap=100,
                          input_ports=(Port('low','S'),),output_ports=(Port('low','D'),),conserve_mass=True),
        'NEW':Design('NEW','process',876.,var_cost=new_cost,activity_unit='tonne/h',max_cap=100,
                     input_ports=(Port('feed','D'),),output_ports=(Port('high','D'),),conserve_mass=True),
        'DISPOSE':Design('DISPOSE','sink',8.76,var_cost=.1,activity_unit='tonne/h',form='waste',loc='D',
                         destination='inert',max_cap=100),
    }
    if upgrade:
        designs['UPGRADE']=Design('UPGRADE','process',87.6,var_cost=upgrade_cost,activity_unit='tonne/h',max_cap=100,
                         input_ports=(Port('low','D'),),
                         output_ports=(Port('high','D',upgrade_yield),Port('waste','D',1-upgrade_yield)),conserve_mass=True)
    base={'fuel':'MWh','elec':'MWh','h2':'MWh','feed':'tonne','product':'tonne','low':'tonne','high':'tonne','waste':'tonne'}
    demands=() if optional else (FlowDemand('primary_service','product','D',(10.,),scale_with_demand=False,attribute_requirement='primary'),)
    needs=[]
    if optional:needs.append(OptionalNeed('primary_optional',(ServiceProfile('product','D',(10.,),'primary'),),value))
    if secondary:needs.append(OptionalNeed('secondary_optional',(ServiceProfile('product','D',(5.,),'secondary'),),10.))
    fs=FlowSystem(base,demands=demands,destinations={'inert':Destination('tonne','disposal',bearer='declared disposal account')},
                  resources=(FlowResource('feed_S','feed','S',(200.,)),FlowResource('feed_D','feed','D',(200.,))))
    sc=Scenario(periods=1,hours=1.,days=1/24,demand_D=[0.],hub_energy=0.,hub_max_rate=0.,profiles={},
                fuel_price_R=0.,voll=3000.,designs=designs,locations=('S','D'),fuel_sites=(),flow_system=fs,
                attribute_system=attrs,need_system=NeedSystem(tuple(needs)) if needs else None)
    tr=Trajectory(K,[0.]*K,[1.]*K,discount=.93)
    prm=Params({n:20 for n in designs},aging=0.)
    history=[Vintage(n,-2,10.,10.,designs[n].annual_cost,designs[n].fixed_cost,20) for n in ['OLD','CORRIDOR']]
    return sc,tr,prm,history


def integration_quality_world(*, K=5, change_at=2):
    sc,tr,p,h=quality_world(K=K,change_at=change_at)
    designs=dict(sc.designs)
    designs['NEW']=replace(designs['NEW'],input_ports=(Port('feed','S'),),output_ports=(Port('high','S'),))
    designs['HIGH_LINE']=Design('HIGH_LINE','process',43.8,activity_unit='tonne/h',max_cap=100,
                               input_ports=(Port('high','S'),),output_ports=(Port('high','D'),),conserve_mass=True)
    sc=replace(sc,designs=designs);p=replace(p,life={n:20 for n in designs})
    tasks={n:IntegrationTask(1.,description=n+' introduction') for n in designs}
    deployments={n:DeploymentRequirement((n,),Capacity(10.,'tonne/h'),.1) for n in designs}
    spec=IntegrationSpec(tasks,deployments,capacity=1.,infer_from_history=True)
    return sc,tr,p,h,spec


def inherited_quality_world(*, K=1, strict=True, upgrade=False, initial=10.):
    sc,tr,p,h=quality_world(K=K,change_at=0 if strict else None,upgrade=upgrade)
    # Inherited material keeps its low-grade form. No new low-grade producer.
    designs={n:d for n,d in sc.designs.items() if n not in {'OLD','CORRIDOR'}}
    designs['DEPOSIT']=Design('DEPOSIT','sink',0.,activity_unit='tonne/h',form='low',loc='D',destination='pile',max_cap=100)
    designs['WITHDRAW']=Design('WITHDRAW','withdraw',0.,activity_unit='tonne/h',form='low',loc='D',destination='pile',max_cap=100)
    fs=replace(sc.flow_system,destinations={**sc.flow_system.destinations,
              'pile':Destination('tonne','stock',initial_stock=initial,bearer='stored low-grade material')})
    sc=replace(sc,designs=designs,flow_system=fs);p=replace(p,life={n:20 for n in designs})
    stocks=StockSystem({'pile':StockSpec('low','D',capacity=20.)},block_weights=(1.,)*K)
    return sc,tr,p,[],stocks
