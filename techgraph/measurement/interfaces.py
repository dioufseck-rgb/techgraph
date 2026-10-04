"""Interface metrics: explicit levels, clocks and declared alternative families."""
from ..interfaces import key


def operating_interfaces(sc, flow, tolerance=1e-7):
    links=[x for x in flow.get('interfaces',{}).get('links',()) if sum(x['rates'])>tolerance]
    adapters={n for n,a in flow.get('activity',{}).items()
              if sc.designs[n].interface_role=='adapter' and sum(a['rates'])>tolerance}
    return {'operating_versions':sorted({tuple(x['interface']) for x in links}),
            'operating_standards':sorted({x['interface'][0] for x in links}),
            'active_port_links':len(links),
            'active_adapters':sorted(adapters),
            'adapter_variable_cost':sum(sc.designs[n].var_cost*sc.hours*sum(flow['activity'][n]['rates']) for n in adapters)}


def interface_history(sc, run, implementations=(), tolerance=1e-7):
    rows=[]; previous=None
    for k,e in enumerate(run['epochs']):
        normal=next(s for s in e['operating_states'] if s['name']=='normal')
        m=operating_interfaces(sc,normal['flow'],tolerance)
        operating={n for n in implementations if normal['throughput'].get(n,0)>tolerance}
        installed={key(p) for n,c in e['capacity'].items() if c>tolerance
                   for p in (*sc.designs[n].input_ports,*sc.designs[n].output_ports) if key(p)}
        migration_tasks=[t for t in e.get('integration',{}).get('completed_tasks',()) if t.startswith('interface_migration:')]
        tasks=run.get('integration_config',{}).get('tasks',{}) if run.get('integration_config') else {}
        rows.append({'epoch':k,**m,'installed_port_versions':sorted(installed),
                     'operating_implementations':sorted(operating),
                     'implementation_turnover':None if previous is None else (1-len(operating&previous)/len(operating|previous) if operating|previous else 0),
                     'migration_actions':migration_tasks,
                     'migration_preparation_cost':sum(tasks[t]['completion_cost'] for t in migration_tasks)})
        previous=operating
    standards=sorted({s for row in rows for s in row['operating_standards']})
    versions=sorted({tuple(v) for row in rows for v in row['operating_versions']})
    return {'clock':'decision epochs; normal operation; installed ports reported separately',
            'epochs':rows,
            'standard_operating_persistence':{s:sum(s in r['operating_standards'] for r in rows)/len(rows) for s in standards},
            'version_operating_epoch_counts':[{'version':v,'epochs':sum(v in r['operating_versions'] for r in rows)} for v in versions]}


def substitute_frontier(records, baseline, epsilons=(0,.01,.02,.05,.1,.25,.5,1,2,5)):
    if baseline<=0: raise ValueError('Relative substitute frontier requires positive baseline')
    valid=[r for r in records if r['status']=='Optimal' and r.get('service_verified')]
    return {'scope':'enumerated full-service configuration families; not exhaustive configurations',
            'functional_alternatives':len(valid),
            'best_substitute_premium':min((r['objective']/baseline-1 for r in valid),default=None),
            'points':[{'epsilon':e,'count':sum(r['objective']<=(1+e)*baseline+1e-7 for r in valid)} for e in epsilons]}
