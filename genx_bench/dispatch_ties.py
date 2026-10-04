import os, sys, pandas as pd
os.environ.setdefault('TECHGRAPH_BACKEND','scipy')
from stageA_techgraph import build
from techgraph.model import solve
day=sys.argv[1]; case=os.path.join(os.environ.get('GENX_SCAN_DIR','scan'),day)
sc,land,ex=build(case); res=solve(sc,land,existing=ex)
p=pd.read_csv(f'{case}/results/power.csv'); p=p[p.Resource.astype(str).str.startswith('t')].set_index('Resource').astype(float)
ch=pd.read_csv(f'{case}/results/charge.csv'); ch=ch[ch.Resource.astype(str).str.startswith('t')].set_index('Resource').astype(float)
fl=pd.read_csv(f'{case}/results/flow.csv'); fl=fl[fl.Line.astype(str).str.startswith('t')].set_index('Line').astype(float) if 'Line' in fl.columns else None
D={}
for n,s in res.activity.items():
    if n in p.columns: D[n]=[a-b for a,b in zip(s['output'],p[n])]
    elif n.endswith('_power'):
        g=n[:-6]; D[g+' disch']=[a-b for a,b in zip(s['backward'],p[g])]; D[g+' charge']=[a-b for a,b in zip(s['forward'],ch[g])]
df=pd.DataFrame(D); df.index=range(1,25)
big=df.loc[:,(df.abs()>1e-3).any()]
print(f'{day}: resources whose dispatch differs (Techgraph minus GenX, MW)')
print(big.round(1).to_string())
# cost of each dispatch at Techgraph's per-MWh costs
vc={n:d.var_cost for n,d in sc.designs.items()}
cost=lambda col,diff: vc.get(col.split(' ')[0] if ' ' not in col else col.split(' ')[0]+'_power',0)*sum(diff)
print('net variable-cost effect of the differences, $/day:', round(sum(cost(c,big[c]) for c in big.columns),6))
