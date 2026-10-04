import json,sys,time,warnings
warnings.filterwarnings('ignore')
from run_demand_sweep import execute
cases={'bins':dict(bins=4,intra_amplitude=.3),'corridors':dict(corridors=True,congestion_cost=1.0),
 'lumps':dict(lump_share=.3),'use_bias':dict(use_bias=4.0),'raw_forms':dict(raw_forms=2),
 'variants':dict(variant_share=.3),'capabilities':dict(capability_cost_scale=10.0,capability_domains='function',relocation_fix=True),
 'switching':dict(switching_cost=.5),'forecast_ar1':dict(forecast='ar1'),'forecast_oracle':dict(forecast='oracle'),
 'learning':dict(learning_rate=.234)}
names=sys.argv[1:] or list(cases)
for n in names:
    spec=dict(seed=301,treatment='cycle16',epochs=72,horizon=4,realism=cases[n]) if n!='resource' else dict(seed=301,treatment='resource_shift50',epochs=72,horizon=4)
    t=time.time();p=execute(spec);r=p['record']
    au=p.get('result',{}).get('audit',{})
    print(n,r['status'],r['completed_epochs'],round(time.time()-t,1),'audit',au.get('passed'),'obj',round(au.get('all_in_objective',float('nan')),2),
          'stateful',p.get('result',{}).get('stateful_audit',{}).get('passed'),p.get('exception',{}).get('message','')[:300],flush=True)
