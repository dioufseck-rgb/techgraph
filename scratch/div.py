import gzip,json,glob,warnings
warnings.filterwarnings('ignore')
from run_stateful_campaign import execute
arch={}
for f in glob.glob('/home/claude/sv2/source/techgraph/results/stateful_campaign_v2b/traces/*.json.gz'):
    t=json.loads(gzip.decompress(open(f,'rb').read()));s=t['record']['spec'];arch[(s['seed'],s['volatility'])]=t['result']
for seed,vol,fix in [(133,0.,False)]:
    A=arch[(seed,vol)];B=execute(dict(seed=seed,volatility=vol,profile='full',epochs=64,horizon=4,relocation_fix=fix))['result']
    first=None;mx=0
    for k,(ea,eb) in enumerate(zip(A['run']['epochs'],B['run']['epochs'])):
        d=max(abs(ea['throughput'].get(n,0)-eb['throughput'].get(n,0)) for n in set(ea['throughput'])|set(eb['throughput']))
        mx=max(mx,d)
        if d>1e-7 and first is None:first=k
    relo={n:c for n,c in A['lineage'].items() if c['operator']=='relocation'}
    ub={n for e in B['run']['epochs'] for n,x in e['throughput'].items() if x>1e-8}
    print(seed,vol,'fix',fix,'obj diff %.4f'%(B['audit']['all_in_objective']-A['audit']['all_in_objective']),'first divergence',first,'max throughput diff %.3g'%mx,
          'relocated used:',[(n,c['epoch'],c['metadata'].get('destination')) for n,c in relo.items() if n in ub])
    if fix:
        caps=lambda R:sorted({a['capability'] for e in R['run']['epochs'] for a in e.get('realizability',{}).get('acquired',[])})
        print('  capabilities acquired only in v3:',sorted(set(caps(A))-set(caps(B))),' only with fix:',sorted(set(caps(B))-set(caps(A))))
