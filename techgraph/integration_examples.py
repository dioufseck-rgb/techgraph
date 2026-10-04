"""Small deterministic fixtures for verifying integration mechanisms, not calibration."""
from dataclasses import replace
from .catalog import Design, Scenario
from .dynamic import Params, Trajectory, Vintage
from .integration import IntegrationSpec, IntegrationTask, DeploymentRequirement
from .representation import Capacity


def two_component_world(pilot_fraction=0.1, effort_budget=1.0, completion_cost=0.0):
    designs = {
        'OLD': Design('OLD','convert',36500.0,loc='D',form_in='fuel',form_out='elec',eff=1.0,max_cap=100.0),
        'REMOTE': Design('REMOTE','renewable',18250.0,loc='R',profile='flat',max_cap=100.0),
        'LINE': Design('LINE','transport',3650.0,form='elec',loc_from='R',loc_to='D',max_cap=100.0),
    }
    sc=Scenario(periods=1,hours=24.0,days=1.0,demand_D=[10.0],hub_energy=0.0,
                hub_max_rate=0.0,profiles={'flat':[1.0]},fuel_price_R=25.0,voll=3000.0,
                designs=designs,locations=('R','D'),fuel_sites=('D',))
    tr=Trajectory(K=4,fuel_price=[25.0]*4,demand_mult=[1.0]*4,discount=0.93)
    prm=Params(life={'OLD':3,'REMOTE':6,'LINE':6},fom_share=0.2,aging=0.0)
    hist=[Vintage('OLD',-1,10.0,10.0,36500.0,0.0,3)]
    tasks={n:IntegrationTask(1.0,completion_cost,description=n.replace('_',' '))
           for n in ['local_operation','remote_operation','corridor_integration']}
    deps={n:DeploymentRequirement((t,),Capacity(10.0,'MW'),pilot_fraction)
          for n,t in [('OLD','local_operation'),('REMOTE','remote_operation'),('LINE','corridor_integration')]}
    spec=IntegrationSpec(tasks,deps,capacity=effort_budget)
    return sc,tr,prm,hist,spec


def relabel(sc,tr,prm,hist,spec,mapping):
    """Consistent design-label transformation; task identities remain unchanged."""
    names={n:mapping.get(n,n) for n in sc.designs}
    if len(set(names.values()))!=len(names):
        raise ValueError('Relabeling must be injective')
    change=lambda d:{names.get(k,k):v for k,v in d.items()}
    return (replace(sc,designs={names[n]:replace(d,name=names[n]) for n,d in sc.designs.items()}),
            replace(tr,cost_mult=change(tr.cost_mult),avail_from=change(tr.avail_from),avail_until=change(tr.avail_until)),
            replace(prm,life=change(prm.life)),[replace(v,design=names[v.design]) for v in hist],
            replace(spec,deployments=change(spec.deployments)))
