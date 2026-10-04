"""Variation, trial selection, support retention, and adoption on the common engine.

This driver calls the existing dynamic optimizer. It does not replace service,
stock, integration, or accounting physics with an evolutionary surrogate.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace, fields
from itertools import combinations
from math import isfinite
import ast
from .variation import MutationRule, RecombinationRule, Candidate, keyed_rng, fingerprint, mutate, recombine, validate_candidate
from .dynamic import solve_window, Vintage, Project, path_cost, path_objective
from .realizability import CapabilityGrant
from .accounting import reconcile_run, independent_path_ledger
from .flows import validate_flow_system, audit_flow_block
from .flow_audit import audit_operating_state
from .needs import audit_need_run
from .attributes import audit_attribute_run
from .stocks import validate_context, audit_stock_run
from .integration import IntegrationTask, DeploymentRequirement, audit_integration_run
from .representation import Capacity, canonical_unit


from ._vsr_legacy import VSRConfig as LegacyConfig, run_vsr as legacy_run, audit_vsr as legacy_audit

@dataclass(frozen=True)
class VSRConfig(LegacyConfig):
    """Persistent knowledge by default; legacy semantics require explicit opt-in.

    support_* fields are compatibility names for investment-consideration charges
    and attention pruning. They do not price or delete stored knowledge.
    """
    parent_pool: str = 'knowledge'
    knowledge_mode: str = 'persistent'
    retrieval: str = 'archive'
    full_archive_access: bool = False
    expectations: str = 'true'
    compact_history: bool = False
    # v4 opt-in realism fields; defaults reproduce the frozen v3 policy exactly.
    forecast: str = 'none'            # none | oracle | ar1 | holt (overrides expectations for demand/resource paths)
    switching_cost: float = 0.0       # per unit absolute change in a process's epoch throughput
    learning_rate: float = 0.0        # experience exponent b: new-build cost x (1+cum/q_ref)^-b
    learning_reference: float = 1.0   # q_ref, cumulative throughput scale
    learning_floor: float = 0.3       # lower bound on the experience multiplier

    def validate(self):
        if self.knowledge_mode not in {'persistent','legacy_support'}:
            raise ValueError('Unknown knowledge mode')
        if self.parent_pool not in {'knowledge','retained','seeds'}:
            raise ValueError('Unknown parent pool')
        if self.retrieval not in {'archive','recent'}:
            raise ValueError('Unknown archive retrieval policy')
        if not isinstance(self.full_archive_access,bool):
            raise ValueError('full_archive_access must be Boolean')
        if not isinstance(self.compact_history,bool):raise ValueError('compact_history must be Boolean')
        if self.expectations not in {'true','static'}:
            raise ValueError('Unknown expectations')
        if self.forecast not in {'none','oracle','ar1','holt'}:raise ValueError('Unknown forecast rule')
        from math import isfinite as _f
        for n in ('switching_cost','learning_rate','learning_reference','learning_floor'):
            v=getattr(self,n)
            if not _f(v) or v<0:raise ValueError('Invalid '+n)
        if self.learning_rate>0 and (self.learning_reference<=0 or not 0<self.learning_floor<=1):raise ValueError('Invalid learning curve')
        if self.knowledge_mode=='legacy_support' and self.expectations!='true':
            raise ValueError('Legacy VSR supports true expectations only')
        kw={f.name:getattr(self,f.name) for f in fields(LegacyConfig)}
        if kw['parent_pool']=='knowledge':kw['parent_pool']='retained'
        LegacyConfig(**kw).validate()
        if self.full_archive_access and (self.support_cost or self.support_hurdle or self.support_patience is not None):
            raise ValueError('Full-archive access has no consideration admission costs or expiry')
        return self


def _infeasible_metadata(exc):
    text=str(exc)
    if not text.startswith('Optimization not proved optimal: '):raise exc
    meta=ast.literal_eval(text.split(': ',1)[1])
    if meta.get('status')!='Infeasible':raise exc
    return meta


def _with_candidates(sc,tr,prm,integration,candidates,k,cfg):
    ds=dict(sc.designs);lives=dict(prm.life);af=dict(tr.avail_from);cm=dict(tr.cost_mult)
    tasks=None if integration is None else dict(integration.tasks)
    deps=None if integration is None else dict(integration.deployments)
    for c in candidates:
        ds[c.design.name]=c.design;lives[c.design.name]=c.life;af[c.design.name]=k
        if (c.operator=='mutation' or getattr(cfg,'learning_rate',0)>0) and c.parents[0] in cm:
            cm[c.design.name]=list(cm[c.parents[0]])
        if tasks is not None:
            required=tuple(sorted({t for parent in c.parents for t in integration.deployments[parent].tasks}))
            if cfg.new_task_effort:
                task='develop:'+c.design.name
                tasks[task]=IntegrationTask(cfg.new_task_effort,0.0,'declared new-variant integration effort')
                required=tuple(sorted((*required,task)))
            # Reference capacity is explicit and inherited from the upstream/root
            # parent. For composites it refers to upstream activity units.
            ref=integration.deployments[c.parents[0]].reference_capacity
            deps[c.design.name]=DeploymentRequirement(required,ref,cfg.pilot_fraction)
    updated=None if integration is None else replace(integration,tasks=tasks,deployments=deps)
    return replace(sc,designs=ds),replace(tr,avail_from=af,cost_mult=cm),replace(prm,life=lives),updated


def _trial(sc,tr,prm,history,k,k1,*,integration,completed,stocks,stock_state,time_limit,expectations='true',projects=None,realizability=None,capability_grants=None,extras=None):
    try:
        sol=solve_window(sc,tr,prm,k,k1,history,integration=integration,completed_tasks=completed,
                         stocks=stocks,stock_state=stock_state,time_limit=time_limit,expectations=expectations,
                         projects=projects,realizability=realizability,capability_grants=capability_grants,extras=extras)
    except RuntimeError as exc:
        return None,_infeasible_metadata(exc)
    return sol,sol['solver']


def run_vsr(sc,tr,prm,history0,mutation_rules,*,recombination_rules=(),config=None,
            integration=None,stocks=None,stock_state0=None,scheduled_candidates=None,epoch_callback=None,
            proposal_source=None,realizability=None,capability_grants0=None,projects0=None,candidate_context=None,
            realism=None):
    """Run one realized design history, including a full evidence record.

    `scheduled_candidates` is an explicit fixed-proposal/null hook for controlled
    tests. Generated runs instead use the operators and keyed random streams.
    Returned scenario includes every feasible recorded design, even economically
    rejected designs. Availability dates restrict only the investment policy's
    attention set. Their knowledge and parenthood are unaffected.
    """
    cfg=(config or VSRConfig()).validate()
    if proposal_source is not None and (scheduled_candidates is not None or mutation_rules or recombination_rules):
        raise ValueError('A generative proposal source cannot be mixed with scheduled or family-rule proposals')
    if cfg.knowledge_mode=='legacy_support':
        if proposal_source is not None or realizability is not None or projects0 or capability_grants0 or candidate_context is not None:
            raise ValueError('Generative/stateful extensions require persistent knowledge')
        if epoch_callback is not None:
            raise ValueError('Epoch recording requires persistent knowledge mode')
        kw={f.name:getattr(cfg,f.name) for f in fields(LegacyConfig)}
        if kw['parent_pool']=='knowledge':kw['parent_pool']='retained'
        return legacy_run(sc,tr,prm,history0,mutation_rules,recombination_rules=recombination_rules,
                          config=LegacyConfig(**kw),integration=integration,stocks=stocks,
                          stock_state0=stock_state0,scheduled_candidates=scheduled_candidates)
    validate_flow_system(sc)
    rules={r.family:r for r in mutation_rules}
    if len(rules)!=len(mutation_rules):raise ValueError('Duplicate mutation families')
    for r in rules.values():r.validate(sc)
    recs={r.family:r.validate() for r in recombination_rules}
    if len(recs)!=len(recombination_rules) or set(recs)&set(rules):raise ValueError('Duplicate family')
    known_families=set(rules)|set(recs)
    if any(r.upstream_family not in known_families or r.downstream_family not in known_families for r in recs.values()):raise ValueError('Unknown recombination family')
    initial_sc=sc;initial_tr=tr;initial_prm=prm;initial_integration=integration
    history=[replace(v) for v in history0]
    projects=[replace(p) for p in (projects0 or [])]
    capability_grants=list(capability_grants0 or [])
    initial_realizability=realizability
    if realizability is not None:realizability.validate(sc)
    if integration is not None:integration.validate(sc,tr.K)
    completed=None if integration is None else integration.known(history)
    initial_stocks=validate_context(sc,stocks,tr.K,0,stock_state0,None);stock_state=initial_stocks
    seeds=set(sc.designs);supported=set(seeds);knowledge=set(seeds);archive={};admissions={}
    family={r.seed_design:r.family for r in rules.values()}
    seed_by_family={f:sorted(n for n,ff in family.items() if ff==f) for f in known_families}
    admitted_at={};shelf={};lineage={};events=[];record=[];logs=[];scores={f:0. for f in known_families}
    previous_activity={};search_total=0.;support_total=0.;proposal_total=0.
    experience={}
    from .realism import forecast_trajectory
    def plan(trj,k,end):
        if cfg.forecast=='none':return trj,cfg.expectations
        return forecast_trajectory(trj,k,end,cfg.forecast),'true'
    def extras_for(k):
        x={}
        if cfg.switching_cost>0:x['switching']={'cost':cfg.switching_cost,'previous':None if k==0 else dict(previous_activity)}
        if realism and realism.get('corridors'):x['corridors']={'members':realism['corridors'],'congestion':tuple(realism.get('congestion',(1.0,0.0)))}
        return x or None
    fingerprints={fingerprint(d) for d in sc.designs.values()}
    failures=[]
    for k in range(tr.K):
        if cfg.compact_history:
            history=[v for v in history if v.alive>1e-8 and k<v.built+v.life]
        due=[p for p in projects if p.commission<=k]
        for p in due:
            history.append(Vintage(p.design,p.commission,p.capacity,p.capacity,p.annual_cost,p.fixed_cost,p.life))
        projects=[p for p in projects if p.commission>k]
        expired=[]
        if cfg.support_patience is not None:
            alive={v.design for v in history if v.alive>1e-8 and k<v.built+v.life}
            for name in sorted(supported-seeds):
                if name not in alive and k-admitted_at[name]>cfg.support_patience:
                    supported.remove(name);expired.append(name)
                    until=dict(tr.avail_until);until[name]=k-1;tr=replace(tr,avail_until=until)
        # Recent-only review is attention, not destruction of archived knowledge.
        shelved_out=[]
        opening_knowledge=set(knowledge)
        opening={'knowledge':sorted(knowledge),'available':sorted(n for n in supported if tr.available(n,k)),
                 'known_tasks':sorted(completed or ()), 'stock_state':stock_state,
                 'history':[asdict(v) for v in history], 'projects':[asdict(p) for p in projects],
                 'capability_grants':[asdict(g) for g in capability_grants]}
        event={'epoch':k,'opening':opening,'support_expired':expired,'prototype_expired':sorted(shelved_out),
               'proposals':[],'trials':[],'retained':[],'knowledge_added':[],
               'support_hurdle':cfg.support_hurdle,'attention_retired':expired}
        event['proposal_charge']=0.
        offered=[]
        if cfg.selection!='none':
            if proposal_source is not None:
                # The source receives known recipes, current activity and lives;
                # no future demands, future arrivals, path objective or target motif.
                batch=proposal_source.propose(sc,prm.life,frozenset(opening_knowledge),k,dict(previous_activity))
                if any(f in sc.flow_system.form_units for f in batch.forms):
                    raise ValueError('Generative form name collides with known vocabulary')
                if any(u not in {'tonne','MWh'} for u in batch.forms.values()):
                    raise ValueError('Unsupported generative form unit')
                if not isfinite(batch.charge) or batch.charge<0:raise ValueError('Invalid proposal charge')
                if batch.forms:
                    sc=replace(sc,flow_system=replace(sc.flow_system,form_units={**sc.flow_system.form_units,**batch.forms}))
                event['generative_attempts']=batch.attempts
                event['forms_added']=dict(batch.forms)
                event['proposal_charge']=batch.charge
                offered=list(batch.candidates)
            elif scheduled_candidates is not None:
                offered=list(scheduled_candidates.get(k,()))
            else:
                pool=seeds if cfg.parent_pool=='seeds' else (supported if cfg.parent_pool=='retained' else knowledge)
                parents={f:sorted(n for n in pool if family.get(n)==f and (n not in seeds or tr.available(n,k))) for f in rules}
                active=[f for f in sorted(rules) if parents[f]]
                rec_parents={f:(sorted(n for n in pool if family.get(n)==r.upstream_family and (n not in seeds or tr.available(n,k))),
                                sorted(n for n in pool if family.get(n)==r.downstream_family and (n not in seeds or tr.available(n,k)))) for f,r in recs.items()}
                possible=[f for f in sorted(recs) if all(rec_parents[f])]
                for slot in range(cfg.proposals_per_epoch):
                    rng=keyed_rng(cfg.seed,'proposal',k,slot)
                    do_rec=bool(possible) and (not active or rng.random()<cfg.recombination_share)
                    choices=possible if do_rec else active
                    if not choices:
                        event['proposals'].append({'slot':slot,'status':'no_eligible_parent'});continue
                    activity={f:sum(previous_activity.get(n,0.) for n,ff in family.items() if ff==f) for f in choices}
                    amax=max(activity.values(),default=0.);smax=max((scores.get(f,0.) for f in choices),default=0.)
                    ws=[(1+cfg.activity_bias*(activity[f]/amax if amax else 0))*
                        ((1-cfg.sightedness)/len(choices)+cfg.sightedness*((scores.get(f,0.)/smax) if smax else 1/len(choices))) for f in choices]
                    selected=rng.choices(choices,weights=ws,k=1)[0]
                    try:
                        if do_rec:
                            pp=rec_parents[selected];a=rng.choice(pp[0]);b=rng.choice(pp[1])
                            if a in tr.cost_mult or b in tr.cost_mult:raise ValueError('Serial composition with exogenous cost trajectories requires an explicit cost rule')
                            c=recombine(sc,a,b,recs[selected],seed=cfg.seed,epoch=k,slot=slot,lives=prm.life)
                        else:
                            parent=rng.choice(parents[selected]);c=mutate(sc,parent,rules[selected],seed=cfg.seed,epoch=k,slot=slot,life=prm.life[parent])
                        offered.append(c)
                    except ValueError as exc:
                        event['proposals'].append({'slot':slot,'family':selected,'status':'invalid','reason':str(exc)})
        shelf_hashes=set();new_known=[]
        for c in offered:
            try:
                if c.epoch!=k:raise ValueError('Proposal has wrong epoch')
                if any(p not in opening_knowledge for p in c.parents):raise ValueError('Unknown or same-epoch parent')
                validate_candidate(sc,c)
                if c.design.name in archive:raise ValueError('Knowledge name collision')
                fp=fingerprint(c.design)
                if fp in fingerprints or fp in shelf_hashes:
                    event['proposals'].append({'candidate':c.manifest(),'status':'duplicate'});continue
                n=c.design.name
                archive[n]=c;new_known.append(c);shelf_hashes.add(fp);fingerprints.add(fp)
                knowledge.add(n);family[n]=c.family;lineage[n]=c.manifest()
                event['knowledge_added'].append(n)
                event['proposals'].append({'candidate':c.manifest(),'status':'feasible'})
            except ValueError as exc:event['proposals'].append({'candidate':c.manifest(),'status':'invalid','reason':str(exc)})
        # All feasible knowledge receives physical/task metadata, independently of
        # which options the investment heuristic currently considers.
        if new_known:
            sc,tr,prm,integration=_with_candidates(sc,tr,prm,integration,new_known,k,cfg)
            if candidate_context is not None:
                tr,realizability=candidate_context.extend(sc,tr,prm,realizability,new_known,k)
            af=dict(tr.avail_from)
            for c in new_known:af[c.design.name]=tr.K+1
            tr=replace(tr,avail_from=af)
        pool=[c for n,c in sorted(archive.items()) if n not in supported and
              (cfg.retrieval=='archive' or k-c.epoch<=cfg.prototype_memory)]
        event['review_pool']=[c.design.name for c in pool]
        event['knowledge_after']=sorted(knowledge)
        if cfg.full_archive_access:
            selected=list(pool);pool=[]
        else:selected=[]
        baseline=None;values={};family_scores={f:0. for f in scores}
        if pool:
            end=min(tr.K-1,k+cfg.evaluation_horizon-1)
            _tp,_ex=plan(tr,k,end)
            baseline,meta=_trial(sc,_tp,prm,history,k,end,integration=integration,completed=completed,
                                stocks=stocks,stock_state=stock_state,time_limit=cfg.time_limit,expectations=_ex,
                       projects=projects,realizability=realizability,capability_grants=capability_grants,extras=extras_for(k))
            event['baseline']={'objective':None if baseline is None else baseline['objective']/tr.discount**k,
                               'solver':meta,'end_epoch':end}
            logs.append({'purpose':'baseline_trial','epoch':k,**meta})
            subsets=[(c,) for c in pool]
            if cfg.selection=='portfolio':
                max_size=min(cfg.max_portfolio,cfg.admission_quota,len(pool))
                for size in range(2,max_size+1):subsets.extend(combinations(pool,size))
            event['trials_deferred']=max(0,len(subsets)-cfg.max_trials_per_epoch)
            subsets=subsets[:cfg.max_trials_per_epoch]
            for subset in subsets:
                ss,tt,pp,ii=_with_candidates(sc,tr,prm,integration,subset,k,cfg)
                until=dict(tt.avail_until)
                for c in subset:until.pop(c.design.name,None)
                tt=replace(tt,avail_until=until)
                _tp,_ex=plan(tt,k,end)
                sol,meta=_trial(ss,_tp,pp,history,k,end,integration=ii,completed=completed,
                               stocks=stocks,stock_state=stock_state,time_limit=cfg.time_limit,expectations=_ex,
                       projects=projects,realizability=realizability,capability_grants=capability_grants,extras=extras_for(k))
                logs.append({'purpose':'candidate_trial','epoch':k,**meta})
                names=tuple(c.design.name for c in subset)
                obj=None if sol is None else sol['objective']/tr.discount**k
                rescue=baseline is None and sol is not None
                value=None if baseline is None or sol is None else (baseline['objective']-sol['objective'])/tr.discount**k
                if value is not None and value < -1e-7*max(1,abs(obj)):
                    raise AssertionError('Adding optional designs worsened exact trial optimum')
                value=max(0.,value) if value is not None else None
                score=None if value is None else value-(cfg.support_hurdle+cfg.support_cost)*len(subset)
                row={'designs':list(names),'objective':obj,'architectural_value':value,'net_score':score,
                     'feasibility_rescue':rescue,'solver':meta}
                event['trials'].append(row);values[names]=(row,subset)
                if len(subset)==1 and value is not None:
                    fam=subset[0].family;family_scores[fam]=max(family_scores.get(fam,0),value)
            if cfg.selection=='all':selected=pool
            elif cfg.selection=='random':
                selected=sorted(pool,key=lambda c:keyed_rng(cfg.seed,'admission',k,c.design.name).random())[:cfg.admission_quota]
            elif cfg.selection=='individual':
                eligible=[(r,sub) for (r,sub) in values.values() if len(sub)==1 and (r['feasibility_rescue'] or (r['net_score'] is not None and r['net_score']>1e-8))]
                eligible.sort(key=lambda x:(not x[0]['feasibility_rescue'], -(x[0]['net_score'] or 0),x[0]['designs']))
                selected=[s[0] for r,s in eligible[:cfg.admission_quota]]
            elif cfg.selection=='portfolio':
                eligible=[(r,sub) for (r,sub) in values.values() if len(sub)<=cfg.admission_quota and (r['feasibility_rescue'] or (r['net_score'] is not None and r['net_score']>1e-8))]
                if eligible:
                    eligible.sort(key=lambda x:(not x[0]['feasibility_rescue'],
                        x[0]['objective']+(cfg.support_hurdle+cfg.support_cost)*len(x[1]) if x[0]['feasibility_rescue'] else -x[0]['net_score'],len(x[1]),x[0]['designs']))
                    selected=list(eligible[0][1])
            scores=family_scores
        for c in selected:
            n=c.design.name;admitted_at[n]=k;supported.add(n)
            admissions.setdefault(n,[]).append(k)
        if selected:
            sc,tr,prm,integration=_with_candidates(sc,tr,prm,integration,selected,k,cfg)
            until=dict(tr.avail_until)
            for c in selected:until.pop(c.design.name,None)
            tr=replace(tr,avail_until=until)
        event['retained']=[c.design.name for c in selected]
        event['evaluation_charge']=cfg.evaluation_cost*len(event['trials'])
        event['support_charge']=cfg.support_cost*len(selected)
        search_total+=tr.discount**k*event['evaluation_charge'];support_total+=tr.discount**k*event['support_charge']
        proposal_total+=tr.discount**k*event['proposal_charge']
        end=min(tr.K-1,k+cfg.adoption_horizon-1)
        _tp,_ex=plan(tr,k,end)
        if cfg.forecast!='none':
            event['forecast']={'rule':cfg.forecast,'demand':{n:v[k:end+1] for n,v in _tp.demand_scale.items()}}
        sol,meta=_trial(sc,_tp,prm,history,k,end,integration=integration,completed=completed,
                       stocks=stocks,stock_state=stock_state,time_limit=cfg.time_limit,expectations=_ex,
                       projects=projects,realizability=realizability,capability_grants=capability_grants,extras=extras_for(k))
        logs.append({'purpose':'adoption','epoch':k,**meta})
        if sol is None:
            failures.append({'epoch':k,'reason':'infeasible_adoption','solver':meta});events.append(event);break
        e=sol['epochs'][k];record.append(e)
        if due:
            e['commissioned']=dict(e.get('commissioned',{}))
            for p in due:e['commissioned'][p.design]=e['commissioned'].get(p.design,0.)+p.capacity
        if realizability is not None:
            for g in e.get('realizability',{}).get('acquired',[]):
                capability_grants.append(CapabilityGrant(g['capability'],g['acquired'],g['ready_from'],g['ready_until']))
        if stocks is not None:stock_state={n:s['stock_end'] for n,s in e['stocks'].items()}
        if integration is not None:completed.update(e['integration']['completed_tasks'])
        for i,v in enumerate(history):v.alive=sol['hist_alive'][i,k]
        canceled=sol.get('project_cancel',{})
        projects=[replace(p,capacity=max(0.,p.capacity-canceled.get(i,0.))) for i,p in enumerate(projects)
                  if p.capacity-canceled.get(i,0.)>1e-8]
        for n,x in e['builds'].items():
            d=sc.designs[n];lead=tr.lead(n,k)
            if lead==0:
                history.append(Vintage(n,k,x,sol['new_alive'].get((n,k,k),x),d.annual_cost*tr.mult(n,k),d.fixed_cost*tr.mult(n,k),prm.life[n]))
            else:
                projects.append(Project(n,k,x,k+lead,d.annual_cost*tr.mult(n,k),d.fixed_cost*tr.mult(n,k),prm.life[n]))
        event['projects_after']=[asdict(p) for p in projects]
        previous_activity=dict(e['throughput'])
        if cfg.learning_rate>0:
            cm=dict(tr.cost_mult)
            for n,x in e['throughput'].items():
                if sc.designs[n].kind!='process' or x<=0:continue
                experience[n]=experience.get(n,0.)+x
                m=max(cfg.learning_floor,(1+experience[n]/cfg.learning_reference)**(-cfg.learning_rate))
                row=list(cm.get(n,[1.]*tr.K))
                for j in range(k+1,tr.K):row[j]=min(row[j],m)
                cm[n]=row
            tr=replace(tr,cost_mult=cm)
        event['built']={n:x for n,x in e['builds'].items() if n in lineage}
        event['used']=[n for n in lineage if e['throughput'].get(n,0)>1e-8]
        event['supported_after']=sorted(supported);events.append(event)
        if epoch_callback is not None:
            from copy import deepcopy
            epoch_callback({'epoch': k, 'operating': deepcopy(e), 'search_event': deepcopy(event), 'solver': deepcopy(meta)})
    run={'epochs':record,'status':'complete' if len(record)==tr.K else 'infeasible',
         'solver_log':[s for s in logs if s['purpose']=='adoption'],
         'integration_config':None if integration is None else integration.manifest(sc),
         'stock_config':None if stocks is None else stocks.manifest(sc),'initial_stocks':initial_stocks,
         'realizability_config':None if realizability is None else realizability.manifest(),
         'initial_projects':[asdict(p) for p in (projects0 or [])],
         'initial_capability_grants':[asdict(g) for g in (capability_grants0 or [])]}
    if cfg.switching_cost>0 or (realism and realism.get('corridors')):
        run['realism_config']={'switching_cost':cfg.switching_cost,
                               'congestion':list((realism or {}).get('congestion',(1.0,0.0))),
                               'corridors':(realism or {}).get('corridors',{})}
    run=reconcile_run(sc,tr,prm,run)
    return {'scenario':sc,'trajectory':tr,'params':prm,'integration':integration,'stocks':stocks,
            'history0':history0,'realizability':realizability,'run':run,'config':asdict(cfg),'events':events,'lineage':lineage,'solver_log':logs,
            'failures':failures,'supported_final':sorted(supported),'family':family,
            'knowledge_archive':{n:c.manifest() for n,c in archive.items()},'knowledge_final':sorted(knowledge),
            'admissions':admissions,'consideration_semantics':'investment heuristic, not knowledge/physical feasibility',
            'research_cost':search_total+support_total+proposal_total,'evaluation_cost':search_total,'support_cost':support_total,
            'proposal_cost':proposal_total,
            'initial':{'scenario':asdict(initial_sc),'trajectory':asdict(initial_tr),'params':asdict(initial_prm),
                       'history':[asdict(v) for v in history0],
                       'integration':None if initial_integration is None else initial_integration.manifest(initial_sc),
                       'realizability':None if initial_realizability is None else initial_realizability.manifest()},
            'operators':{'mutation':[asdict(r) for r in mutation_rules],'recombination':[asdict(r) for r in recombination_rules],
                         'generative':None if proposal_source is None else proposal_source.manifest(),
                         'candidate_context':None if candidate_context is None else candidate_context.manifest()}}


def audit_vsr(result,tolerance=1e-6):
    """Independent lifecycle, trial arithmetic, supply and all-in cost verification."""
    sc,tr,run=result['scenario'],result['trajectory'],result['run']
    if run['status']!='complete':raise ValueError('Cannot certify a partial VSR trajectory as complete')
    if result.get('config',{}).get('knowledge_mode')!='persistent':return legacy_audit(result,tolerance)
    initial=result['initial'];seed=set(initial['scenario']['designs']);available=set(seed)
    known=set(seed);accepted={};retired=set();evaluations=0;all_entries=0
    for k,event in enumerate(result['events']):
        if set(event['opening']['knowledge'])!=known:raise ValueError('Knowledge archive lost or invented entries')
        opening=set(known);new=set()
        for n in event['support_expired']:
            if n not in available or n in seed:raise ValueError('Invalid attention retirement')
            alive=sum(v['alive'] for v in event['opening']['history'] if v['design']==n and k<v['built']+v['life'])
            if alive>tolerance:raise ValueError('Attention expired for installed capacity')
            available.remove(n);retired.add(n)
        for proposal in event['proposals']:
            if proposal['status']=='feasible':
                c=proposal['candidate'];n=c['design']['name']
                if n in known or n in new:raise ValueError('Repeated known design')
                if any(p not in opening for p in c['parents']):raise ValueError('Unknown or same-epoch parent')
                if result['knowledge_archive'].get(n)!=c:raise ValueError('Archive changed recipe or provenance')
                if asdict(sc.designs[n])!=c['design']:raise ValueError('Physical recipe differs from knowledge')
                new.add(n)
        known.update(new)
        if set(event['knowledge_added'])!=new or set(event['knowledge_after'])!=known:
            raise ValueError('Knowledge retention violation')
        if event['prototype_expired']:raise ValueError('Persistent knowledge cannot expire with prototype patience')
        base=event.get('baseline',{}).get('objective')
        for t in event['trials']:
            evaluations+=1
            if any(n not in known for n in t['designs']):raise ValueError('Trial of unknown design')
            if base is not None and t['objective'] is not None:
                expected=max(0.,base-t['objective'])
                if abs(expected-t['architectural_value'])>tolerance*max(1,abs(base)):raise ValueError('Bad trial value')
                score=expected-(result['config']['support_hurdle']+result['config']['support_cost'])*len(t['designs'])
                if abs(score-t['net_score'])>tolerance*max(1,abs(base)):raise ValueError('Bad net trial score')
        for n in event['retained']:
            if n in available or n not in known:raise ValueError('Repeated or unknown consideration entry')
            accepted.setdefault(n,[]).append(k);available.add(n);all_entries+=1
        if abs(event['evaluation_charge']-result['config']['evaluation_cost']*len(event['trials']))>tolerance:
            raise ValueError('Bad evaluation charge')
        if abs(event['support_charge']-result['config']['support_cost']*len(event['retained']))>tolerance:
            raise ValueError('Bad consideration charge')
        generator=result.get('operators',{}).get('generative')
        expected_proposal=0. if generator is None else generator['attempt_cost']*len(event.get('generative_attempts',[]))
        if abs(event.get('proposal_charge',0)-expected_proposal)>tolerance:raise ValueError('Bad proposal effort charge')
        for n,x in run['epochs'][k]['builds'].items():
            if n not in available and x>tolerance:raise ValueError('Investment outside declared consideration set')
        if set(event['supported_after'])!=available:raise ValueError('Bad active consideration ledger')
        for state in run['epochs'][k]['operating_states']:
            if sc.flow_system is not None:
                audit_operating_state(sc,state)
                audit_flow_block(sc,state['flow'],run['epochs'][k]['capacity'])
    if result.get('config',{}).get('knowledge_mode')=='persistent':
        if set(result['knowledge_final'])!=known or accepted!=result['admissions']:
            raise ValueError('Incorrect final knowledge/admission history')
    if sc.need_system is not None:audit_need_run(sc,run)
    if sc.attribute_system is not None:audit_attribute_run(sc,run,trajectory=tr)
    if result['stocks'] is not None:audit_stock_run(sc,result['stocks'],run)
    if result['integration'] is not None:audit_integration_run(sc,result['history0'],result['integration'],run)
    ledger=independent_path_ledger(sc,tr,result['params'],run)
    error=abs(ledger['path_objective']-path_objective(tr,run))
    if error>tolerance*max(1,abs(ledger['path_objective'])):raise ValueError('Cost/objective replay mismatch')
    cost=sum(tr.discount**k*(e['evaluation_charge']+e['support_charge']+e.get('proposal_charge',0)) for k,e in enumerate(result['events']))
    if abs(cost-result['research_cost'])>tolerance:raise ValueError('Research charge mismatch')
    installed={n for e in run['epochs'] for n,x in e['builds'].items() if x>1e-8 and n in accepted}
    used={n for e in run['epochs'] for n,x in e['throughput'].items() if x>1e-8 and n in accepted}
    return {'passed':True,'objective_replay_error':error,'known_new_designs':len(known-seed),
            'known_never_considered':len((known-seed)-set(accepted)),
            'consideration_entries':all_entries,'supported_ever':len(accepted),'installed_new_designs':len(installed),
            'used_new_designs':len(used),'supported_never_used':len(set(accepted)-used),'support_expired':len(retired),
            'trial_count':evaluations,'path_cost':ledger['path_cost'],'path_objective':ledger['path_objective'],
            'path_benefit':ledger['path_benefit'],'research_cost':cost,'all_in_objective':ledger['path_objective']+cost}


def serializable_result(result,include_runs=True):
    out={k:v for k,v in result.items() if k not in {'scenario','trajectory','params','integration','stocks','history0','realizability'}}
    out['final']={'scenario':asdict(result['scenario']),'trajectory':asdict(result['trajectory']),
                  'params':asdict(result['params'])}
    out['audit']=audit_vsr(result) if result['run']['status']=='complete' else {'passed':False,'reason':'partial trajectory'}
    if not include_runs:out.pop('run',None)
    return out
