"""Generated, mass-balanced, interconnected production worlds on the common engine.

This is a supplied functional grammar with generated spatial/economic traits,
not automatically inferred chemistry or a model of independent firms.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from itertools import combinations
import math
import numpy as np
from .catalog import Design, Scenario
from .flows import Port, FlowDemand, FlowResource, Destination, FlowSystem, validate_flow_system
from .attributes import AttributeDefinition, FormVariant, NumericLimit, RequirementStage, ServiceRequirement, AttributeSystem
from .dynamic import Trajectory, Params, Vintage
from .stocks import StockSpec, StockSystem
from .integration import IntegrationTask, DeploymentRequirement, IntegrationSpec
from .representation import Capacity

TRANSFER_FORMS=('intermediate','coproduct','residue')
ROLES=('REFINE','LEAN_REFINE','FINISH_LOW','FINISH_HIGH','UPGRADE','SUPPLEMENT',
       'RECOVER','TREAT','DEPOSIT','WITHDRAW','INERT_OUT','COPRODUCT_OUT','DIRECT_HIGH')
EXTRA_ROLES={'LEAN_REFINE','UPGRADE','RECOVER'}

@dataclass
class NetworkWorld:
    scenario: Scenario
    trajectory: Trajectory
    params: Params
    history: list
    stocks: StockSystem
    metadata: dict
    forbid: tuple[str,...]=()
    integration: IntegrationSpec|None=None

    def manifest(self):
        return {'scenario':asdict(self.scenario),'trajectory':asdict(self.trajectory),
                'params':asdict(self.params),'history':[asdict(x) for x in self.history],
                'stocks':self.stocks.manifest(self.scenario),
                'integration':None if self.integration is None else self.integration.manifest(self.scenario),
                'metadata':self.metadata,'forbid':list(self.forbid)}


def _edges(coords, neighbours=3):
    """Nested connected candidate scaffolds: Euclidean MST, then k-neighbour edges."""
    n=len(coords)
    distances={(a,b):float(np.linalg.norm(coords[a]-coords[b])) for a,b in combinations(range(n),2)}
    # Kruskal without a dependency on a graph package.
    parent=list(range(n))
    def find(a):
        while parent[a]!=a:
            parent[a]=parent[parent[a]];a=parent[a]
        return a
    tree=set()
    for (a,b),d in sorted(distances.items(),key=lambda p:(p[1],p[0])):
        u,v=find(a),find(b)
        if u!=v:parent[u]=v;tree.add((a,b))
    rich=set(tree)
    for a in range(n):
        near=sorted((b for b in range(n) if b!=a),key=lambda b:(distances[tuple(sorted((a,b)))],b))
        rich.update(tuple(sorted((a,b))) for b in near[:min(neighbours,n-1)])
    return tree,rich,distances


def make_network_world(n_sites=6, seed=0, connectivity='rich', *, K=6, periods=2,
                       alternatives='rich', residual_capacity=6.0, link_cost_scale=1.,
                       link_fixed_charge=0., integration_budget=None, enable_integration=False,
                       pilot_fraction=.10, shock_site=None, shock_epoch=None):
    if n_sites<2 or n_sites>100 or K<1 or periods<1:raise ValueError('Invalid world size')
    if connectivity not in {'separated','sparse','rich'}:raise ValueError('Unknown connectivity')
    if alternatives not in {'core','rich'}:raise ValueError('Unknown alternative set')
    if residual_capacity is not None and residual_capacity<0:raise ValueError('Negative stock capacity')
    if link_cost_scale<0 or link_fixed_charge<0:raise ValueError('Negative link cost')
    rng=np.random.default_rng(seed)
    # Fixed local-scale spacing; area expands with size. No privileged center node.
    width=math.ceil(math.sqrt(n_sites))
    coords=np.array([(i%width,i//width) for i in range(n_sites)],float)+rng.uniform(-.15,.15,(n_sites,2))
    tree,rich,distances=_edges(coords)
    locs=tuple('D' if i==0 else f'L{i:02d}' for i in range(n_sites))
    forms={f:'tonne' for f in ['feed','intermediate','product','low','high','coproduct','residue','inert']}
    forms.update(fuel='MWh',elec='MWh',h2='MWh')
    D=periods/24.; annual=365./D  # all specified below as per-block capacity/lump charges
    designs={};roles={};traits={};history=[];destinations={};resources=[];demands=[];requirements={};stock_specs={}
    tasks={};deploy={}
    def add(name,role,site,inputs=(),outputs=(),capcost=.05,varcost=0.,maxcap=80.,kind='process',form=None,destination=None,fixed=0.):
        d=Design(name,kind,capcost*annual,fixed_cost=fixed*annual,var_cost=varcost,
                 input_ports=tuple(Port(f,l,c) for f,l,c in inputs),
                 output_ports=tuple(Port(f,l,c) for f,l,c in outputs),
                 activity_unit='tonne/h',max_cap=maxcap,conserve_mass=kind=='process',
                 form=form,loc=site if kind!='process' else None,destination=destination)
        designs[name]=d;roles[name]={'role':role,'site':site}
    for i,l in enumerate(locs):
        demand=float(rng.uniform(7.,12.));secondary=float(rng.uniform(1.0,5.0))
        rawprice=float(rng.uniform(.6,2.8));ry=float(rng.uniform(.66,.80));by=float(rng.uniform(.12,.18))
        efficient=float(rng.uniform(.87,.94));rec=float(rng.uniform(.45,.75))
        # Reference-period demand profiles have equal mean and differ temporally.
        profile=np.array([.90,1.10]*((periods+1)//2))[:periods];profile/=profile.mean()
        need=tuple(float(demand*x) for x in profile);co_need=tuple(float(secondary*x) for x in profile)
        traits[l]={'primary_rate':demand,'coproduct_rate':secondary,'resource_price':rawprice,
                   'old_yield':ry,'coproduct_yield':by,'lean_yield':efficient,'recovery_yield':rec}
        destinations['pile_'+l]=Destination('tonne','stock',bearer=l+' residual inventory')
        destinations['inert_'+l]=Destination('tonne','disposal',bearer=l+' inert receiving environment',private_charge=.12)
        destinations['coproduct_'+l]=Destination('tonne','disposal',bearer=l+' unused coproduct receiver',private_charge=.05)
        stock_specs['pile_'+l]=StockSpec('residue',l,capacity=residual_capacity)
        basic_peak=max(need)/(.9*ry)
        resources.extend([FlowResource('primary_'+l,'feed',l,tuple(basic_peak*1.45 for _ in range(periods)),rawprice),
                          FlowResource('reserve_'+l,'feed',l,tuple(basic_peak*5 for _ in range(periods)),rawprice+6.)])
        req='grade_'+l
        stages=(RequirementStage(0,(NumericLimit('grade',lower=.80),)),)
        if shock_site==i and shock_epoch is not None:
            if not 0<=shock_epoch<K:raise ValueError('Requirement event outside trajectory')
            q=RequirementStage(shock_epoch,(NumericLimit('grade',lower=.98),))
            stages=(q,) if shock_epoch==0 else stages+(q,)
        requirements[req]=ServiceRequirement('product',('low','high'),stages)
        demands.extend([FlowDemand('product_'+l,'product',l,need,attribute_requirement=req,scale_with_demand=False),
                        FlowDemand('secondary_'+l,'coproduct',l,co_need,scale_with_demand=False)])
        P=lambda f,c=1.:(f,l,c)
        add('REFINE_'+l,'REFINE',l,[P('feed')],[P('intermediate',ry),P('coproduct',by),P('residue',1-ry-by)],.08,.18)
        add('LEAN_REFINE_'+l,'LEAN_REFINE',l,[P('feed')],[P('intermediate',efficient),P('residue',1-efficient)],.19,.32)
        add('FINISH_LOW_'+l,'FINISH_LOW',l,[P('intermediate')],[P('low',.9),P('residue',.1)],.06,.18)
        add('FINISH_HIGH_'+l,'FINISH_HIGH',l,[P('intermediate')],[P('high',.82),P('residue',.18)],.18,.48)
        uy=float(rng.uniform(.86,.96));uc=float(rng.uniform(.2,1.1))
        add('UPGRADE_'+l,'UPGRADE',l,[P('low')],[P('high',uy),P('residue',1-uy)],.13,uc)
        add('SUPPLEMENT_'+l,'SUPPLEMENT',l,[P('feed')],[P('coproduct',.8),P('residue',.2)],.12,.9)
        rc=float(rng.uniform(.25,1.8));tc=float(rng.uniform(.6,1.9))
        add('RECOVER_'+l,'RECOVER',l,[P('residue')],[P('intermediate',rec),P('inert',1-rec)],.15,rc)
        add('TREAT_'+l,'TREAT',l,[P('residue')],[P('inert')],.09,tc)
        add('DEPOSIT_'+l,'DEPOSIT',l,capcost=.025,varcost=.02,kind='sink',form='residue',destination='pile_'+l)
        add('WITHDRAW_'+l,'WITHDRAW',l,capcost=.05,varcost=.04,kind='withdraw',form='residue',destination='pile_'+l)
        add('INERT_OUT_'+l,'INERT_OUT',l,capcost=.015,kind='sink',form='inert',destination='inert_'+l)
        add('COPRODUCT_OUT_'+l,'COPRODUCT_OUT',l,capcost=.015,kind='sink',form='coproduct',destination='coproduct_'+l)
        add('DIRECT_HIGH_'+l,'DIRECT_HIGH',l,[P('feed')],[P('high',.92),P('residue',.08)],.3,2.3)
        traits[l].update(upgrade_yield=uy,upgrade_cost=uc,recovery_cost=rc,treatment_cost=tc)
        for name,d in list(designs.items()):
            if roles[name]['site']!=l:continue
            task=roles[name]['role']+'@'+l
            tasks[task]=IntegrationTask(1.,description=task)
            deploy[name]=DeploymentRequirement((task,),Capacity(10.,'tonne/h'),pilot_fraction)
            if roles[name]['role'] in {'REFINE','FINISH_LOW','SUPPLEMENT','TREAT','DEPOSIT','WITHDRAW','INERT_OUT','COPRODUCT_OUT'}:
                cap=basic_peak*1.7 if roles[name]['role']=='REFINE' else max(need)*1.7
                age=1+(i%3);life=8
                history.append(Vintage(name,-age,cap,cap,d.annual_cost,d.fixed_cost,life))
    edge_names={};allowed={'separated':set(),'sparse':tree,'rich':rich}[connectivity]
    for a,b in sorted(rich):
        distance=distances[a,b]
        for src,dst in [(a,b),(b,a)]:
            for form in TRANSFER_FORMS:
                name=f'LINK_{form}_{src:02d}_{dst:02d}'
                loss=min(.04,.008*distance)
                add(name,'LINK',locs[src],[(form,locs[src],1.)],[(form,locs[dst],1-loss),('inert',locs[dst],loss)],
                    capcost=.045*distance*link_cost_scale,varcost=.07*distance*link_cost_scale,
                    maxcap=50.,fixed=link_fixed_charge*distance)
                roles[name].update(origin=locs[src],destination=locs[dst],form=form,distance=distance)
                edge_names[name]=(a,b)
                task=f'corridor@{a:02d}_{b:02d}'
                tasks.setdefault(task,IntegrationTask(1.,description=task))
                deploy[name]=DeploymentRequirement((task,),Capacity(10.,'tonne/h'),pilot_fraction)
    forbid=tuple(sorted(n for n in designs if (n in edge_names and edge_names[n] not in allowed) or
                         (alternatives=='core' and roles[n]['role'] in EXTRA_ROLES)))
    attrs=AttributeSystem({'grade':AttributeDefinition('numeric','fraction',allow_average=True)},
        {'low':FormVariant('product',{'grade':.90}), 'high':FormVariant('product',{'grade':1.0})},requirements)
    fs=FlowSystem(forms,tuple(demands),destinations,(),True,tuple(resources))
    sc=Scenario(periods,1.,[0.]*periods,0.,0.,{},0.,3000.,designs,days=D,locations=locs,
                fuel_sites=(),hub_loc=locs[0],coords={l:tuple(map(float,c)) for l,c in zip(locs,coords)},
                flow_system=fs,attribute_system=attrs)
    tr=Trajectory(K,[0.]*K,[1.]*K,discount=.93)
    prm=Params({n:8 for n in designs},fom_share=.2,aging=.02)
    stocks=StockSystem(stock_specs,tuple(1. for _ in range(K)))
    integration=IntegrationSpec(tasks,deploy,capacity=integration_budget) if enable_integration else None
    validate_flow_system(sc);stocks.validate(sc,K)
    if integration:integration.validate(sc,K)
    meta={'generator':'interconnected-production-v0.1','seed':seed,'n_sites':n_sites,'K':K,'periods':periods,
          'connectivity':connectivity,'alternatives':alternatives,'candidate_designs':len(designs),
          'available_designs':len(designs)-len(forbid),'service_obligations':len(demands),
          'traits':traits,'module_roles':roles,'tree_edges':sorted(tree),'rich_edges':sorted(rich),
          'allowed_edges':sorted(allowed),'link_cost_scale':link_cost_scale,'link_fixed_charge':link_fixed_charge,
          'residual_capacity':residual_capacity,'pilot_fraction':pilot_fraction,
          'integration_enabled':enable_integration,'integration_budget':integration_budget,
          'requirement_shock_site':shock_site,'requirement_shock_epoch':shock_epoch,
          'scope':'one joint planner; fixed known catalogue; generated declared mass recipes; not calibrated chemistry'}
    return NetworkWorld(sc,tr,prm,history,stocks,meta,forbid,integration)


def quality_shock(world, site=0, epoch=3):
    """New requirement on one site; no physical recipe or quantity changes."""
    l=world.scenario.locations[site]
    reqs=dict(world.scenario.attribute_system.requirements)
    req=reqs['grade_'+l]
    reqs['grade_'+l]=replace(req,stages=(RequirementStage(0,(NumericLimit('grade',lower=.80),)),
                                       RequirementStage(epoch,(NumericLimit('grade',lower=.98),))))
    sc=replace(world.scenario,attribute_system=replace(world.scenario.attribute_system,requirements=reqs))
    return replace(world,scenario=sc,metadata={**world.metadata,'intervention':{'kind':'quality','site':l,'epoch':epoch}})
