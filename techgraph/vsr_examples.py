"""Explicit VSR examples: verification fixtures, not calibrated technology searches."""
from dataclasses import replace
from .variation import MutationRule,RecombinationRule,Candidate
from .vsr import VSRConfig
from .need_examples import efficiency_need_world,simple_task_spec
from .stock_examples import residual_world
from .attribute_examples import quality_world
from .integration_examples import two_component_world
from .flows import FlowSystem


def efficiency_search_world(*,K=6,optional=True,world_seed=0):
    from .variation import keyed_rng
    rng=keyed_rng(world_seed,'physical')
    sc,tr,p,h=efficiency_need_world(K=K,optional=optional,arrival=K+1,
                                 value_multiplier=rng.uniform(.65,1.5))
    sc=replace(sc,designs={n:d for n,d in sc.designs.items() if n!='NEW'})
    tr=replace(tr,avail_from={},fuel_price=[rng.uniform(.8,1.2)]*K)
    p=replace(p,life={n:v for n,v in p.life.items() if n!='NEW'})
    rules=(MutationRule('generation','OLD',cost_log_sigma=.25,variable_sigma=0,output_pair=(0,1),
                        yield_sigma=.07,yield_bounds=(.12,.82)),)
    return sc,tr,p,h,rules,(),None


def circular_search_world(*,K=6,capacity=5.,world_seed=0,quality=False):
    from .variation import keyed_rng
    rng=keyed_rng(world_seed,'physical')
    if quality:
        sc,tr,p,h=quality_world(K=K,change_at=K//2,upgrade=True,upgrade_cost=rng.uniform(.8,2.4),
                               upgrade_yield=.85,new_cost=rng.uniform(2.5,4.))
        rules=(MutationRule('upgrade','UPGRADE',cost_log_sigma=.3,variable_sigma=.5,output_pair=(0,1),
                            yield_sigma=.065,yield_bounds=(.5,.985)),)
        return sc,tr,p,h,rules,(),None
    sc,tr,p,h,stocks=residual_world(K=K,capacity=capacity,route='recovery',recovery_cost=rng.uniform(1.5,5.))
    rules=(MutationRule('production','OLD',cost_log_sigma=.3,variable_sigma=.35,output_pair=(0,1),yield_sigma=.04,yield_bounds=(.5,.985)),
           MutationRule('recovery','RECOVER',cost_log_sigma=.3,variable_sigma=.55,output_pair=(0,1),yield_sigma=.08,yield_bounds=(.2,.95)))
    recombinations=(RecombinationRule('integrated_recovery','production','recovery','residue','D',(.85,1.15)),)
    return sc,tr,p,h,rules,recombinations,stocks


def complementary_prototypes(*,delay=False):
    sc,tr,p,h,spec=two_component_world()
    ds=dict(sc.designs)
    ds['REMOTE']=replace(ds['REMOTE'],annual_cost=365.*100000.)
    ds['LINE']=replace(ds['LINE'],annual_cost=365.*100000.)
    sc=replace(sc,designs=ds,flow_system=FlowSystem(spill_forms=('fuel','elec','h2'),hard_legacy_service=True))
    low_gen=replace(ds['REMOTE'],name='PROTO_REMOTE',annual_cost=365.*50.)
    low_line=replace(ds['LINE'],name='PROTO_LINE',annual_cost=365.*10.)
    a=Candidate(low_gen,'remote',('REMOTE',),'scheduled_prototype',0,0,p.life['REMOTE'],{})
    b=Candidate(low_line,'delivery',('LINE',),'scheduled_prototype',1 if delay else 0,1,p.life['LINE'],{})
    scheduled={0:[a] if delay else [a,b]}
    if delay:scheduled[1]=[b]
    rules=(MutationRule('remote','REMOTE'),MutationRule('delivery','LINE'))
    return sc,tr,p,h,rules,scheduled
