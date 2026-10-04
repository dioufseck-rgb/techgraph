"""Build the accepted cohort without overwriting any original attempt.

Resolved trace links are reproducible views, excluded from the archive to avoid
duplicating the raw records. Run this script after extracting the checkpoint.
"""
from pathlib import Path
import json,hashlib,os,shutil
from run_demand_sweep import write_json
from techgraph.discovery import ident

def main():
    base=Path('results/demand_v3');out=Path('results/demand_v3_resolved')
    repair_dirs=[Path('results/demand_v3_precision'),Path('results/demand_v3_precision_323')]
    bm=json.loads((base/'manifest.json').read_text())
    rms=[json.loads((d/'manifest.json').read_text()) for d in repair_dirs]
    bc=json.loads((base/'coverage.json').read_text())
    assert bc['histories']==500
    for d in repair_dirs:assert json.loads((d/'coverage.json').read_text())['statuses']=={'complete':20}
    originals={r['run_id']:r for r in json.loads((base/'runs.json').read_text())}
    repairs=[r for d in repair_dirs for r in json.loads((d/'runs.json').read_text())]
    repair_source={r['run_id']:d/'traces'/(r['run_id']+'.json.gz') for d in repair_dirs for r in json.loads((d/'runs.json').read_text())}
    repaired={r['spec']['repair_of']:r for r in repairs}
    assert len(repaired)==40 and {r['spec']['seed'] for r in repairs}=={314,323}
    out.mkdir(exist_ok=True);(out/'traces').mkdir(exist_ok=True);(out/'analysis/cache').mkdir(parents=True,exist_ok=True)
    selected=[];sources={};hashes={};excluded=[]
    for spec in bm['specs']:
        original_id=ident(spec,'demand_');old=originals[original_id]
        if original_id in repaired:
            r=repaired[original_id];src=repair_source[r['run_id']];excluded.append(old)
        else:r=old;src=base/'traces'/(r['run_id']+'.json.gz')
        assert r['status']=='complete',(r['run_id'],r['status'])
        dest=out/'traces'/src.name
        if not dest.exists():os.link(src,dest)
        digest=hashlib.sha256(src.read_bytes()).hexdigest()
        assert hashlib.sha256(dest.read_bytes()).hexdigest()==digest
        hashes[r['run_id']]=digest;selected.append(r);sources[r['run_id']]=str(src)
        cache=base/'analysis/cache'/src.name
        if cache.exists() and not (out/'analysis/cache'/src.name).exists():shutil.copy2(cache,out/'analysis/cache'/src.name)
    accepted_names={r['run_id']+'.json.gz' for r in selected}
    for p in (out/'traces').glob('*.json.gz'):
        if p.name not in accepted_names:p.unlink()  # Remove only a reproducible view link.
    assert len(selected)==500 and len(list((out/'traces').glob('*.json.gz')))==500
    manifest={**bm,'campaign':'demand-v3-resolved','output_identity':out.name,'specs':[r['spec'] for r in selected],
              'precision_repair':rms,'accepted_trace_sources':sources,
              'exclusions':{'records':excluded,'reason':'all initial attempts for worlds314 and323 replaced as matched groups'},
              'source_hashes':{**bm['source_hashes'],'run_demand_precision_repair.py':rms[0]['source_hash'],
                               'run_demand_precision_world323.py':rms[1]['source_hash'],
                               'resolve_demand_campaign.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    write_json(out/'manifest.json',manifest);write_json(out/'runs.json',selected);write_json(out/'trace_hashes.json',hashes)
    write_json(out/'coverage.json',{'histories':500,'statuses':{'complete':500},'completed_epochs':sum(r['completed_epochs'] for r in selected),
                                  'ancestries':24,'excluded_original_attempts':40,'original_audit_failures':sum(r['status']!='complete' for r in excluded)})
    print('Accepted cohort: 500 histories; matched precision repairs replace all 40 cases of worlds314 and323.')

if __name__=='__main__':main()
