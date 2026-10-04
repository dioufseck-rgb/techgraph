"""Variation, trial selection, support retention, and adoption on the common engine.

This driver calls the existing dynamic optimizer. It does not replace service,
stock, integration, or accounting physics with an evolutionary surrogate.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from itertools import combinations
from math import isfinite
import ast
from .variation import MutationRule, RecombinationRule, Candidate, keyed_rng, fingerprint, mutate, recombine, validate_candidate
from .dynamic import solve_window, Vintage, path_cost, path_objective
from .accounting import reconcile_run, independent_path_ledger
from .flows import validate_flow_system, audit_flow_block
from .flow_audit import audit_operating_state
from .needs import audit_need_run
from .attributes import audit_attribute_run
from .stocks import validate_context, audit_stock_run
from .integration import IntegrationTask, DeploymentRequirement, audit_integration_run
from .representation import Capacity, canonical_unit


@dataclass(frozen=True)
class VSRConfig:
    proposals_per_epoch: int = 2
    selection: str = 'individual'  # individual, portfolio, random, all, none
    evaluation_horizon: int = 1
    adoption_horizon: int = 1
    support_hurdle: float = 0.0
    evaluation_cost: float = 0.0
    support_cost: float = 0.0
    admission_quota: int = 2
    max_portfolio: int = 2
    max_trials_per_epoch: int = 100
    prototype_memory: int = 0
    support_patience: int | None = None
    parent_pool: str = 'retained'  # retained or seeds (controlled proposal stream)
    sightedness: float = 0.0  # lagged family trial values, not an oracle
    activity_bias: float = 0.0
    recombination_share: float = .25
    new_task_effort: float = 0.0
    pilot_fraction: float = .1
    seed: int = 0
    time_limit: float = 60.

    def validate(self):
        for n in ['proposals_per_epoch','admission_quota','max_portfolio','max_trials_per_epoch','prototype_memory']:
            x=getattr(self,n)
            if not isinstance(x,int) or x<0:raise ValueError(f'Invalid {n}')
        if self.evaluation_horizon<1 or self.adoption_horizon<1:raise ValueError('Positive horizons required')
        if self.selection not in {'individual','portfolio','random','all','none'}:raise ValueError('Unknown selection')
        if self.parent_pool not in {'retained','seeds'}:raise ValueError('Unknown parent pool')
        if not 0<=self.sightedness<=1 or not 0<=self.recombination_share<=1 or not 0<self.pilot_fraction<=1:raise ValueError('Invalid probability/fraction')
        for n in ['support_hurdle','evaluation_cost','support_cost','activity_bias','new_task_effort']:
            if not isfinite(getattr(self,n)) or getattr(self,n)<0:raise ValueError(f'Invalid {n}')
        if self.support_patience is not None and (not isinstance(self.support_patience,int) or self.support_patience<0):raise ValueError('Invalid support patience')
        if self.max_portfolio>4:raise ValueError('This bounded portfolio implementation supports sizes <=4')
        if not isfinite(self.time_limit) or self.time_limit<=0:raise ValueError('Invalid solve time limit')
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
        if c.operator=='mutation' and c.parents[0] in cm:
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


def _trial(sc,tr,prm,history,k,k1,*,integration,completed,stocks,stock_state,time_limit):
    try:
        sol=solve_window(sc,tr,prm,k,k1,history,integration=integration,completed_tasks=completed,
                         stocks=stocks,stock_state=stock_state,time_limit=time_limit)
    except RuntimeError as exc:
        return None,_infeasible_metadata(exc)
    return sol,sol['solver']


def run_vsr(sc,tr,prm,history0,mutation_rules,*,recombination_rules=(),config=None,
            integration=None,stocks=None,stock_state0=None,scheduled_candidates=None):
    """Run one realized design history, including a full evidence record.

    `scheduled_candidates` is an explicit fixed-proposal/null hook for controlled
    tests. Generated runs instead use the operators and keyed random streams.
    Returned final scenario includes every ever-supported design for replay;
    expired support is represented by availability dates, not deleting history.
    """
    cfg=(config or VSRConfig()).validate();validate_flow_system(sc)
    rules={r.family:r for r in mutation_rules}
    if len(rules)!=len(mutation_rules):raise ValueError('Duplicate mutation families')
    for r in rules.values():r.validate(sc)
    recs={r.family:r.validate() for r in recombination_rules}
    if len(recs)!=len(recombination_rules) or set(recs)&set(rules):raise ValueError('Duplicate family')
    known_families=set(rules)|set(recs)
    if any(r.upstream_family not in known_families or r.downstream_family not in known_families for r in recs.values()):raise ValueError('Unknown recombination family')
    initial_sc=sc;initial_tr=tr;initial_prm=prm;initial_integration=integration
    history=[replace(v) for v in history0]
    if integration is not None:integration.validate(sc,tr.K)
    completed=None if integration is None else integration.known(history)
    initial_stocks=validate_context(sc,stocks,tr.K,0,stock_state0,None);stock_state=initial_stocks
    seeds=set(sc.designs);supported=set(seeds)
    family={r.seed_design:r.family for r in rules.values()}
    seed_by_family={f:sorted(n for n,ff in family.items() if ff==f) for f in known_families}
    admitted_at={};shelf={};lineage={};events=[];record=[];logs=[];scores={f:0. for f in known_families}
    previous_activity={};search_total=0.;support_total=0.
    fingerprints={fingerprint(d) for d in sc.designs.values()}
    failures=[]
    for k in range(tr.K):
        expired=[]
        if cfg.support_patience is not None:
            alive={v.design for v in history if v.alive>1e-8 and k<v.built+v.life}
            for name in sorted(supported-seeds):
                if name not in alive and k-admitted_at[name]>cfg.support_patience:
                    supported.remove(name);expired.append(name)
                    until=dict(tr.avail_until);until[name]=k-1;tr=replace(tr,avail_until=until)
        shelved_out=[n for n,c in shelf.items() if k-c.epoch>cfg.prototype_memory]
        for n in shelved_out:shelf.pop(n)
        opening={'available':sorted(n for n in supported if tr.available(n,k)),
                 'known_tasks':sorted(completed or ()), 'stock_state':stock_state,
                 'history':[asdict(v) for v in history]}
        event={'epoch':k,'opening':opening,'support_expired':expired,'prototype_expired':sorted(shelved_out),
               'proposals':[],'trials':[],'retained':[],'support_hurdle':cfg.support_hurdle}
        offered=[]
        if cfg.selection!='none':
            if scheduled_candidates is not None:
                offered=list(scheduled_candidates.get(k,()))
            else:
                pool=seeds if cfg.parent_pool=='seeds' else supported
                parents={f:sorted(n for n in pool if family.get(n)==f and tr.available(n,k)) for f in rules}
                active=[f for f in sorted(rules) if parents[f]]
                rec_parents={f:(sorted(n for n in pool if family.get(n)==r.upstream_family and tr.available(n,k)),
                                sorted(n for n in pool if family.get(n)==r.downstream_family and tr.available(n,k))) for f,r in recs.items()}
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
        shelf_hashes={fingerprint(c.design) for c in shelf.values()}
        for c in offered:
            try:
                if c.epoch!=k:raise ValueError('Proposal has wrong epoch')
                if any(p not in supported or not tr.available(p,k) for p in c.parents):raise ValueError('Unsupported or unavailable parent')
                validate_candidate(sc,c)
                if c.design.name in shelf:raise ValueError('Prototype name collision')
                fp=fingerprint(c.design)
                if fp in fingerprints or fp in shelf_hashes:
                    event['proposals'].append({'candidate':c.manifest(),'status':'duplicate'});continue
                shelf[c.design.name]=c;shelf_hashes.add(fp)
                event['proposals'].append({'candidate':c.manifest(),'status':'feasible'})
            except ValueError as exc:event['proposals'].append({'candidate':c.manifest(),'status':'invalid','reason':str(exc)})
        # Prototypes whose parents lost support cannot be tried or retained.
        pool=[c for n,c in sorted(shelf.items()) if all(p in supported for p in c.parents)]
        selected=[];baseline=None;values={};family_scores={f:0. for f in scores}
        if pool:
            end=min(tr.K-1,k+cfg.evaluation_horizon-1)
            baseline,meta=_trial(sc,tr,prm,history,k,end,integration=integration,completed=completed,
                                stocks=stocks,stock_state=stock_state,time_limit=cfg.time_limit)
            event['baseline']={'objective':None if baseline is None else baseline['objective']/tr.discount**k,
                               'solver':meta,'end_epoch':end}
            logs.append({'purpose':'baseline_trial','epoch':k,**meta})
            subsets=[(c,) for c in pool]
            if cfg.selection=='portfolio':
                max_size=min(cfg.max_portfolio,cfg.admission_quota,len(pool))
                for size in range(2,max_size+1):subsets.extend(combinations(pool,size))
            if len(subsets)>cfg.max_trials_per_epoch:raise ValueError('Trial budget exceeded: reduce prototype shelf or portfolio size')
            for subset in subsets:
                ss,tt,pp,ii=_with_candidates(sc,tr,prm,integration,subset,k,cfg)
                sol,meta=_trial(ss,tt,pp,history,k,end,integration=ii,completed=completed,
                               stocks=stocks,stock_state=stock_state,time_limit=cfg.time_limit)
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
            n=c.design.name;family[n]=c.family;lineage[n]=c.manifest();admitted_at[n]=k;supported.add(n)
            fingerprints.add(fingerprint(c.design));shelf.pop(n,None)
        if selected:
            sc,tr,prm,integration=_with_candidates(sc,tr,prm,integration,selected,k,cfg)
        event['retained']=[c.design.name for c in selected]
        event['evaluation_charge']=cfg.evaluation_cost*len(event['trials'])
        event['support_charge']=cfg.support_cost*len(selected)
        search_total+=tr.discount**k*event['evaluation_charge'];support_total+=tr.discount**k*event['support_charge']
        end=min(tr.K-1,k+cfg.adoption_horizon-1)
        sol,meta=_trial(sc,tr,prm,history,k,end,integration=integration,completed=completed,
                       stocks=stocks,stock_state=stock_state,time_limit=cfg.time_limit)
        logs.append({'purpose':'adoption','epoch':k,**meta})
        if sol is None:
            failures.append({'epoch':k,'reason':'infeasible_adoption','solver':meta});events.append(event);break
        e=sol['epochs'][k];record.append(e)
        if stocks is not None:stock_state={n:s['stock_end'] for n,s in e['stocks'].items()}
        if integration is not None:completed.update(e['integration']['completed_tasks'])
        for i,v in enumerate(history):v.alive=sol['hist_alive'][i,k]
        for n,x in e['builds'].items():
            d=sc.designs[n]
            history.append(Vintage(n,k,x,sol['new_alive'].get((n,k,k),x),d.annual_cost*tr.mult(n,k),d.fixed_cost*tr.mult(n,k),prm.life[n]))
        previous_activity=dict(e['throughput'])
        event['built']={n:x for n,x in e['builds'].items() if n in lineage}
        event['used']=[n for n in lineage if e['throughput'].get(n,0)>1e-8]
        event['supported_after']=sorted(supported);events.append(event)
    run={'epochs':record,'status':'complete' if len(record)==tr.K else 'infeasible',
         'solver_log':[s for s in logs if s['purpose']=='adoption'],
         'integration_config':None if integration is None else integration.manifest(sc),
         'stock_config':None if stocks is None else stocks.manifest(sc),'initial_stocks':initial_stocks}
    run=reconcile_run(sc,tr,prm,run)
    return {'scenario':sc,'trajectory':tr,'params':prm,'integration':integration,'stocks':stocks,
            'history0':history0,'run':run,'config':asdict(cfg),'events':events,'lineage':lineage,'solver_log':logs,
            'failures':failures,'supported_final':sorted(supported),'family':family,
            'research_cost':search_total+support_total,'evaluation_cost':search_total,'support_cost':support_total,
            'initial':{'scenario':asdict(initial_sc),'trajectory':asdict(initial_tr),'params':asdict(initial_prm),
                       'history':[asdict(v) for v in history0],
                       'integration':None if initial_integration is None else initial_integration.manifest(initial_sc)},
            'operators':{'mutation':[asdict(r) for r in mutation_rules],'recombination':[asdict(r) for r in recombination_rules]}}


def audit_vsr(result,tolerance=1e-6):
    """Independent lifecycle, trial arithmetic, supply and all-in cost verification."""
    sc,tr,run=result['scenario'],result['trajectory'],result['run']
    if run['status']!='complete':raise ValueError('Cannot certify a partial VSR trajectory as complete')
    initial=result['initial'];available=set(initial['scenario']['designs']);accepted={};retired=set();evaluations=0
    for k,event in enumerate(result['events']):
        for n in event['support_expired']:
            if n not in available or n in initial['scenario']['designs']:raise ValueError('Invalid support expiry')
            alive=sum(v['alive'] for v in event['opening']['history'] if v['design']==n and k<v['built']+v['life'])
            if alive>tolerance:raise ValueError('Support expired for installed capacity')
            available.remove(n);retired.add(n)
        for p in event['proposals']:
            if p['status']=='feasible':
                c=p['candidate']
                if any(parent not in available for parent in c['parents']):raise ValueError('Candidate from unsupported parent')
        base=event.get('baseline',{}).get('objective')
        for t in event['trials']:
            evaluations+=1
            if base is not None and t['objective'] is not None:
                expected=max(0.,base-t['objective'])
                if abs(expected-t['architectural_value'])>tolerance*max(1,abs(base)):raise ValueError('Bad trial value')
        for n in event['retained']:
            if n in accepted or n not in result['lineage']:raise ValueError('Repeated or unknown admission')
            accepted[n]=k;available.add(n)
        for n,x in run['epochs'][k]['builds'].items():
            if n not in available and x>tolerance:raise ValueError('Investment in unsupported technology')
        for state in run['epochs'][k]['operating_states']:
            if sc.flow_system is not None:
                audit_operating_state(sc,state)
                audit_flow_block(sc,state['flow'],run['epochs'][k]['capacity'])
    if sc.need_system is not None:audit_need_run(sc,run)
    if sc.attribute_system is not None:audit_attribute_run(sc,run,trajectory=tr)
    if result['stocks'] is not None:audit_stock_run(sc,result['stocks'],run)
    if result['integration'] is not None:audit_integration_run(sc,result['history0'],result['integration'],run)
    ledger=independent_path_ledger(sc,tr,result['params'],run)
    error=abs(ledger['path_objective']-path_objective(tr,run))
    if error>tolerance*max(1,abs(ledger['path_objective'])):raise ValueError('Cost/objective replay mismatch')
    cost=sum(tr.discount**k*(e['evaluation_charge']+e['support_charge']) for k,e in enumerate(result['events']))
    if abs(cost-result['research_cost'])>tolerance:raise ValueError('Research charge mismatch')
    installed={n for e in run['epochs'] for n,x in e['builds'].items() if x>1e-8 and n in accepted}
    used={n for e in run['epochs'] for n,x in e['throughput'].items() if x>1e-8 and n in accepted}
    return {'passed':True,'objective_replay_error':error,'supported_ever':len(accepted),'installed_new_designs':len(installed),
            'used_new_designs':len(used),'supported_never_used':len(set(accepted)-used),'support_expired':len(retired),
            'trial_count':evaluations,'path_cost':ledger['path_cost'],'path_objective':ledger['path_objective'],
            'path_benefit':ledger['path_benefit'],'research_cost':cost,'all_in_objective':ledger['path_objective']+cost}


def serializable_result(result,include_runs=True):
    out={k:v for k,v in result.items() if k not in {'scenario','trajectory','params','integration','stocks','history0'}}
    out['final']={'scenario':asdict(result['scenario']),'trajectory':asdict(result['trajectory']),
                  'params':asdict(result['params'])}
    out['audit']=audit_vsr(result) if result['run']['status']=='complete' else {'passed':False,'reason':'partial trajectory'}
    if not include_runs:out.pop('run',None)
    return out
