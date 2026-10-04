"""Five-view discovery measurements over unchanged stateful traces.

All summaries are exploratory. A run, seed, design occurrence, period and return
are distinct units; repeated conditions are not independent world replications.
"""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,gzip,hashlib,json,statistics as stats
import numpy as np
from techgraph.discovery import canonical

EPS=1e-7

def spread(values):
    v=list(values)
    return {'min':min(v),'median':stats.median(v),'max':max(v)} if v else None


def extract(t):
    r=t['record'];R=t['result'];initial=t['inputs'];sc=R['final']['scenario'];L=R['lineage'];epochs=R['run']['epochs']
    assert R['audit']['passed'] and R['stateful_audit']['passed']
    assert len(epochs)==r['expected_epochs']==r['completed_epochs']
    assert t['callback_epochs']==list(range(len(epochs)))
    base=set(initial['scenario']['designs']);ds=sc['designs'];known=set(base)
    active=[];installed=[];alive_vintages=[];first={};first_order={};major_ever=set();major_prev=set();major_configs=set();functional_prev=set();functional_configs=set();weights_prev={};known_at={n:c['epoch'] for n,c in L.items()};rows=[];previous=set()
    prior_seen=set();dormant=set();returns=[];stock_limit=sum(v['capacity'] for v in initial['stocks']['stocks'].values())
    for k,(e,event) in enumerate(zip(epochs,R['events'])):
        assert set(event['opening']['knowledge'])==known
        for n in event['knowledge_added']:assert set(L[n]['parents'])<=known
        known.update(event['knowledge_added']);assert set(event['knowledge_after'])==known
        state=next(s for s in e['operating_states'] if s['name']=='normal');flow=state['flow']
        used={n for n,q in state['throughput'].items() if q>EPS}
        core={n for n in used if ds[n]['kind']=='process'}
        physical=defaultdict(float)
        for v in e['vintages']:
            if v['alive']>EPS:physical[v['design']]+=v['alive']
        installed.append(set(physical));alive_vintages.append({(v['design'],v['built']) for v in e['vintages'] if v['alive']>EPS})
        active.append(core)
        for n in used:first.setdefault(n,k)
        for n,q in e['builds'].items():
            if q>EPS:first_order.setdefault(n,k)
        for n in core&dormant:
            last=max(j for j in range(k) if n in active[j])
            same=set.intersection(*(alive_vintages[j] for j in range(last,k+1)))
            returns.append({'design':n,'last_active':last,'return_epoch':k,'gap':k-last-1,
                'retained_same_vintage':any(x[0]==n for x in same),
                'ordered_during_gap':any(epochs[j]['builds'].get(n,0)>EPS for j in range(last+1,k+1)),
                'commissioned_at_return':e['commissioned'].get(n,0)>EPS})
        dormant=(dormant|prior_seen)-core;prior_seen.update(core)
        demand=sum(sum(q['target_rates']) for q in flow['demands'].values())
        unmet=sum(sum(q['unmet_rates']) for q in flow['demands'].values())
        delivered=sum(sum(q['delivered_rates']) for q in flow['demands'].values())
        stocks=e['stocks'];deposit=sum(sum(s['deposits']) for s in stocks.values());withdraw=sum(sum(s['withdrawals']) for s in stocks.values())
        resource_rates={n:sum(q['rates']) for n,q in flow['resources'].items()};total_resource=sum(resource_rates.values())
        hhi=sum((q/total_resource)**2 for q in resource_rates.values()) if total_resource>EPS else 0.
        total_activity=sum(state['throughput'][n] for n in core)
        transport_activity=sum(state['throughput'][n] for n in core if len({p['location'] for p in ds[n]['input_ports']+ds[n]['output_ports']})>1)
        stock_end=sum(s['stock_end'] for s in stocks.values())
        ready=set(e.get('realizability',{}).get('ready',[]))
        blocked=sum(max(0,q-e['capacity'].get(n,0.)) for n,q in physical.items())
        forms_used={p['form'] for n in core for p in ds[n]['input_ports']+ds[n]['output_ports']}
        major={n for n in core if state['throughput'][n]>max(EPS,.001*demand)}
        major_ever.update(major-base);major_configs.add(tuple(sorted(major)))
        def signature(n):
            d=ds[n]
            return canonical({side:sorted((p['form'],p['location'],round(p['coefficient'],6)) for p in d[side]) for side in ('input_ports','output_ports')})
        functional={signature(n) for n in major};functional_configs.add(tuple(sorted(functional)))
        weights={n:state['throughput'][n]/total_activity for n in core} if total_activity>EPS else {}
        flow_tv=0. if not k else .5*sum(abs(weights.get(n,0)-weights_prev.get(n,0)) for n in set(weights)|set(weights_prev))
        row={'run_id':r['run_id'],'epoch':k,'known':len(known),'new_known':len(known-base),'new_active':len(used-base),
            'active_core':sorted(core),'active_all':sorted(used),'installed_physical':sorted(physical),
            'known_forms':len(flow['form_units']),'used_forms':len(forms_used),
            'core_changed':int(k>0 and core!=previous),'major_core_changed':int(k>0 and major!=major_prev),
            'functional_config_changed':int(k>0 and functional!=functional_prev),'activity_mix_total_variation':flow_tv,
            'major_core':sorted(major),'core_jaccard_change':0. if not k else len(core^previous)/max(1,len(core|previous)),
            'required':demand,'delivered':delivered,'unmet':unmet,'fill':delivered/demand if demand else 1.,
            'stock_end':stock_end,'stock_limit':stock_limit,'stock_deposit':deposit,'stock_withdraw':withdraw,
            'stock_loss':sum(s['natural_loss'] for s in stocks.values()),
            'wip_capacity':sum(p['capacity'] for p in event.get('projects_after',[])),
            'ordered_capacity':sum(e['builds'].values()),'commissioned_capacity':sum(e['commissioned'].values()),
            'canceled_capacity':e['stranded_work'],'capabilities_ready':len(ready),
            'capabilities_acquired':len(e.get('realizability',{}).get('acquired',[])),
            'installed_but_unusable_capacity':blocked,
            'resource_used':total_resource,'resource_site_hhi':hhi,'process_activity':total_activity,
            'transport_activity':transport_activity,'active_process_hhi':sum((state['throughput'][n]/total_activity)**2 for n in core) if total_activity>EPS else 0.,
            'cost':sum(e.get(x,0) for x in ('capital','fom','ops_cost','integration_cost','realizability_cost','stock_cost')),
            'shortfall_penalty':sum(q['penalty']*sum(flow['demands'][q['name']]['unmet_rates']) for q in sc['flow_system']['demands']),
            'research_charge':sum(event.get(x,0) for x in ('proposal_charge','evaluation_charge','support_charge'))}
        rows.append(row);previous=core;major_prev=major;functional_prev=functional;weights_prev=weights
    new_used=set(first)-base
    ancestry=[]
    for n in sorted(new_used):
        parents=L[n]['parents'];never=[p for p in parents if p in L and p not in first]
        unused_before=[p for p in parents if p in L and first.get(p,10**9)>=L[n]['epoch']]
        ancestry.append({'design':n,'operator':L[n]['operator'],'generation':L[n]['metadata']['generation'],
            'discovered':known_at[n],'first_order':first_order.get(n),'first_use':first[n],'discovery_use_lag':first[n]-known_at[n],
            'parents':parents,'generated_parents_never_used':never,'generated_parents_unused_before_creation':unused_before})
    required=sum(e['required'] for e in rows);delivered=sum(e['delivered'] for e in rows)
    lags=[x['discovery_use_lag'] for x in ancestry];changes=sum(e['core_changed'] for e in rows)
    changed_k=[e['epoch'] for e in rows if e['core_changed']];stable_intervals=np.diff([0,*changed_k,len(rows)]).tolist()
    metrics={'new_known':len(known-base),'new_ever_used':len(new_used),'new_fraction_used':len(new_used)/max(1,len(known-base)),
        'max_known_generation':max((c['metadata']['generation'] for c in L.values()),default=0),
        'max_operated_generation':max((c['generation'] for c in ancestry),default=0),
        'lagged_adoptions':sum(l>0 for l in lags),'median_adoption_lag':stats.median(lags) if lags else 0.,'max_adoption_lag':max(lags,default=0),
        'unused_ancestor_adoptions':sum(bool(c['generated_parents_never_used']) for c in ancestry),
        'unused_before_creation_adoptions':sum(bool(c['generated_parents_unused_before_creation']) for c in ancestry),
        'core_changes':changes,'major_core_changes':sum(e['major_core_changed'] for e in rows),
        'functional_config_changes':sum(e['functional_config_changed'] for e in rows),
        'functional_configurations':len(functional_configs),'major_core_configurations':len(major_configs),
        'new_major_ever_used':len(major_ever),'mean_activity_mix_variation':stats.mean(e['activity_mix_total_variation'] for e in rows[1:]),
        'core_changes_interior':sum(e['core_changed'] for e in rows[4:-4]),
        'core_configurations':len({tuple(sorted(a)) for a in active}),'longest_stable_interval':max(stable_intervals),
        'return_episodes':len(returns),'returns_with_same_vintage':sum(x['retained_same_vintage'] for x in returns),
        'return_episodes_interior':sum(4<=x['return_epoch']<len(rows)-4 for x in returns),
        'required_total':required,'delivered_total':delivered,'unmet_total':required-delivered,'service_fill':delivered/required if required else 1.,
        'shortfall_epochs':sum(e['unmet']>EPS for e in rows),
        'stock_active_epochs':sum(e['stock_end']>EPS for e in rows),'withdrawal_epochs':sum(e['stock_withdraw']>EPS for e in rows),
        'stock_withdraw_total':sum(e['stock_withdraw'] for e in rows),'stock_deposit_total':sum(e['stock_deposit'] for e in rows),
        'stock_loss_total':sum(e['stock_loss'] for e in rows),'stock_peak':max(e['stock_end'] for e in rows),
        'stock_final':rows[-1]['stock_end'],'capability_acquisitions':sum(e['capabilities_acquired'] for e in rows),
        'blocked_installed_epochs':sum(e['installed_but_unusable_capacity']>EPS for e in rows),
        'wip_epochs':sum(e['wip_capacity']>EPS for e in rows),'wip_peak':max(e['wip_capacity'] for e in rows),
        'canceled_capacity':sum(e['canceled_capacity'] for e in rows),'cancellation_epochs':sum(e['canceled_capacity']>EPS for e in rows),
        'ordered_capacity':sum(e['ordered_capacity'] for e in rows),'resource_site_hhi_mean':stats.mean(e['resource_site_hhi'] for e in rows),
        'transport_activity_per_delivered':sum(e['transport_activity'] for e in rows)/max(EPS,delivered),
        'all_in_objective':R['audit']['all_in_objective'],'shortfall_penalty_total':sum(e['shortfall_penalty'] for e in rows),
        'direct_cost_excluding_penalty':R['audit']['all_in_objective']-sum(e['shortfall_penalty'] for e in rows)}
    h={**r,'schema':'stateful-history-2.0','metrics':metrics,'adoption_events':ancestry,'return_events':returns,
        'world_metadata':initial['metadata'],'initial_catalog_size':len(base),'final_catalog_size':len(known),
        'initial_graph_fingerprint':hashlib.sha256(canonical({n:{k:d[k] for k in ('kind','input_ports','output_ports','form','loc')} for n,d in initial['scenario']['designs'].items()}).encode()).hexdigest(),
        'lineage_sha256':hashlib.sha256(canonical(L).encode()).hexdigest(),
        'initial_history_sha256':hashlib.sha256(canonical(initial['history']).encode()).hexdigest(),
        'trace_audits':{'physical_and_accounting':R['audit']['passed'],'stateful':R['stateful_audit']['passed']}}
    return h,rows


def summarize(histories,epochs):
    base=[h for h in histories if h['spec']['epochs']==64 and 'replay' not in h['spec']];full=[h for h in base if h['spec']['profile']=='full']
    byspec={(h['spec']['seed'],h['spec']['volatility'],h['spec']['profile'],h['spec']['epochs']):h for h in histories}
    profiles={}
    if full:
        for profile in sorted({h['spec']['profile'] for h in base}):
            cases=[h for h in base if h['spec']['profile']==profile]
            profiles[profile]={'histories':len(cases),'any_adoption':sum(h['metrics']['new_ever_used']>0 for h in cases),
                'any_unused_ancestor':sum(h['metrics']['unused_ancestor_adoptions']>0 for h in cases),
                'any_return':sum(h['metrics']['return_episodes']>0 for h in cases),
                'metrics':{key:spread(h['metrics'][key] for h in cases) for key in full[0]['metrics']}}
    comparisons=[]
    for h in full:
        seed,vol=h['spec']['seed'],h['spec']['volatility'];m=h['metrics']
        for profile in ('no_search','no_inventories','no_capabilities','no_preparation'):
            g=byspec.get((seed,vol,profile,64))
            if g is None:continue
            n=g['metrics'];comparisons.append({'full':h['run_id'],'control':g['run_id'],'profile':profile,'seed':seed,'volatility':vol,
                'same_initial_assets':h['initial_history_sha256']==g['initial_history_sha256'],
                'same_proposal_lineage':h['lineage_sha256']==g['lineage_sha256'],
                'full_minus_control_cost_percent':100*(m['all_in_objective']-n['all_in_objective'])/n['all_in_objective'],
                'full_minus_control_fill_points':100*(m['service_fill']-n['service_fill']),
                **{f'full_minus_control_{key}':m[key]-n[key] for key in ['core_changes','major_core_changes','functional_config_changes','mean_activity_mix_variation','core_changes_interior','new_ever_used','return_episodes','canceled_capacity','transport_activity_per_delivered']}})
    controls={}
    for profile in sorted({c['profile'] for c in comparisons}):
        cs=[c for c in comparisons if c['profile']==profile]
        controls[profile]={'pairs':len(cs),'same_initial_assets':sum(c['same_initial_assets'] for c in cs),
            'same_proposal_lineage':sum(c['same_proposal_lineage'] for c in cs)}
        if profile!='no_search':assert all(c['same_proposal_lineage'] for c in cs),('proposal mismatch',profile)
        for field in ['cost_percent','fill_points','core_changes','major_core_changes','functional_config_changes','mean_activity_mix_variation','core_changes_interior','new_ever_used','return_episodes','canceled_capacity','transport_activity_per_delivered']:
            vals=[c['full_minus_control_'+field] for c in cs]
            controls[profile][field]={'negative':sum(v< -1e-6 for v in vals),'zero':sum(abs(v)<=1e-6 for v in vals),'positive':sum(v>1e-6 for v in vals),**spread(vals)}
    groups={}
    for vol in (0.,.18):
        hs=[h for h in full if h['spec']['volatility']==vol]
        if hs:groups[str(vol)]={'runs':len(hs),'any_returns':sum(h['metrics']['return_episodes']>0 for h in hs),
            'any_delayed_adoption':sum(h['metrics']['lagged_adoptions']>0 for h in hs),
            'metrics':{key:spread(h['metrics'][key] for h in hs) for key in full[0]['metrics']}}
    eby=defaultdict(list)
    for e in epochs:eby[e['run_id']].append(e)
    boundaries=[]
    for h in histories:
        if h['spec']['epochs']!=96:continue
        g=byspec.get((h['spec']['seed'],h['spec']['volatility'],'full',64))
        if g is None:continue
        a,b=eby[g['run_id']],eby[h['run_id']]
        # Horizon 4: periods 0..60 have identical evaluation windows before the
        # 64-period boundary starts shortening them at period 61.
        fields=['delivered','unmet','stock_end','ordered_capacity','canceled_capacity']
        boundaries.append({'short':g['run_id'],'long':h['run_id'],'seed':h['spec']['seed'],'volatility':h['spec']['volatility'],
            'prefix61_max_absolute_difference':max(abs(a[k][f]-b[k][f]) for k in range(61) for f in fields),
            'prefix61_identical_core_paths':all(a[k]['active_core']==b[k]['active_core'] for k in range(61)),
            'last3_short_fill':sum(x['delivered'] for x in a[61:64])/sum(x['required'] for x in a[61:64]),
            'same3_long_fill':sum(x['delivered'] for x in b[61:64])/sum(x['required'] for x in b[61:64])})
    return {'complete_histories':len(histories),'base_histories_64':len(base),'full_histories_64':len(full),'long_histories_96':sum(h['spec']['epochs']==96 for h in histories),
        'observed_epochs':len(epochs),'independent_seed_ancestries':len({h['spec']['seed'] for h in histories}),
        'initial_graphs':len({h['initial_graph_fingerprint'] for h in base}),'profiles':profiles,'full_by_demand':groups,'controls':controls,'terminal_comparisons':boundaries},comparisons


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',default='results/stateful_campaign_v2');ap.add_argument('--out');ap.add_argument('--allow-partial',action='store_true');a=ap.parse_args()
    root=Path(a.data);out=Path(a.out) if a.out else root/'analysis';out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((root/'manifest.json').read_text())
    for path,sha in manifest['source_hashes'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha,('source mismatch',path)
    expected_hashes=json.loads((root/'trace_hashes.json').read_text()) if (root/'trace_hashes.json').exists() else None
    hs=[];es=[];exceptions=[];hashes={}
    files=sorted((root/'traces').glob('*.json.gz'))
    if not a.allow_partial:assert len(files)==len(manifest['specs'])
    for p in files:
        packed=p.read_bytes();t=json.loads(gzip.decompress(packed));r=t['record'];hashes[r['run_id']]=hashlib.sha256(packed).hexdigest()
        if expected_hashes is not None:assert expected_hashes[r['run_id']]==hashes[r['run_id']]
        if r['status']!='complete':exceptions.append(r);continue
        h,e=extract(t);hs.append(h);es.extend(e)
    summary,comparisons=summarize(hs,es);summary.update(recorded_attempts=len(files),exceptions=exceptions,source_hashes_match=True,all_completed_trace_audits_passed=True,
        analysis_status='partial exploratory' if a.allow_partial else 'complete exploratory')
    for name,rows in [('histories',hs),('epochs',es)]:
        with gzip.open(out/(name+'.jsonl.gz'),'wt') as f:
            for row in rows:f.write(canonical(row)+'\n')
    for name,data in [('summary',summary),('matched_comparisons',comparisons),('trace_hashes',hashes)]:
        (out/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['profiles','full_by_demand','controls','terminal_comparisons']},indent=2))
    print('Controls:',json.dumps(summary['controls'],indent=2))

if __name__=='__main__':main()
