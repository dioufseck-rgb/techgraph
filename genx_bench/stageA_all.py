import os, sys, json, io, contextlib, pandas as pd
SCAN=os.environ.get('GENX_SCAN_DIR','scan')
os.environ.setdefault('TECHGRAPH_BACKEND','scipy')
from stageA_techgraph import build, genx_reference
from techgraph.model import solve
rows=[]
for d in sorted(os.listdir(SCAN)):
    case=os.path.join(SCAN,d)
    sc,land,ex=build(case); res=solve(sc,land,existing=ex)
    gx,gcap=genx_reference(case); tg=365*res.objective
    capdiff=max(abs(res.capacity.get(k,0)-v) for k,v in gcap.items())
    # hourly dispatch: GenX power.csv rows are time steps after 3 header rows
    p=pd.read_csv(f'{case}/results/power.csv'); p=p[p.Resource.astype(str).str.startswith('t')].set_index('Resource')
    dmax=0.0
    for name,ser in res.activity.items():
        if name in p.columns:
            dmax=max(dmax,max(abs(a-b) for a,b in zip(ser['output'],p[name].astype(float))))
        elif name.endswith('_power') and name[:-6] in p.columns:
            dmax=max(dmax,max(abs(a-b) for a,b in zip(ser['backward'],p[name[:-6]].astype(float))))
    simul=max((max(min(f,b) for f,b in zip(s['forward'],s['backward'])) for n,s in res.activity.items() if n.endswith('_power')),default=0)
    rows.append(dict(day=d,genx=gx/1e6,techgraph=tg/1e6,rel=(tg-gx)/gx,max_cap_diff_MW=capdiff,max_dispatch_diff_MW=dmax,simul_MW=simul))
    print(rows[-1],flush=True)
df=pd.DataFrame(rows); df.to_csv('stageA_all_days.csv',index=False)
print(df.to_string(index=False,float_format=lambda x:f'{x:.3g}'))
