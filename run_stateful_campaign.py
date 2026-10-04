"""Frozen broad stateful campaign with single-parent, read-verified publication."""
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from dataclasses import asdict
from collections import Counter
import argparse,gzip,hashlib,json,multiprocessing,os,time,traceback
from techgraph.generative import WorldConfig,SearchConfig,RecipeSearch
from techgraph.stateful import StateConfig,make_stateful_world,audit_stateful
from techgraph.vsr import VSRConfig,run_vsr,serializable_result
from techgraph.discovery import canonical,jsonable,ident,classify_exception
from techgraph.variation import keyed_rng

PROFILES=('full','no_search','no_inventories','no_capabilities','no_preparation')

def specs(mode):
    if mode=='smoke':
        return [dict(seed=106+i,volatility=.18,profile='full',epochs=12,horizon=4) for i in range(4)]
    if mode=='timing':return [dict(seed=110,volatility=.18,profile='full',epochs=64,horizon=4)]
    result=[dict(seed=seed,volatility=vol,profile=p,epochs=64,horizon=4) for seed in range(120,152) for vol in (0.,.18) for p in PROFILES]
    # These longer controls are chosen by seed before observing any trajectories.
    result += [dict(seed=seed,volatility=vol,profile='full',epochs=96,horizon=4) for seed in range(120,128) for vol in (0.,.18)]
    return result


def prepare(spec):
    seed=spec['seed'];medium=seed%2==1;dense=(seed//2)%2==1
    wc=WorldConfig(seed=seed,epochs=spec['epochs'],locations=3 if medium else 2,forms=6 if medium else 5,
        extra_recipes=(8 if medium else 6) if dense else (4 if medium else 2),edge_probability=.7 if dense else .1,
        demand_volatility=spec['volatility'])
    rng=keyed_rng(seed,'stateful-world-sampling')
    cfg=StateConfig(inventories=spec['profile']!='no_inventories',capabilities=spec['profile']!='no_capabilities',
        preparation=spec['profile']!='no_preparation',supply_margin=rng.uniform(.95,1.65),inventory_periods=rng.uniform(.5,2.),
        relocation_fix=bool(spec.get('relocation_fix',False)))
    w=make_stateful_world(wc,cfg)
    search_cfg=SearchConfig(seed=2000+seed)
    policy=VSRConfig(selection='none' if spec['profile']=='no_search' else 'all',full_archive_access=True,
        adoption_horizon=spec['horizon'],evaluation_horizon=spec['horizon'],expectations='static',compact_history=True,time_limit=30.)
    return w,search_cfg,policy


def execute(spec):
    started=time.monotonic();rid=ident(spec,'state_');events=[]
    record={'run_id':rid,'spec':spec,'ancestry_id':f'stateful-seed-{spec["seed"]}','allocation':'exploration','status':'started','expected_epochs':spec['epochs']}
    payload={'record':record}
    def observe(event):events.append(event)
    try:
        w,search_cfg,cfg=prepare(spec)
        payload.update(inputs=jsonable({'scenario':asdict(w.scenario),'trajectory':asdict(w.trajectory),'params':asdict(w.params),
            'history':[asdict(v) for v in w.history],'stocks':w.stocks.manifest(w.scenario),
            'realizability':None if w.realizability is None else w.realizability.manifest(),'metadata':w.metadata}),
            search_config=asdict(search_cfg),policy=asdict(cfg))
        r=run_vsr(w.scenario,w.trajectory,w.params,w.history,(),config=cfg,stocks=w.stocks,
            realizability=w.realizability,candidate_context=w.candidate_context,
            proposal_source=RecipeSearch(search_cfg) if spec['profile']!='no_search' else None,epoch_callback=observe)
        record['status']='complete' if r['run']['status']=='complete' else 'certified_infeasible'
        r['stateful_audit']=audit_stateful(r)
        payload['result']=serializable_result(r)
        assert len(events)==len(r['run']['epochs'])
        # No redundant full journal for successful histories. Callback identities
        # are checked against the authoritative result before publication.
        payload['callback_epochs']=[e['epoch'] for e in events]
    except Exception as exc:
        record['status'],metadata=classify_exception(exc)
        payload['exception']={'type':type(exc).__name__,'message':str(exc),'solver':metadata,'traceback':traceback.format_exc()}
        payload['completed_epoch_prefix']=jsonable(events)
    record['completed_epochs']=len(events);record['elapsed_seconds']=time.monotonic()-started
    return jsonable(payload)


def publish(path,payload):
    raw=canonical(payload).encode();packed=gzip.compress(raw,compresslevel=5,mtime=0)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('wb') as f:f.write(packed);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    assert path.read_bytes()==packed,'Publication bytes differ'
    assert gzip.decompress(packed)==raw
    return hashlib.sha256(packed).hexdigest()


def write_json(path,payload):
    raw=(canonical(payload)+'\n').encode();tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path);assert path.read_bytes()==raw


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['smoke','timing','main'],default='main');ap.add_argument('--out',required=True);ap.add_argument('--workers',type=int,default=4);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);(out/'traces').mkdir(exist_ok=True)
    planned=specs(a.mode)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('techgraph').rglob('*.py'))}
    hashes['run_stateful_campaign.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest={'campaign':'stateful-v2-'+a.mode,'output_identity':out.name,'specs':planned,'source_hashes':hashes,'allocation':'all exploration',
        'target_phenomena':[],'sampling':'fresh seeds 120..151, 2 sizes x 2 graph priors; each constant/varying demand and 5 matched profiles',
        'controls':'remove one of inventory, capability, preparation or search; all remaining primitives and proposal draws keyed identically',
        'longer_runs':'first 8 seeds, both demand conditions, selected before observing outcomes',
        'publication':'one parent writer; fsync + byte equality + decompression verification; partial/error histories retained',
        'policy':'one coordinating planner; horizon 4, static demand expectations, no access to future inventions',
        'scope':'one abstract mass-flow grammar, multiple priors; no empirical or cross-domain representativeness claim'}
    mp=out/'manifest.json'
    if mp.exists():assert json.loads(mp.read_text())==manifest,'Frozen source/output mismatch; use new output identity'
    else:write_json(mp,manifest)
    records=[];hashes_out={};pending=[]
    for spec in planned:
        path=out/'traces'/(ident(spec,'state_')+'.json.gz')
        if path.exists():
            packed=path.read_bytes();p=json.loads(gzip.decompress(packed));assert p['record']['spec']==spec
            records.append(p['record']);hashes_out[p['record']['run_id']]=hashlib.sha256(packed).hexdigest()
        else:pending.append(spec)
    started=time.monotonic()
    with ProcessPoolExecutor(max_workers=a.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        todo=iter(pending);jobs={}
        for _ in range(a.workers):
            spec=next(todo,None)
            if spec is not None:jobs[pool.submit(execute,spec)]=spec
        while jobs:
            done,_=wait(jobs,return_when=FIRST_COMPLETED)
            for f in done:
                spec=jobs.pop(f);payload=f.result();r=payload['record'];rid=r['run_id']
                hashes_out[rid]=publish(out/'traces'/(rid+'.json.gz'),payload)
                records.append(r)
                write_json(out/'progress.json',{'done':len(records),'planned':len(planned),'latest':r,'elapsed_seconds':time.monotonic()-started})
                print(len(records),len(planned),r['status'],r['completed_epochs'],round(r['elapsed_seconds'],2),rid,flush=True)
                spec=next(todo,None)
                if spec is not None:jobs[pool.submit(execute,spec)]=spec
    coverage={'histories':len(records),'statuses':dict(Counter(r['status'] for r in records)),'completed_epochs':sum(r['completed_epochs'] for r in records),
        'elapsed_seconds':time.monotonic()-started,'ancestries':len({r['ancestry_id'] for r in records}),'all_exploratory':True}
    write_json(out/'runs.json',sorted(records,key=lambda r:r['run_id']));write_json(out/'trace_hashes.json',hashes_out);write_json(out/'coverage.json',coverage)
    print(json.dumps(coverage,indent=2),flush=True)

if __name__=='__main__':main()
