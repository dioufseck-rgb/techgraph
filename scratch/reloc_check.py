import gzip,json,glob,warnings,sys
warnings.filterwarnings('ignore')
from run_stateful_campaign import execute
arch={}
for f in glob.glob('/home/claude/sv2/source/techgraph/results/stateful_campaign_v2b/traces/*.json.gz'):
    t=json.loads(gzip.decompress(open(f,'rb').read()));s=t['record']['spec']
    arch[(s['seed'],s['volatility'])]=t['result']
out=open('reloc_check.jsonl','a')
for seed in range(120,152):
    for vol in (0.,.18):
        A=arch[(seed,vol)]
        spec=dict(seed=seed,volatility=vol,profile='full',epochs=64,horizon=4,relocation_fix=True)
        p=execute(spec);B=p['result']
        relo=[n for n,c in A['lineage'].items() if c['operator']=='relocation']
        used=lambda R:{n for e in R['run']['epochs'] for n,x in e['throughput'].items() if x>1e-8}
        ua,ub=used(A),used(B)
        same=all(abs(ea['throughput'].get(n,0)-eb['throughput'].get(n,0))<1e-7 for ea,eb in zip(A['run']['epochs'],B['run']['epochs']) for n in set(ea['throughput'])|set(eb['throughput']))
        out.write(json.dumps({'seed':seed,'vol':vol,'audit':B['audit']['passed'],'stateful':B['stateful_audit']['passed'],
            'obj_v3':A['audit']['all_in_objective'],'obj_fix':B['audit']['all_in_objective'],'identical':same,
            'relocated_known':len(relo),'relocated_used_v3':len([n for n in relo if n in ua]),'relocated_used_fix':len([n for n in relo if n in ub]),
            'unused_parent_v3':any(n in ua and any(q in A['lineage'] and q not in ua for q in c['parents']) for n,c in A['lineage'].items()),
            'unused_parent_fix':any(n in ub and any(q in B['lineage'] and q not in ub for q in c['parents']) for n,c in B['lineage'].items())})+'\n');out.flush()
