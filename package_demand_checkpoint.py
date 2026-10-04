"""Snapshot immutable published traces with an entry-by-entry hash manifest."""
from pathlib import Path
import argparse,hashlib,json,zipfile,datetime

def main():
    p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[2]
    data=root/'source/techgraph/results/demand_v3'
    traces=sorted((data/'traces').glob('*.json.gz'))
    planned=json.loads((data/'manifest.json').read_text())
    if not a.partial:
        coverage=json.loads((root/'source/techgraph/results/demand_v3_resolved/coverage.json').read_text())
        assert len(traces)==len(planned['specs'])==coverage['histories']==500
        assert coverage['statuses']=={'complete':500}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for f in sorted(root.rglob('*')):
        if not f.is_file():continue
        r=f.relative_to(root)
        if any(x in r.parts for x in ('__pycache__','.pytest_cache','cache')):continue
        if 'demand_v3_resolved' in r.parts and 'traces' in r.parts:continue
        if f.suffix in ('.tmp','.pyc','.zip'):continue
        if a.partial and ('analysis' in r.parts or 'synthesis' in r.parts):continue
        if a.partial and f.suffix=='.log':continue
        if f.parent==data/'traces' and f not in traces:continue
        if a.partial and f.name in ('runs.json','trace_hashes.json','coverage.json'):continue
        files.append(f)
    manifest={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':'partial checkpoint; campaign running' if a.partial else 'complete, analyzed and verified',
        'planned_histories':500,'published_main_traces_in_this_snapshot':len(traces),
        'pilot_histories':4,'pilots_excluded_from_findings':True,
        'resolved_trace_view':'Rebuild hardlinks with source/techgraph/resolve_demand_campaign.py; original and precision raw records are preserved separately',
        'entries':{}}
    if not a.partial:
        original_coverage=json.loads((data/'coverage.json').read_text())
        precision_records=sum(len(list((root/'source/techgraph/results'/d/'traces').glob('*.json.gz')))
                              for d in ('demand_v3_precision','demand_v3_precision_323'))
        assert original_coverage['statuses']=={'complete':498,'error':2}
        assert precision_records==40
        manifest.update({'accepted_coverage':coverage,'original_attempt_statuses':original_coverage['statuses'],
                         'precision_reruns':precision_records,'diagnostic_precision_pilots':1,
                         'accepted_original_histories':460,'accepted_precision_histories':40,
                         'raw_attempts_total':545,
                         'exclusions':'40 originals replaced together for worlds 314 and 323; 4 initial pilots and 1 precision diagnostic excluded'})
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for f in files:
            raw=f.read_bytes();name=str(Path(root.name)/f.relative_to(root))
            manifest['entries'][name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            z.writestr(name,raw,compress_type=zipfile.ZIP_STORED if f.suffix in ('.gz','.png') else zipfile.ZIP_DEFLATED)
        z.writestr(root.name+'/CHECKPOINT_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    # Entry verification detects a packaging/readback problem independently of
    # the runner's earlier publication checks.
    with zipfile.ZipFile(out) as z:
        for name,v in manifest['entries'].items():
            raw=z.read(name);assert len(raw)==v['bytes'] and hashlib.sha256(raw).hexdigest()==v['sha256'],name
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_suffix('.sha256').write_text(digest+'  '+out.name+'\n')
    print(json.dumps({'path':str(out),'bytes':out.stat().st_size,'sha256':digest,
                      'published_main_traces':len(traces),'entries':len(manifest['entries']),'partial':a.partial}))

if __name__=='__main__':main()
