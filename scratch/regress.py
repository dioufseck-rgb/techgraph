import gzip,json,glob,sys,warnings
warnings.filterwarnings('ignore')
from run_demand_sweep import execute
from techgraph.discovery import ident
ARCH='/home/claude/d3/techgraph_demand_sweep_v3/source/techgraph/results'
def archived(spec):
    rid=ident(spec,'demand_')
    for d in ['demand_v3_precision','demand_v3']:
        f=f'{ARCH}/{d}/traces/{rid}.json.gz'
        try:return json.loads(gzip.decompress(open(f,'rb').read()))
        except FileNotFoundError:pass
for seed,t in [(300,"constant")]:
    spec=dict(seed=seed,treatment=t,epochs=72,horizon=4)
    a=archived(spec);p=execute(spec)
    A=a['result'];B=p['result']
    oa=A['audit']['all_in_objective'];ob=B['audit']['all_in_objective']
    same=all(ea['throughput']==eb['throughput'] and ea['builds']==eb['builds'] for ea,eb in zip(A['run']['epochs'],B['run']['epochs']))
    print(seed,t,'archived',oa,'v4',ob,'diff',abs(oa-ob),'identical throughput/builds',same,'lineage same',A['lineage']==B['lineage'])
    m=0
    for ea,eb in zip(A['run']['epochs'],B['run']['epochs']):
        for key in ('throughput','builds'):
            ks=set(ea[key])|set(eb[key])
            m=max([m]+[abs(ea[key].get(n,0)-eb[key].get(n,0)) for n in ks])
    print('   max abs difference in throughput/builds:',m)
