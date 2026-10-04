"""Small declared verification worlds for optional service and joint demand.

Costs are representative-block model units; preferences and technologies are
synthetic. Candidate need recognition and actual uptake are different events.
"""
from dataclasses import replace
from .catalog import Scenario, Design
from .flows import FlowSystem, FlowDemand, FlowResource, Destination, Port
from .needs import NeedSystem, OptionalNeed, ServiceProfile
from .dynamic import Trajectory, Params, Vintage
from .stock_examples import residual_world
from .integration import IntegrationSpec, IntegrationTask, DeploymentRequirement
from .representation import Capacity, canonical_unit


def joint_service_world(*, K=1, customers=('A','B'), values=(8.,8.), trunk_cost=10.,
                        mode='indivisible', cheap_at=None, recognize_b=0):
    # One-hour block. The main line's fixed annual equivalent is 10/block;
    # two independent demand profiles share it, rather than being forced jointly.
    ds=[Design('TRUNK','transport',0.0,fixed_cost=trunk_cost*8760,form='elec',
               loc_from='R',loc_to='H',max_cap=2),
        Design('SPUR_A','transport',.5*8760,form='elec',loc_from='H',loc_to='D',max_cap=1),
        Design('SPUR_B','transport',.5*8760,form='elec',loc_from='H',loc_to='B',max_cap=1)]
    fs=FlowSystem(resources=(FlowResource('upstream_supply','elec','R',(4.,),unit_cost=1.0),),hard_legacy_service=True)
    ns=NeedSystem(tuple(OptionalNeed(f'customer_{name}',(ServiceProfile('elec',loc,(1.,)),),v,mode=mode,
                                      recognized_from=recognize_b if name=='B' else 0)
                        for name,loc,v in [('A','D',values[0]),('B','B',values[1])] if name in customers))
    if cheap_at is not None:
        ds.append(replace(ds[0],name='CHEAPER_TRUNK',fixed_cost=10.*8760))
    sc=Scenario(periods=1,hours=1.,days=1./24.,demand_D=[0.],hub_energy=0.,hub_max_rate=0.,
        profiles={},fuel_price_R=0.,voll=3000.,designs={d.name:d for d in ds},
        locations=('R','H','D','B'),fuel_sites=(),flow_system=fs,need_system=ns)
    tr=Trajectory(K,[0.]*K,[1.]*K,avail_from={} if cheap_at is None else {'CHEAPER_TRUNK':cheap_at},discount=.93)
    prm=Params({n:10 for n in sc.designs},aging=0.)
    return sc,tr,prm,[]


def efficiency_need_world(*, K=5, arrival=2, optional=True, new_efficiency=.5,
                          values=(3.,2.5,1.5), value_multiplier=1.0):
    def generator(name,eff):
        return Design(name,'process',8.76,input_ports=(Port('fuel','D'),),
            output_ports=(Port('elec','D',eff),Port('residual_heat','D',1-eff)),
            activity_unit='MW',conserve_energy=True,max_cap=100)
    ds=[generator('OLD',.25),generator('NEW',new_efficiency),
        Design('HEAT_RELEASE','sink',8.76,form='residual_heat',loc='D',
               destination='ambient',activity_unit='MW',max_cap=100)]
    fs=FlowSystem(form_units={'fuel':'MWh','elec':'MWh','h2':'MWh','residual_heat':'MWh'},
                  destinations={'ambient':Destination('MWh')},hard_legacy_service=True)
    needs=NeedSystem(tuple(OptionalNeed(f'additional_service_{i+1}',(ServiceProfile('elec','D',(1.,)),),
                                         value_multiplier*v) for i,v in enumerate(values))) if optional else None
    sc=Scenario(periods=1,hours=1.,days=1./24.,demand_D=[1.],hub_energy=0.,hub_max_rate=0.,
                profiles={},fuel_price_R=1.,voll=3000.,designs={d.name:d for d in ds},
                locations=('D',),fuel_sites=('D',),flow_system=fs,need_system=needs)
    tr=Trajectory(K,[1.]*K,[1.]*K,avail_from={'NEW':arrival},discount=.93)
    prm=Params({n:20 for n in sc.designs},aging=0.)
    history=[Vintage('OLD',-1,4.,4.,ds[0].annual_cost,0,20)]
    return sc,tr,prm,history


def residual_demand_world(*, K=6, value=8.0, capacity=5.):
    sc,tr,p,h,stocks=residual_world(K=K,capacity=capacity)
    sc=replace(sc,need_system=NeedSystem((OptionalNeed('additional_product',
                (ServiceProfile('product','D',(5.,)),),value),)))
    return sc,tr,p,h,stocks


def inherited_resource_needs_world(*, initial=10., K=3):
    if K!=3: raise ValueError('This fixture declares a three-epoch value schedule')
    sc,tr,p,h,stocks=residual_world(K=K,capacity=10.,route='recovery',initial=initial,recovery_cost=.2)
    sc=replace(sc,flow_system=replace(sc.flow_system,demands=()),
        need_system=NeedSystem((OptionalNeed('optional_product',
           (ServiceProfile('product','D',(5.,)),),(7.5,7.5,15.)),)))
    return sc,tr,p,[],stocks


def simple_task_spec(sc, *, effort_capacity=None):
    tasks={n:IntegrationTask(effort=1.,description=n) for n in sc.designs}
    deployments={n:DeploymentRequirement((n,),Capacity(10.,canonical_unit(d)),.01)
                 for n,d in sc.designs.items()}
    return IntegrationSpec(tasks,deployments,capacity=effort_capacity)
