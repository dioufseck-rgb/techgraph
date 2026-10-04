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

from demand_sweep import prepare, specs


def execute(spec):
    started=time.monotonic();rid=ident(spec,'demand_');events=[]
    record={'run_id':rid,'spec':spec,'ancestry_id':f'demand-world-{spec["seed"]}','allocation':'exploration','status':'started','expected_epochs':spec['epochs']}
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
            proposal_source=RecipeSearch(search_cfg),epoch_callback=observe,
            realism=getattr(w,'realism_runtime',None))
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
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['smoke','main'],default='main');ap.add_argument('--out',required=True);ap.add_argument('--workers',type=int,default=4);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);(out/'traces').mkdir(exist_ok=True)
    planned=specs(a.mode)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('techgraph').rglob('*.py'))}
    hashes['run_demand_sweep.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    hashes['demand_sweep.py']=hashlib.sha256(Path('demand_sweep.py').read_bytes()).hexdigest()
    manifest={'campaign':'demand-v3-'+a.mode,'output_identity':out.name,'specs':planned,'source_hashes':hashes,
        'allocation':'all exploration','target_phenomena':[],
        'sampling':'24 fresh seeds 300..323; 3/4 sites crossed with sparse/dense priors; 6 seeds per cell; 6 initial forms',
        'controls':'20 matched demand conditions; common initial catalogue, assets, capabilities, stocks, supply and recursive proposal stream',
        'timing':'72 periods; shared demand epochs 0..7; principal forcing epochs 8..55; primary analysis 8..67 excludes final four periods',
        'longer_runs':'first 4 seeds, 5 named conditions each, 96 periods; chosen before inspecting outcomes',
        'geography':'both services share site weights; reference site has highest initial resource use; distant is farthest Euclidean site; every site has resources',
        'temporal_matching':'cycle16/cycle24 share volume and amplitude; irregular0/85 share exactly the same realized marginal distribution but different ordering; trends and pulse do not match baseline cumulative demand',
        'publication':'one parent writer; fsync, byte equality, decompression; retain all outcomes',
        'policy':'one coordinator; horizon 4; static current demand expectation; full archive; exogenous proposal effort',
        'scope':'one abstract mass-flow grammar; demand treatment effects under a bounded policy; no calibration or attractor claim'}
    mp=out/'manifest.json'
    if mp.exists():assert json.loads(mp.read_text())==manifest,'Frozen source/output mismatch; use new output identity'
    else:write_json(mp,manifest)
    records=[];hashes_out={};pending=[]
    for spec in planned:
        path=out/'traces'/(ident(spec,'demand_')+'.json.gz')
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
