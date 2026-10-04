"""Outcome-agnostic abstract material worlds and recursive recipe search.

Conservation, ports, lifetimes and choices are primitives. No transition motif,
target architecture, incumbent identity, scheduled invention or discovery count
is specified. This is an abstract mass-flow grammar, not inferred chemistry or
a first-class model of information, markets, energy conversion or institutions.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass,field,replace
from math import exp,isfinite,sqrt
from collections import defaultdict
import numpy as np
from .catalog import Design,Scenario
from .flows import Port,FlowResource,FlowDemand,Destination,FlowSystem,validate_flow_system
from .dynamic import Trajectory,Params,Vintage,solve_window
from .variation import Candidate,RecombinationRule,recombine,validate_candidate,keyed_rng


@dataclass(frozen=True)
class WorldConfig:
    seed:int=0
    epochs:int=32
    locations:int=3
    forms:int=6
    extra_recipes:int=6
    edge_probability:float=.35
    demand_volatility:float=.15
    demand_persistence:float=.8
    life_min:int=4
    life_max:int=9
    raw_forms:int=1   # v4: number of raw resource forms (1 reproduces v3 exactly)

    def validate(self):
        for name,lo,hi in [('epochs',2,200),('locations',2,12),('forms',4,30),('extra_recipes',0,200),('life_min',2,100),('life_max',2,100)]:
            x=getattr(self,name)
            if not isinstance(x,int) or not lo<=x<=hi:raise ValueError('Invalid '+name)
        if self.life_max<self.life_min:raise ValueError('Invalid lifetime range')
        if not isinstance(self.raw_forms,int) or not 1<=self.raw_forms<=self.forms-2:raise ValueError('Invalid raw_forms')
        if not 0<=self.edge_probability<=1 or not 0<=self.demand_persistence<1 or not 0<=self.demand_volatility<=.8:
            raise ValueError('Invalid world stochastic process')
        return self


@dataclass
class GenerativeWorld:
    scenario:Scenario
    trajectory:Trajectory
    params:Params
    history:list
    metadata:dict


def make_generative_world(config=WorldConfig()):
    cfg=config.validate();rng=keyed_rng(cfg.seed,'world-structure-v1')
    locs=tuple(f'L{i}' for i in range(cfg.locations));forms=tuple(f'F{i}' for i in range(cfg.forms));units={f:'tonne' for f in forms}
    coords={l:(rng.uniform(0,3),rng.uniform(0,3)) for l in locs};annual=365*24
    designs={};roles={};destinations={}
    def process(name,inputs,outputs,capital,variable,role):
        designs[name]=Design(name,'process',annual*capital,var_cost=variable,
            input_ports=tuple(inputs),output_ports=tuple(outputs),activity_unit='tonne/h',max_cap=1000,conserve_mass=True)
        roles[name]=role
    # A random spanning scaffold makes the starting services attainable. It
    # selects no future design or adoption sequence. Extra recipes add branching,
    # mixtures, co-products and cycles with nonnegative private costs.
    for i in range(1,cfg.forms):
        l=rng.choice(locs);parent=forms[rng.randrange(i)]
        capital,variable=rng.uniform(.08,.7),rng.uniform(.15,1.6)
        # v4: with several raw forms, F0..F{r-1} are extracted, not produced.
        # The same draws are consumed, so later world structure is unchanged.
        if i<cfg.raw_forms:continue
        process(f'R{i}',[Port(parent,l)],[Port(forms[i],l)],capital,variable,'recipe')
    for i in range(cfg.extra_recipes):
        l=rng.choice(locs);perm=list(forms);rng.shuffle(perm)
        ni=rng.randint(1,min(2,cfg.forms-2));no=rng.randint(1,min(3,cfg.forms-ni))
        ins=perm[:ni];outs=perm[ni:ni+no]
        wi=[rng.uniform(.2,1) for _ in ins];wo=[rng.uniform(.2,1) for _ in outs]
        process(f'X{i}',[Port(f,l,w/sum(wi)) for f,w in zip(ins,wi)],
                [Port(f,l,w/sum(wo)) for f,w in zip(outs,wo)],rng.uniform(.06,.8),rng.uniform(.1,1.8),'recipe')
    edges={(rng.randrange(j),j) for j in range(1,cfg.locations)}
    for i in range(cfg.locations):
        for j in range(i+1,cfg.locations):
            if rng.random()<cfg.edge_probability:edges.add((i,j))
    for i,j in sorted(edges):
        dist=sqrt(sum((a-b)**2 for a,b in zip(coords[locs[i]],coords[locs[j]])))
        for a,b in [(i,j),(j,i)]:
            for form in forms:
                process(f'T_{form}_{a}_{b}',[Port(form,locs[a])],[Port(form,locs[b])],
                        rng.uniform(.01,.10)*(1+dist),rng.uniform(.03,.15)*(1+dist),'transport')
    # Every termination is explicit and charged. Disposal is not free spill.
    for l in locs:
        for form in forms:
            dest=f'receiver_{form}_{l}';destinations[dest]=Destination('tonne','disposal',bearer=dest,private_charge=rng.uniform(.02,.2))
            n=f'S_{form}_{l}';designs[n]=Design(n,'sink',annual*.005,form=form,loc=l,destination=dest,
                                                  activity_unit='tonne/h',max_cap=1000);roles[n]='disposal'
    resources=tuple(FlowResource(f'input_{l}',forms[0],l,(1000.,),rng.uniform(.5,2.0)) for l in locs)
    if cfg.raw_forms>1:
        # Each extra raw form occurs at a random nonempty subset of sites (keyed
        # stream, so v3 structure draws are untouched). F0 stays everywhere.
        rr=keyed_rng(cfg.seed,'raw-placement-v4');extra=[]
        for j in range(1,cfg.raw_forms):
            sites=[l for l in locs if rr.random()<.5] or [rr.choice(locs)]
            extra+=[FlowResource(f'input_{forms[j]}_{l}',forms[j],l,(1000.,),rr.uniform(.5,2.0)) for l in sites]
        resources=resources+tuple(extra)
    demands=[]
    for i,f in enumerate(forms[-2:]):
        # Need identity and place are initial conditions; adoption is not demand.
        l=rng.choice(locs);demands.append(FlowDemand(f'need{i}',f,l,(rng.uniform(2,4),),hard=True))
    fs=FlowSystem(units,tuple(demands),destinations,(),False,resources)
    sc=Scenario(1,1,[0],0,0,{},0,3000,designs,days=1/24,locations=locs,fuel_sites=(),hub_loc=locs[0],coords=coords,flow_system=fs)
    validate_flow_system(sc)
    lives={n:rng.randint(cfg.life_min,cfg.life_max) for n in sorted(designs)}
    prm=Params(lives,fom_share=.2,aging=.04)
    demand_scale={}
    for q in demands:
        dr=keyed_rng(cfg.seed,'demand-process-v1',q.name);x=0.;seq=[]
        for k in range(cfg.epochs):
            if k:x=cfg.demand_persistence*x+dr.gauss(0,cfg.demand_volatility)
            seq.append(float(np.clip(exp(x),.5,2.)))
        demand_scale[q.name]=seq
    tr=Trajectory(cfg.epochs,[0.]*cfg.epochs,[1.]*cfg.epochs,discount=1.,demand_scale=demand_scale)
    # Starting assets solve only period-zero service. They are then assigned
    # heterogeneous ages, independently of the future need or invention streams.
    start=solve_window(sc,tr,prm,0,0,[],time_limit=30.)
    history=[]
    for n,cap in sorted(start['epochs'][0]['builds'].items()):
        if cap<=1e-8:continue
        age=keyed_rng(cfg.seed,'initial-age',n).randrange(prm.life[n])
        d=designs[n];history.append(Vintage(n,-age,cap,cap,d.annual_cost,d.fixed_cost,prm.life[n]))
    return GenerativeWorld(sc,tr,prm,history,{'generator':'abstract-material-grammar-v1','config':asdict(cfg),
        'initialization':'one-period service optimum, independently aged assets','module_roles':roles,'spatial_edges':sorted(edges),
        'demand_process':'clipped log AR(1), keyed independently; no targeted event dates',
        'unsupported':['chemical/energy feasibility beyond declared mass balance','information copying','independent actors',
                       'capability acquisition','construction lead in this VSR adapter','physical inventories','endogenous needs','experience learning'],
        'initial_optimum':start['objective'],'initial_solver':start['solver']})


@dataclass(frozen=True)
class SearchConfig:
    seed:int=0
    mean_attempts:float=1.5
    max_attempts:int=4
    mutation_share:float=.4
    composition_share:float=.35
    factorization_share:float=.15
    attempt_cost:float=.01
    cost_sigma:float=.2
    cost_bounds:tuple=(.25,4.)
    composition_factor:tuple=(.85,1.15)
    max_ports:int=12
    max_generation:int=12
    use_bias:float=0.        # v4: parent weight 1+use_bias if operated in the previous epoch
    variant_share:float=0.   # v4: share of attempts spent on interface variants
    variant_drift:float=-.1  # log-cost drift of a variant relative to its parent
    adapter_cost:tuple=(.05,.25)

    def validate(self):
        if not isfinite(self.use_bias) or self.use_bias<0 or not 0<=self.variant_share<1:raise ValueError('Invalid v4 search parameters')
        weights=[self.mutation_share,self.composition_share,self.factorization_share]
        if any(not isfinite(x) or x<0 for x in weights) or sum(weights)>1:raise ValueError('Invalid operator shares')
        if not isfinite(self.mean_attempts) or self.mean_attempts<0 or not isinstance(self.max_attempts,int) or self.max_attempts<0:raise ValueError('Invalid attempt process')
        if not isfinite(self.attempt_cost) or self.attempt_cost<0 or not isfinite(self.cost_sigma) or self.cost_sigma<0:raise ValueError('Invalid search cost/variation')
        for bounds in [self.cost_bounds,self.composition_factor]:
            if len(bounds)!=2 or not 0<bounds[0]<=bounds[1] or not all(map(isfinite,bounds)):raise ValueError('Invalid cost envelope')
        if self.max_ports<2 or self.max_generation<1:raise ValueError('Invalid computational envelope')
        return self


@dataclass(frozen=True)
class ProposalBatch:
    candidates:tuple=()
    forms:dict=field(default_factory=dict)
    attempts:tuple=()
    charge:float=0.


class RecipeSearch:
    """Recursive, non-oracular recipe operators over accumulated knowledge.

    New intermediates arise by algebraic factorization; subsequent composition
    may connect them. Factorization itself guarantees neither adoption nor value.
    Computational port/depth bounds are explicit and hit counts are recorded.
    """
    def __init__(self,config=SearchConfig()):
        self.config=config.validate();self.generation={};self.anchors={}

    def manifest(self):return {'generator':'recursive-recipe-search-v1',**asdict(self.config),
                              'operators':['cost/yield mutation','serial composition','factorization','relocation'],
                              'proposal_clock':'capped Poisson attempts; invalid draws consume effort'}

    def propose(self,sc,lives,knowledge,epoch,activity):
        cfg=self.config
        if sc.interface_system is not None:raise ValueError('Generic grammar does not support typed standards yet')
        eligible=sorted(n for n in knowledge if sc.designs[n].kind=='process' and sc.designs[n].conserve_mass)
        for n in eligible:
            self.generation.setdefault(n,0)
            self.anchors.setdefault(n,(sc.designs[n].annual_cost,sc.designs[n].var_cost))
        # Independent clock means changing acceptance does not change random effort.
        rg=np.random.default_rng(keyed_rng(cfg.seed,'attempt-clock',epoch).getrandbits(64))
        attempts=min(int(rg.poisson(cfg.mean_attempts)),cfg.max_attempts)
        offered=[];forms={};log=[]
        output_index=defaultdict(list);input_index=defaultdict(list)
        for n in eligible:
            d=sc.designs[n]
            for p in d.output_ports:output_index[p.form,p.location].append(n)
            for p in d.input_ports:input_index[p.form,p.location].append(n)
        interfaces=sorted(set(output_index)&set(input_index))
        used={n for n,x in (activity or {}).items() if x>1e-8}
        def pick(rng,names):
            names=list(names)
            if cfg.use_bias<=0:return rng.choice(names)
            return rng.choices(names,weights=[1+cfg.use_bias*(n in used) for n in names],k=1)[0]
        for slot in range(attempts):
            rng=keyed_rng(cfg.seed,'recipe-draw',epoch,slot);u=rng.random();bounds=[cfg.mutation_share,cfg.mutation_share+cfg.composition_share,cfg.mutation_share+cfg.composition_share+cfg.factorization_share]
            op='mutation' if u<bounds[0] else 'composition' if u<bounds[1] else 'factorization' if u<bounds[2] else 'relocation'
            if cfg.variant_share>0 and keyed_rng(cfg.seed,'variant-draw',epoch,slot).random()<cfg.variant_share:op='variant'
            row={'slot':slot,'operator':op};name=f'G_{epoch:03d}_{slot:02d}';localforms={};cs=[]
            try:
                if not eligible:raise ValueError('no_eligible_parent')
                if op=='composition':
                    if not interfaces:raise ValueError('no_compatible_interface')
                    form,loc=rng.choice(interfaces);a=pick(rng,output_index[form,loc]);b=pick(rng,input_index[form,loc])
                    parents=(a,b);generation=1+max(self.generation[a],self.generation[b])
                    rule=RecombinationRule('generic','generic','generic',form,loc,cfg.composition_factor)
                    cs=[recombine(sc,a,b,rule,seed=cfg.seed,epoch=epoch,slot=slot,lives=lives,name=name)]
                elif op=='variant':
                    cs,parents,generation,localforms=self._variant(sc,lives,eligible,epoch,slot,name,pick,output_index,input_index)
                else:
                    parent=pick(rng,eligible);d=sc.designs[parent];parents=(parent,);generation=self.generation[parent]+1
                    if op=='mutation':
                        ac=d.annual_cost*exp(rng.gauss(0,cfg.cost_sigma));vc=d.var_cost*exp(rng.gauss(0,cfg.cost_sigma))
                        anchor=self.anchors[parent]
                        for val,base in [(ac,anchor[0]),(vc,anchor[1])]:
                            if base>0 and not cfg.cost_bounds[0]<=val/base<=cfg.cost_bounds[1]:raise ValueError('cost_envelope')
                        ports=list(d.output_ports)
                        if len(ports)>1:
                            i,j=rng.sample(range(len(ports)),2);total=ports[i].coefficient+ports[j].coefficient
                            yi=ports[i].coefficient+rng.gauss(0,.06*total)
                            if not .05*total<yi<.95*total:raise ValueError('yield_envelope')
                            ports[i]=replace(ports[i],coefficient=yi);ports[j]=replace(ports[j],coefficient=total-yi)
                        design=replace(d,name=name,annual_cost=ac,var_cost=vc,output_ports=tuple(ports))
                        cs=[Candidate(design,'generic',parents,'generic_mutation',epoch,slot,lives[parent],{})]
                    elif op=='relocation':
                        locset={p.location for p in d.input_ports+d.output_ports}
                        if len(locset)!=1:raise ValueError('only_local_recipes_relocatable')
                        choices=sorted(set(sc.locations)-locset)
                        if not choices:raise ValueError('no_other_location')
                        loc=rng.choice(choices)
                        design=replace(d,name=name,input_ports=tuple(replace(p,location=loc) for p in d.input_ports),
                                       output_ports=tuple(replace(p,location=loc) for p in d.output_ports))
                        cs=[Candidate(design,'generic',parents,'relocation',epoch,slot,lives[parent],{'destination':loc})]
                    else:
                        if len(d.input_ports)+len(d.output_ports)>cfg.max_ports:raise ValueError('port_envelope')
                        intermediate=f'M_{epoch:03d}_{slot:02d}'
                        if intermediate in sc.flow_system.form_units:raise ValueError('intermediate_collision')
                        loc=rng.choice(sorted({p.location for p in d.input_ports+d.output_ports}))
                        amount=sum(p.coefficient for p in d.input_ports)
                        share=rng.uniform(.25,.75);factor=rng.uniform(*cfg.composition_factor);localforms[intermediate]='tonne'
                        da=replace(d,name=name+'_a',annual_cost=d.annual_cost*share*factor,var_cost=d.var_cost*share*factor,
                                   fixed_cost=d.fixed_cost*share*factor,output_ports=(Port(intermediate,loc,amount),))
                        db=replace(d,name=name+'_b',annual_cost=d.annual_cost*(1-share)*factor,var_cost=d.var_cost*(1-share)*factor,
                                   fixed_cost=d.fixed_cost*(1-share)*factor,input_ports=(Port(intermediate,loc,amount),))
                        cs=[Candidate(dd,'generic',parents,'factorization',epoch,slot,lives[parent],{'intermediate':intermediate,'part':part,'cost_factor':factor}) for dd,part in [(da,'upstream'),(db,'downstream')]]
                if generation>cfg.max_generation:raise ValueError('generation_envelope')
                if any(len(c.design.input_ports)+len(c.design.output_ports)>cfg.max_ports for c in cs):raise ValueError('port_envelope')
                test_sc=replace(sc,flow_system=replace(sc.flow_system,form_units={**sc.flow_system.form_units,**localforms}))
                for c in cs:validate_candidate(test_sc,c)
                for c in cs:
                    c=replace(c,metadata={**c.metadata,'generation':generation,'parents_known_before_epoch':True})
                    self.generation[c.design.name]=generation
                    self.anchors[c.design.name]=self.anchors[parents[0]] if op in {'mutation','relocation'} else (c.design.annual_cost,c.design.var_cost)
                    if c.design.name not in self.generation:self.generation[c.design.name]=generation
                    offered.append(c)
                forms.update(localforms);row.update(status='proposed',parents=list(parents),designs=[c.design.name for c in cs],generation=generation)
            except ValueError as exc:row.update(status='invalid',reason=str(exc))
            log.append(row)
        return ProposalBatch(tuple(offered),forms,tuple(log),cfg.attempt_cost*attempts)


    def _variant(self,sc,lives,eligible,epoch,slot,name,pick,output_index,input_index):
        """Interface variants (v4). A variant is a new form F~v at one location,
        materially identical to F but incompatible with F's existing consumers.

        'create': a producer of F@l is copied to produce F~v@l, with a cost drift
        (the new interface permits a different implementation), plus a pair of
        adapters F~v@l -> F@l and F@l -> F~v@l that cost a declared fraction of
        the producer. 'adopt': a consumer of F@l is copied to take an existing
        known variant F~v@l instead. Variants have no transport or warehouse;
        dependence on a variant is therefore dependence on an interface.
        """
        cfg=self.config;rng=keyed_rng(cfg.seed,'variant-op',epoch,slot)
        variants=sorted(f for f in sc.flow_system.form_units if '~' in f)
        consumers=[]
        for v in variants:
            base=v.split('~')[0]
            for l in sorted({l for (f,l) in output_index if f==v}):
                consumers+=[(v,l,n) for n in input_index.get((base,l),[])]
        if consumers and rng.random()<.5:
            v,l,parent=consumers[rng.randrange(len(consumers))];d=sc.designs[parent]
            if any(p.form==v for p in d.input_ports):raise ValueError('variant_already_adopted')
            ports=tuple(replace(p,form=v) if (p.form,p.location)==(v.split('~')[0],l) else p for p in d.input_ports)
            f=exp(rng.gauss(cfg.variant_drift,cfg.cost_sigma))
            dd=replace(d,name=name,input_ports=ports,annual_cost=d.annual_cost*f,var_cost=d.var_cost*f)
            return [Candidate(dd,'generic',(parent,),'variant_adopt',epoch,slot,lives[parent],{'variant':v})],(parent,),self.generation[parent]+1,{}
        producers=[(f,l,n) for (f,l),names in output_index.items() if '~' not in f for n in names]
        if not producers:raise ValueError('no_variant_parent')
        f0,l,parent=producers[rng.randrange(len(producers))];d=sc.designs[parent]
        v=f'{f0}~{epoch:03d}{slot:02d}'
        if v in sc.flow_system.form_units:raise ValueError('intermediate_collision')
        g=exp(rng.gauss(cfg.variant_drift,cfg.cost_sigma))
        ports=tuple(replace(p,form=v) if (p.form,p.location)==(f0,l) else p for p in d.output_ports)
        dp=replace(d,name=name,output_ports=ports,annual_cost=d.annual_cost*g,var_cost=d.var_cost*g)
        ac=rng.uniform(*cfg.adapter_cost)
        up=replace(d,name=name+'_up',input_ports=(Port(v,l,1.),),output_ports=(Port(f0,l,1.),),
                   annual_cost=d.annual_cost*ac,var_cost=d.var_cost*ac,fixed_cost=d.fixed_cost*ac)
        down=replace(up,name=name+'_down',input_ports=(Port(f0,l,1.),),output_ports=(Port(v,l,1.),))
        cs=[Candidate(dp,'generic',(parent,),'variant_create',epoch,slot,lives[parent],{'variant':v,'base':f0}),
            Candidate(up,'generic',(parent,),'adapter',epoch,slot,lives[parent],{'variant':v,'direction':'to_base'}),
            Candidate(down,'generic',(parent,),'adapter',epoch,slot,lives[parent],{'variant':v,'direction':'to_variant'})]
        return cs,(parent,),self.generation[parent]+1,{v:'tonne'}
