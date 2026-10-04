"""v4 diagnostic/pilot runner: resumable, one process, same trace format as v3."""
import argparse,gzip,json,os,sys,time,warnings
from pathlib import Path
warnings.filterwarnings('ignore')
from run_demand_sweep import execute,publish
from techgraph.discovery import ident

def main():
    ap=argparse.ArgumentParser();ap.add_argument('specs');ap.add_argument('out');a=ap.parse_args()
    out=Path(a.out);(out/'traces').mkdir(parents=True,exist_ok=True)
    specs=json.load(open(a.specs))
    for i,spec in enumerate(specs):
        rid=ident(spec,'v4_');path=out/'traces'/(rid+'.json.gz')
        if path.exists():continue
        t=time.time();p=execute(spec);publish(path,p);r=p['record']
        au=p.get('result',{}).get('audit',{})
        with open(out/'log.jsonl','a') as f:
            f.write(json.dumps({'i':i,'run_id':rid,'spec':spec,'status':r['status'],'epochs':r['completed_epochs'],
                                'seconds':round(time.time()-t,1),'audit':au.get('passed'),
                                'error':p.get('exception',{}).get('message')})+'\n')
if __name__=='__main__':main()
