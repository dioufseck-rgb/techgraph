"""Matched effects and temporal-shape measurements; no simulator changes."""
from pathlib import Path
from collections import defaultdict, Counter
import argparse, gzip, hashlib, json
import numpy as np
from analyze_stateful_campaign import extract
from techgraph.discovery import canonical
from demand_sweep import TREATMENTS

def sha(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def tv(a,b): return .5*sum(abs(a.get(k,0)-b.get(k,0)) for k in a.keys()|b.keys())
def stats(values, tolerance=1e-7):
    x=np.asarray(list(values),dtype=float)
    if not len(x):return {'n':0}
    return dict(n=len(x),mean=float(x.mean()),median=float(np.median(x)),
                q25=float(np.quantile(x,.25)),q75=float(np.quantile(x,.75)),
                minimum=float(x.min()),maximum=float(x.max()),
                lower=int(sum(x < -tolerance)),tied=int(sum(abs(x)<=tolerance)),higher=int(sum(x>tolerance)))

def extended_extract(t):
    h,rows=extract(t)
    ds=t['result']['final']['scenario']['designs']
    core={n for n,d in ds.items() if d['kind']=='process'}
    signatures={n:canonical({side:sorted((p['form'],p['location'],round(p['coefficient'],6)) for p in ds[n][side])
                            for side in ('input_ports','output_ports')}) for n in core}
    previous=set();previous_functional=set();seen=set();prev_weights={}
    for k,(row,e) in enumerate(zip(rows,t['result']['run']['epochs'])):
        state=next(s for s in e['operating_states'] if s['name']=='normal')
        weights=defaultdict(float)
        for n,q in state['throughput'].items():
            if n in core and q>1e-7:weights[signatures[n]]+=q
        total=sum(weights.values())
        weights={n:q/total for n,q in weights.items()} if total else {}
        physical=defaultdict(float)
        for v in e['vintages']:
            if v['design'] in core and v['alive']>1e-7:physical[v['design']]+=v['alive']
        current=set(row['major_core']);functional={signatures[n] for n in current}
        gained=functional-previous_functional;lost=previous_functional-functional
        change='mixed' if gained and lost else 'expansion' if gained else 'contraction' if lost else 'unchanged'
        key=tuple(sorted(functional))
        row.update(process_capacity=sum(physical.values()),process_capacity_by_design=dict(physical),
                   functional_weights=weights,functional_core=sorted(functional),functional_change_kind=change,
                   functional_tv=tv(weights,prev_weights) if k else 0.,
                   functional_recurrence=int(k>=8 and functional!=previous_functional and key in seen),
                   expansion=int(k>0 and change=='expansion'),contraction=int(k>0 and change=='contraction'),
                   mixed_substitution=int(k>0 and change=='mixed'))
        for threshold in (.0005,.002):
            row[f'core_{threshold}']=sorted(n for n,q in state['throughput'].items() if n in core and q>max(1e-7,threshold*row['required']))
        if k>=7:seen.add(key)
        previous=current;previous_functional=functional;prev_weights=weights
    start=rows[4:8];late=rows[60:68];interior=rows[8:68]
    mean=lambda rs,key:float(np.mean([x[key] for x in rs]))
    required=sum(x['required'] for x in interior);delivered=sum(x['delivered'] for x in interior)
    capacity0=mean(start,'process_capacity');delivery0=mean(start,'delivered')
    cap_path=np.array([x['process_capacity'] for x in rows[7:68]])
    cap_moves=np.diff(cap_path)
    substantial_moves=np.sign(cap_moves[abs(cap_moves)>.001*max(1e-7,capacity0)])
    cap_path_length=float(abs(cap_moves).sum())
    h['shape']={
        'reconfiguration_pct':100*sum(x['major_core_changed'] for x in interior)/60,
        'functional_reconfiguration_pct':100*sum(x['functional_config_changed'] for x in interior)/60,
        'capacity_change_pct':100*(mean(late,'process_capacity')/max(1e-7,capacity0)-1),
        'delivery_change_pct':100*(mean(late,'delivered')/max(1e-7,delivery0)-1),
        'capacity_path_length_pct':100*cap_path_length/max(1e-7,capacity0),
        'capacity_path_directness':float(abs(cap_path[-1]-cap_path[0])/cap_path_length) if cap_path_length>1e-7 else 0.,
        'capacity_direction_reversals':int(sum(substantial_moves[1:]!=substantial_moves[:-1])),
        'mean_functional_tv':mean(interior,'functional_tv'),
        'functional_recurrences':sum(x['functional_recurrence'] for x in interior),
        'expansions':sum(x['expansion'] for x in interior),'contractions':sum(x['contraction'] for x in interior),
        'mixed_substitutions':sum(x['mixed_substitution'] for x in interior),
        'fill_pct':100*delivered/required,'required_total':required,'delivered_total':delivered,
        'cross_site_activity_per_delivered':sum(x['transport_activity'] for x in interior)/max(1e-7,delivered),
        'ordered_capacity':sum(x['ordered_capacity'] for x in interior),
        'canceled_capacity':sum(x['canceled_capacity'] for x in interior),
        'new_designs_used':len({n for x in rows[:68] for n in x['active_all'] if n not in t['inputs']['scenario']['designs']}),
        'new_major_designs_used':len({n for x in rows[:68] for n in x['major_core'] if n not in t['inputs']['scenario']['designs']}),
        'new_design_uptake_pct':100*len({n for x in rows[:68] for n in x['active_all'] if n not in t['inputs']['scenario']['designs']})/max(1,rows[67]['new_known']),
        'direct_cost':sum(x['cost']-x['shortfall_penalty'] for x in interior),
        'direct_cost_per_delivered':sum(x['cost']-x['shortfall_penalty'] for x in interior)/max(1e-7,delivered),
        'mean_stock':mean(interior,'stock_end'),
        'resource_hhi':mean(interior,'resource_site_hhi'),
    }
    for threshold in (.0005,.002):
        h['shape'][f'reconfiguration_pct_{threshold}']=100*sum(rows[k][f'core_{threshold}']!=rows[k-1][f'core_{threshold}'] for k in range(8,68))/60
    h['matching']={
        'scenario':sha(t['inputs']['scenario']),'assets':sha(t['inputs']['history']),
        'readiness':sha(t['inputs']['realizability']),'stocks':sha(t['inputs']['stocks']),
        'lineage':sha(t['result']['lineage']),'warmup':sha(t['result']['run']['epochs'][:8]),
    }
    # Final boundary controls compare epoch 0..68 inclusive: horizon-four
    # windows are identical there in a 72-period and a 96-period history.
    h['prefix69_epochs_sha']=sha(t['result']['run']['epochs'][:69])
    return h,rows

def summarize(histories,eby,attempts,planned):
    main=[h for h in histories if h['spec']['epochs']==72]
    by={(h['spec']['seed'],h['spec']['treatment'],h['spec']['epochs']):h for h in histories}
    groups={t:{'histories':len(hs),'metrics':{m:stats(h['shape'][m] for h in hs) for m in hs[0]['shape']}}
            for t in TREATMENTS if (hs:=[h for h in main if h['spec']['treatment']==t])}
    contrasts=[(t,'constant') for t in TREATMENTS if t!='constant']
    contrasts += [('geo_far50','geo_ref50'),('geo_far80','geo_ref80'),('geo_return80','geo_ref80'),
                  ('irregular85','irregular0'),('cycle16','cycle24'),('mix_a80','mix_a65'),('mix_b80','mix_b65')]
    effects={};pairs=[]
    for treatment,control in contrasts:
        cs=[]
        for s in sorted({h['spec']['seed'] for h in main}):
            a=by.get((s,treatment,72));b=by.get((s,control,72))
            if not a or not b:continue
            for key in a['matching']:assert a['matching'][key]==b['matching'][key],(s,treatment,control,key)
            ar=eby[a['run_id']];br=eby[b['run_id']]
            late=range(60,68)
            deltas={m:a['shape'][m]-b['shape'][m] for m in a['shape']}
            record={'seed':s,'treatment':treatment,'control':control,'treated_run':a['run_id'],'control_run':b['run_id'],
                    'deltas':deltas,
                    'late_functional_tv':float(np.mean([tv(ar[k]['functional_weights'],br[k]['functional_weights']) for k in late])),
                    'late_same_functional_set':sum(ar[k]['functional_core']==br[k]['functional_core'] for k in late),
                    'late_same_design_set':sum(ar[k]['major_core']==br[k]['major_core'] for k in late),
                    'late_capacity_relative_l1':float(np.mean([sum(abs(ar[k]['process_capacity_by_design'].get(n,0)-br[k]['process_capacity_by_design'].get(n,0))
                         for n in ar[k]['process_capacity_by_design'].keys()|br[k]['process_capacity_by_design'].keys())/max(1e-7,br[k]['process_capacity']) for k in late]))}
            cs.append(record);pairs.append(record)
        if cs:
            effects[f'{treatment}__{control}']={'pairs':len(cs),'metrics':{m:stats(c['deltas'][m] for c in cs) for m in cs[0]['deltas']},
                'late_functional_tv':stats(c['late_functional_tv'] for c in cs),
                'late_same_functional_every_epoch':sum(c['late_same_functional_set']==8 for c in cs),
                'late_capacity_relative_l1':stats(c['late_capacity_relative_l1'] for c in cs)}
    long=[]
    for h in histories:
        if h['spec']['epochs']!=96:continue
        b=by.get((h['spec']['seed'],h['spec']['treatment'],72))
        if b:
            assert h['prefix69_epochs_sha']==b['prefix69_epochs_sha']
            long.append({'seed':h['spec']['seed'],'treatment':h['spec']['treatment'],'identical_prefix69':True})
    return {'planned':planned,'recorded':len(attempts),'statuses':dict(Counter(a['status'] for a in attempts)),
            'complete':len(histories),'main_histories':len(main),'worlds':len({h['spec']['seed'] for h in main}),
            'complete_periods':sum(h['completed_epochs'] for h in histories),
            'groups':groups,'effects':effects,'long_controls':long,
            'matching':'all available contrast pairs match complete initial scenario/assets/readiness/stocks, invention lineage and realized warmup'},pairs

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',default='results/demand_v3');ap.add_argument('--partial',action='store_true');a=ap.parse_args()
    root=Path(a.data);out=root/'analysis';out.mkdir(exist_ok=True);cache=out/'cache';cache.mkdir(exist_ok=True)
    manifest=json.loads((root/'manifest.json').read_text())
    for p,v in manifest['source_hashes'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==v,p
    analyzer_hash=hashlib.sha256(Path(__file__).read_bytes()+Path('analyze_stateful_campaign.py').read_bytes()).hexdigest()
    hs=[];eby={};attempts=[];hashes={}
    for p in sorted((root/'traces').glob('*.json.gz')):
        raw=p.read_bytes();trace_hash=hashlib.sha256(raw).hexdigest();cp=cache/p.name
        cached=json.loads(gzip.decompress(cp.read_bytes())) if cp.exists() else None
        if cached and cached['trace_hash']==trace_hash and cached['analyzer_hash']==analyzer_hash:
            rec=cached['record'];h=cached['history'];rows=cached['rows']
        else:
            t=json.loads(gzip.decompress(raw));rec=t['record'];h=None;rows=[]
            if rec['status']=='complete':h,rows=extended_extract(t)
            cp.write_bytes(gzip.compress(canonical(dict(trace_hash=trace_hash,analyzer_hash=analyzer_hash,record=rec,history=h,rows=rows)).encode(),compresslevel=3,mtime=0))
        attempts.append(rec);hashes[rec['run_id']]=trace_hash
        if h:hs.append(h);eby[h['run_id']]=rows
    if not a.partial:
        assert len(attempts)==len(manifest['specs'])
        assert hashes==json.loads((root/'trace_hashes.json').read_text())
    summary,pairs=summarize(hs,eby,attempts,len(manifest['specs']))
    for name,value in [('summary',summary),('paired_effects',pairs),('analysis_trace_hashes',hashes)]:
        (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    for name,rows in [('histories',hs),('epochs',(e for rr in eby.values() for e in rr))]:
        with gzip.open(out/(name+'.jsonl.gz'),'wt') as f:
            for row in rows:f.write(canonical(row)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('groups','effects','long_controls')},indent=2))

if __name__=='__main__':main()
