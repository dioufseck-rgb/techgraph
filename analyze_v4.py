"""Analysis of v4 diagnostics against the archived v3 cohort (same metric code)."""
import gzip,json,glob,sys,warnings,numpy as np
warnings.filterwarnings('ignore')
from analyze_demand_sweep import extended_extract
BASE='/home/claude/d3/techgraph_demand_sweep_v3/source/techgraph/results/demand_v3_resolved/analysis/histories.jsonl.gz'
base={}
for l in gzip.open(BASE):
    h=json.loads(l)
    if h['spec']['epochs']==72:base[(h['spec']['seed'],h['spec']['treatment'],'v3')]=h['shape']
def load(d,label):
    out={}
    for f in glob.glob(f'results/{d}/traces/*.json.gz'):
        t=json.loads(gzip.decompress(open(f,'rb').read()))
        if t['record']['status']!='complete':continue
        h,_=extended_extract(t);s=t['record']['spec']
        out[(s['seed'],s['treatment'],label(s))]=h['shape']
    return out
def med(x):x=np.asarray(x);return dict(n=len(x),median=float(np.median(x)),min=float(x.min()),max=float(x.max()),pos=int((x>1e-9).sum()),neg=int((x<-1e-9).sum()))
res={}
S={**base,**load('d1',lambda s:s['realism']['forecast']),**load('d2',lambda s:'switch')}
seeds=range(300,324)
# D1: ordering effect under three forecast rules
res['d1']={}
for pol in ('v3','oracle','ar1'):
    ss=[s for s in seeds if (s,'irregular0',pol) in S and (s,'irregular85',pol) in S]
    if not ss:continue
    eff=[S[s,'irregular85',pol]['fill_pct']-S[s,'irregular0',pol]['fill_pct'] for s in ss]
    res['d1'][pol]={'ordering_fill_effect_pp':med(eff),
        'fill_irregular0':med([S[s,'irregular0',pol]['fill_pct'] for s in ss]),
        'fill_irregular85':med([S[s,'irregular85',pol]['fill_pct'] for s in ss]),
        'switching_effect_pp':med([S[s,'irregular85',pol]['reconfiguration_pct']-S[s,'irregular0',pol]['reconfiguration_pct'] for s in ss]),
        'mean_stock_irregular0':med([S[s,'irregular0',pol]['mean_stock'] for s in ss])}
# D2: switching cost
res['d2']={}
for pol in ('v3','switch'):
    row={}
    for t in ('constant','cycle16','irregular0','irregular85'):
        ss=[s for s in seeds if (s,t,pol) in S]
        if ss:row[t]={m:med([S[s,t,pol][m] for s in ss]) for m in ('reconfiguration_pct','functional_reconfiguration_pct','mean_functional_tv','fill_pct','direct_cost_per_delivered')}
    for a,b in (('cycle16','constant'),('irregular85','irregular0')):
        ss=[s for s in seeds if (s,a,'switch') in S and (s,b,'switch') in S]
        if ss:row[f'{a}-{b}']={m:med([S[s,a,pol][m]-S[s,b,pol][m] for s in ss]) for m in ('reconfiguration_pct','fill_pct')}
    res['d2'][pol]=row
json.dump(res,open('v4_diagnostics.json','w'),indent=1)
def show(r,ind=''):
    for k,v in r.items():
        if isinstance(v,dict) and 'median' in v:print(f"{ind}{k}: median {v['median']:.3f} [{v['min']:.2f},{v['max']:.2f}] +{v['pos']}/-{v['neg']} n={v['n']}")
        elif isinstance(v,dict):print(ind+k);show(v,ind+'  ')
show(res)
