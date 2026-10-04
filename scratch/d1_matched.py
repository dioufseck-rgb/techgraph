import gzip,json,glob,warnings,numpy as np
warnings.filterwarnings('ignore')
from analyze_demand_sweep import extended_extract
BASE='/home/claude/d3/techgraph_demand_sweep_v3/source/techgraph/results/demand_v3_resolved/analysis/histories.jsonl.gz'
S={};meta={}
for l in gzip.open(BASE):
    h=json.loads(l)
    if h['spec']['epochs']==72:
        S[(h['spec']['seed'],h['spec']['treatment'],'static')]=h['shape']
        m=h['world_metadata'];meta[h['spec']['seed']]=m['total_input_rate']/m['demand_base_total']
for f in glob.glob('results/d1/traces/*.json.gz'):
    t=json.loads(gzip.decompress(open(f,'rb').read()));h,_=extended_extract(t);s=t['record']['spec']
    S[(s['seed'],s['treatment'],'oracle')]=h['shape']
seeds=sorted({k[0] for k in S if k[2]=='oracle'})
M=['fill_pct','reconfiguration_pct','mean_functional_tv','mean_stock','direct_cost_per_delivered','capacity_path_length_pct']
def q(x):x=np.asarray(x);return f"median {np.median(x):7.3f}  [{x.min():.2f}, {x.max():.2f}]  +{(x>1e-9).sum()}/-{(x<-1e-9).sum()}"
out={}
print('worlds',seeds)
for t in ('irregular0','irregular85'):
    print('\n'+t)
    for m in M:
        a=[S[s,t,'static'][m] for s in seeds];b=[S[s,t,'oracle'][m] for s in seeds]
        print(f'  {m:28s} static {np.median(a):8.3f} | oracle {np.median(b):8.3f} | oracle-static {q(np.subtract(b,a))}')
        out[f'{t}:{m}']=dict(static=a,oracle=b)
print('\nordering effect (irregular85 - irregular0)')
for m in ('fill_pct','reconfiguration_pct','mean_functional_tv'):
    for pol in ('static','oracle'):
        e=[S[s,'irregular85',pol][m]-S[s,'irregular0',pol][m] for s in seeds]
        print(f'  {m:22s} {pol:7s} {q(e)}')
        out[f'order:{m}:{pol}']=e
print('\nper world fill (pp): static0 static85 | oracle0 oracle85 | margin')
for s in seeds:
    print(s,' '.join(f"{S[s,t,p]['fill_pct']:6.2f}" for p in ('static','oracle') for t in ('irregular0','irregular85')),f'{meta[s]:.2f}')
json.dump({'worlds':seeds,'data':out},open('d1_matched.json','w'))
