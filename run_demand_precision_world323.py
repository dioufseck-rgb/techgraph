"""Re-run the complete affected world at stricter native solver precision.

The model and audit tolerances are unchanged. Original attempts remain intact.
SciPy forwards these native HiGHS options; installed HighsOptions confirms them.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from collections import Counter
import argparse,json,hashlib,multiprocessing,time,warnings
from scipy.optimize._highspy._core import HighsOptions
import techgraph._scipy_lp as backend
from run_demand_sweep import execute, publish, write_json
from demand_sweep import TREATMENTS
from techgraph.discovery import ident

PRECISION={'mip_feasibility_tolerance':1e-9,'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9}

def execute_strict(spec):
    opt=HighsOptions()
    for k,v in PRECISION.items():setattr(opt,k,v);assert getattr(opt,k)==v
    original_milp=backend.milp;original_linprog=backend.linprog
    def milp(*args,**kwargs):
        kwargs['options']={**kwargs.get('options',{}),**PRECISION}
        return original_milp(*args,**kwargs)
    def linprog(*args,**kwargs):
        kwargs['options']={**kwargs.get('options',{}),**{k:v for k,v in PRECISION.items() if k!='mip_feasibility_tolerance'}}
        return original_linprog(*args,**kwargs)
    backend.milp=milp;backend.linprog=linprog
    try:
        # Expected SciPy forwarding notice; the native options are validated above.
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',message='Unrecognized options detected.*')
            payload=execute(spec)
        payload['solver_precision']=PRECISION
        return payload
    finally:backend.milp=original_milp;backend.linprog=original_linprog

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pilot',action='store_true');ap.add_argument('--workers',type=int,default=2);a=ap.parse_args()
    out=Path('results/demand_v3_precision_323_pilot' if a.pilot else 'results/demand_v3_precision_323');out.mkdir(exist_ok=True);(out/'traces').mkdir(exist_ok=True)
    ts=['pulse40'] if a.pilot else TREATMENTS
    specs=[]
    for t in ts:
        base=dict(seed=323,treatment=t,epochs=72,horizon=4)
        specs.append({**base,'solver_precision':'HiGHS feasibility 1e-9','repair_of':ident(base,'demand_')})
    manifest={'campaign':'demand-v3-precision-repair','specs':specs,'precision':PRECISION,
        'reason':'seed323 growth20 failed unchanged 1e-6 stock audit with accumulated feasibility drift',
        'selection':'all 20 demand conditions of affected world, not only the failed history',
        'scientific_changes':[],'audit_tolerance_changed':False,
        'source_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_json(out/'manifest.json',manifest)
    records=[];hashes={}
    with ProcessPoolExecutor(max_workers=a.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        jobs=[pool.submit(execute_strict,s) for s in specs]
        for f in as_completed(jobs):
            p=f.result();r=p['record'];hashes[r['run_id']]=publish(out/'traces'/(r['run_id']+'.json.gz'),p);records.append(r)
            print(len(records),len(specs),r['status'],r['spec']['treatment'],round(r['elapsed_seconds'],2),flush=True)
    write_json(out/'runs.json',records);write_json(out/'trace_hashes.json',hashes)
    write_json(out/'coverage.json',{'histories':len(records),'statuses':dict(Counter(r['status'] for r in records))})

if __name__=='__main__':main()
