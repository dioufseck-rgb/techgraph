from dataclasses import replace
import pytest
from techgraph.catalog import Design,Scenario
from techgraph.flows import FlowSystem,FlowResource,FlowDemand,Port
from techgraph.dynamic import Trajectory,Params,Vintage,run_policy
from techgraph.realizability import Capability,DesignRequirement,SupportWindow,RealizabilitySpec


def support_world(K=6):
    ds={
      'OLD':Design('OLD','process',annual_cost=5,max_cap=100,activity_unit='tonne/h',input_ports=(Port('ore','A',1),),output_ports=(Port('product','A',1),),conserve_mass=True),
      'NEW':Design('NEW','process',annual_cost=12,max_cap=100,activity_unit='tonne/h',input_ports=(Port('ore','A',1),),output_ports=(Port('product','A',1),),conserve_mass=True),
    }
    fs=FlowSystem(form_units={'ore':'tonne','product':'tonne'},resources=(FlowResource('ore','ore','A',(30,),unit_cost=1),),demands=(FlowDemand('svc','product','A',(10,),hard=True),))
    sc=Scenario(periods=1,hours=1,demand_D=[0],hub_energy=0,hub_max_rate=0,profiles={},fuel_price_R=0,voll=3000,designs=ds,locations=('A',),fuel_sites=(),hub_loc='A',flow_system=fs)
    tr=Trajectory(K,[0]*K,[1.]*K,construction_lead={'NEW':1})
    prm=Params(life={'OLD':10,'NEW':10},fom_share=0,aging=0)
    hist=[Vintage('OLD',-1,10,10,5,0,10)]
    rs=RealizabilitySpec({'new_skill':Capability(acquire_cost=3,acquire_lead=1)},
        {'NEW':DesignRequirement(build=('new_skill',),operate=('new_skill',))},
        support={'OLD':SupportWindow(operate_until=2)})
    return sc,tr,prm,hist,rs

def test_support_withdrawal_plus_reconstitution_requires_anticipatory_migration():
    sc,tr,prm,hist,rs=support_world()
    with pytest.raises(RuntimeError):run_policy(sc,tr,prm,hist,horizon=1,realizability=rs)
    r=run_policy(sc,tr,prm,hist,horizon=3,realizability=rs)
    assert r['epochs'][1]['realizability']['acquired'][0]['capability']=='new_skill'
    assert r['epochs'][2]['orders']['NEW']==pytest.approx(10)
    assert r['epochs'][3]['commissioned']['NEW']==pytest.approx(10)
    assert r['epochs'][3]['throughput']['OLD']==pytest.approx(0)
    assert r['epochs'][3]['throughput']['NEW']>0
