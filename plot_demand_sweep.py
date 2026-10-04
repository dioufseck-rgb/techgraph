"""Scientific figures over the complete demand sweep; no simulated graphics."""
from pathlib import Path
from collections import defaultdict
import gzip,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from analyze_demand_sweep import tv

ROOT=Path('results/demand_v3_resolved/analysis')
OUT=Path('../../synthesis').resolve()
OUT.mkdir(parents=True,exist_ok=True)
LABELS={
 'constant':'Constant', 'growth20':'Growth +20%', 'growth40':'Growth +40%',
 'decline20':'Decline −20%', 'decline40':'Decline −40%',
 'cycle16':'Cycle: 16 periods', 'cycle24':'Cycle: 24 periods',
 'irregular0':'Irregular: weak ordering', 'irregular85':'Irregular: persistent ordering',
 'pulse40':'Temporary +40% pulse',
 'geo_ref50':'Moderate concentration: reference', 'geo_ref80':'Strong concentration: reference',
 'geo_far50':'Moderate concentration: distant', 'geo_far80':'Strong concentration: distant',
 'geo_return80':'Geographic move and return',
 'mix_a65':'Service A → 65%', 'mix_a80':'Service A → 80%',
 'mix_b65':'Service B → 65%', 'mix_b80':'Service B → 80%',
 'mix_return80':'Service mix out and back'}
COLORS=['#147D92','#D96B32','#7861A8','#608C39','#BE4767']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                     'axes.spines.right':False,'axes.titleweight':'bold','figure.facecolor':'#FAFAF8',
                     'axes.facecolor':'#FAFAF8','savefig.facecolor':'#FAFAF8','grid.alpha':.18})

def load():
    with gzip.open(ROOT/'histories.jsonl.gz','rt') as f:hs=[json.loads(x) for x in f]
    es=defaultdict(list)
    with gzip.open(ROOT/'epochs.jsonl.gz','rt') as f:
        for x in f:
            e=json.loads(x);es[e['run_id']].append(e)
    for e in es.values():e.sort(key=lambda x:x['epoch'])
    return hs,es,json.loads((ROOT/'summary.json').read_text())

def finish(fig,name):
    fig.savefig(OUT/name,dpi=170,bbox_inches='tight');plt.close(fig)

def inputs(hs):
    seed=min(h['spec']['seed'] for h in hs)
    by={h['spec']['treatment']:h for h in hs if h['spec']['seed']==seed and h['spec']['epochs']==72}
    fig,axs=plt.subplots(2,3,figsize=(15.5,8.3))
    configs=[('Scale',('growth40','decline40'),'scale','Total / baseline'),
             ('Timing',('cycle16','cycle24','pulse40'),'scale','Total / baseline'),
             ('Ordering, same value distribution',('irregular0','irregular85'),'scale','Total / baseline'),
             ('Geographic concentration',('geo_ref50','geo_ref80'),'concentration','Normalized concentration'),
             ('Geographic placement',('geo_ref80','geo_far80','geo_return80'),'separation','Mean separation from reference / max'),
             ('Service composition',('mix_a80','mix_b80','mix_return80'),'mix_a','Share of service A')]
    for ax,(title,ts,coord,ylabel) in zip(axs.flat,configs):
        for color,t in zip(COLORS,ts):
            h=by[t];c=h['world_metadata']['demand_coordinates']
            if coord=='concentration':y=np.asarray(c['alpha'])**2
            elif coord=='separation':
                # Exact demand coordinates are available in raw initial scenarios.
                run=h['run_id'];raw=json.loads(gzip.decompress((ROOT.parent/'traces'/(run+'.json.gz')).read_bytes()))
                sc=raw['inputs']['scenario'];locs=sc['locations'];ref=h['world_metadata']['reference_site']
                dist=np.array([np.linalg.norm(np.array(sc['coords'][l])-np.array(sc['coords'][ref])) for l in locs])
                y=np.asarray(c['spatial'])@(dist/max(dist))
            else:y=c[coord]
            ax.plot(y,color=color,lw=1.8,label=LABELS[t])
        ax.axvspan(0,7,color='#BBBBBB',alpha=.13);ax.axvspan(68,71,color='#BBBBBB',alpha=.13)
        ax.set(title=title,xlabel='Period',ylabel=ylabel,xlim=(0,71));ax.grid(True)
        ax.legend(fontsize=8,loc='best',frameon=False)
    fig.suptitle('What we varied: demand coordinates, held apart',fontsize=20,x=.06,ha='left',y=1.015)
    fig.text(.06,-.015,f'Actual schedules for world {seed}. Geographic placement changes without changing concentration. Shading: shared warmup / excluded endpoint.',fontsize=10)
    fig.tight_layout(pad=2)
    finish(fig,'Techgraph_Demand_Inputs.png')

def atlas(hs):
    main=[h for h in hs if h['spec']['epochs']==72]
    by={(h['spec']['seed'],h['spec']['treatment']):h for h in main}
    seeds=sorted({h['spec']['seed'] for h in main})
    panels=[('Scale',('growth40','decline40'),'constant'),
            ('Cycles and a pulse',('cycle16','cycle24','pulse40'),'constant'),
            ('Ordering at equal demand distribution',('irregular0','irregular85'),'constant'),
            ('Same concentration, different placement',('geo_ref80','geo_far80'),'constant'),
            ('Service mix',('mix_a80','mix_b80'),'constant'),
            ('Move away, then return',('geo_return80','mix_return80'),'mixed')]
    fig,axs=plt.subplots(2,3,figsize=(15.5,9))
    for ax,(title,ts,control) in zip(axs.flat,panels):
        for color,t in zip(COLORS,ts):
            for s in seeds:
                h=by[s,t];b=by[s,('geo_ref80' if t=='geo_return80' else 'constant') if control=='mixed' else control]
                x=h['shape']['reconfiguration_pct'];y=h['shape']['capacity_change_pct']
                bx=b['shape']['reconfiguration_pct'];byy=b['shape']['capacity_change_pct']
                ax.plot([bx,x],[byy,y],color=color,alpha=.17,lw=.7,zorder=1)
                ax.scatter(bx,byy,s=11,color='#888888',alpha=.5,zorder=2)
                ax.scatter(x,y,s=27,color=color,alpha=.85,zorder=3)
            ax.scatter([],[],s=30,color=color,label=LABELS[t])
        ax.axhline(0,color='#888888',lw=.7);ax.set(title=title,xlabel='Periods with a process-set change (%)',ylabel='Net summed process-capacity change (%)',xlim=(-2,102))
        ax.grid(True);ax.legend(fontsize=8,frameon=False)
    fig.suptitle('Demand changes produce different technological histories',fontsize=20,x=.06,ha='left',y=1.015)
    fig.text(.06,-.017,f'{len(seeds)} matched worlds per condition. Gray dots: stationary controls; lines connect the same world, not successive periods.\nNet capacity: periods 60–67 versus 4–7; switching: transitions 8–67. Summed process capacity includes serial stages.',fontsize=10)
    fig.tight_layout(pad=2)
    finish(fig,'Techgraph_Demand_Response_Space.png')

def effects(summary):
    ts=[t for t in LABELS if t!='constant']
    cols=[('reconfiguration_pct','Configuration changes\nΔ percentage points'),
          ('capacity_change_pct','Net process-capacity change\nΔ percentage points'),
          ('fill_pct','Service fulfillment\nΔ percentage points'),
          ('new_major_designs_used','New designs substantially used\nΔ count'),
          ('cross_site_activity_per_delivered','Cross-site process activity\nΔ activity / delivered service')]
    fig,axs=plt.subplots(1,len(cols),figsize=(17,10.7),sharey=True)
    for ax,(m,title) in zip(axs,cols):
        for j,t in enumerate(ts):
            d=summary['effects'][f'{t}__constant']['metrics'][m]
            col=COLORS[0] if t.startswith(('growth','decline')) else COLORS[1] if t.startswith(('cycle','irregular','pulse')) else COLORS[2] if t.startswith('geo') else COLORS[3]
            ax.plot([d['minimum'],d['maximum']],[j,j],color=col,alpha=.25,lw=1.3)
            ax.plot([d['q25'],d['q75']],[j,j],color=col,lw=4,solid_capstyle='round')
            ax.scatter(d['median'],j,color=col,s=25,zorder=3)
        ax.axvline(0,color='#777777',lw=.8);ax.grid(axis='x');ax.set_title(title,fontsize=10,pad=14)
        ax.set_yticks(range(len(ts)),[LABELS[t] for t in ts]);ax.tick_params(axis='y',length=0)
    axs[0].invert_yaxis()
    fig.suptitle('Matched effects relative to constant demand',fontsize=21,x=.025,ha='left',y=.99)
    ns=[summary['effects'][f'{t}__constant']['pairs'] for t in ts]
    coverage=str(min(ns)) if min(ns)==max(ns) else f'{min(ns)}–{max(ns)}'
    fig.text(.025,.025,f'Each row contains {coverage} within-world comparisons. Dot = median; thick line = middle half; thin line = full range.\nThese are descriptive ranges, not confidence intervals. Placement and return contrasts have additional controls in the report.',fontsize=11)
    fig.tight_layout(rect=(0,.07,1,.95),w_pad=2.3)
    finish(fig,'Techgraph_Demand_Matched_Effects.png')

def returns(hs,es):
    by={(h['spec']['seed'],h['spec']['treatment']):h for h in hs if h['spec']['epochs']==72}
    seeds=sorted({s for s,t in by})
    cases=[('geo_return80','geo_ref80',48,'Geography: relocation and return'),
           ('mix_return80','constant',56,'Service mix: out and back'),
           ('cycle16','constant',56,'Demand cycles end'),
           ('pulse40','constant',40,'Temporary demand pulse ends')]
    fig,axs=plt.subplots(2,2,figsize=(13.5,8))
    for ax,(t,b,end,title) in zip(axs.flat,cases):
        curves=[]
        for s in seeds:
            aa=es[by[s,t]['run_id']];bb=es[by[s,b]['run_id']]
            y=[tv(a['functional_weights'],b['functional_weights']) for a,b in zip(aa,bb)]
            curves.append(y);ax.plot(y,color=COLORS[0],alpha=.14,lw=.7)
        curves=np.asarray(curves);ax.plot(np.median(curves,axis=0),color=COLORS[0],lw=2.4,label=f'Median across {len(seeds)} worlds')
        ax.axvline(end,color=COLORS[1],ls='--',lw=1.5,label='Demand matches control again')
        ax.axvspan(60,67,color='#AAAAAA',alpha=.15);ax.set(title=title,xlabel='Period',ylabel='Functional activity-share distance',ylim=(-.025,1.025),xlim=(0,67));ax.grid(True)
        ax.legend(fontsize=8,frameon=False,loc='upper left')
    fig.suptitle('How much operating difference remains after demand returns?',fontsize=20,x=.065,ha='left',y=1.015)
    fig.text(.065,-.02,'Each thin line compares matched histories in one world. Distance 0 = identical functional activity shares; 1 = disjoint.\nGray band: late observation window. Persistence here is finite-time path dependence, not evidence of an attractor.',fontsize=10)
    fig.tight_layout(pad=2)
    finish(fig,'Techgraph_Demand_Returns.png')

def capacity_paths(hs,es):
    by={(h['spec']['seed'],h['spec']['treatment']):h for h in hs if h['spec']['epochs']==72}
    seeds=sorted({s for s,t in by})
    panels=[('Scale: expansion and contraction', [('growth40','constant'),('decline40','constant')]),
            ('Cycles: movement within the history', [('cycle16','constant'),('cycle24','constant')]),
            ('Geography: placement and return', [('geo_far80','geo_ref80'),('geo_return80','geo_ref80')]),
            ('Service mix: redistribution and return', [('mix_a80','constant'),('mix_b80','constant'),('mix_return80','constant')])]
    fig,axs=plt.subplots(2,2,figsize=(13.5,8))
    for ax,(title,cases) in zip(axs.flat,panels):
        for color,(t,c) in zip(COLORS,cases):
            paths=[]
            for seed in seeds:
                a=es[by[seed,t]['run_id']];b=es[by[seed,c]['run_id']]
                cap0=np.mean([e['process_capacity'] for e in b[4:8]])
                paths.append([100*(x['process_capacity']-y['process_capacity'])/max(1e-7,cap0) for x,y in zip(a[:68],b[:68])])
            paths=np.array(paths)
            ax.fill_between(range(68),np.quantile(paths,.25,axis=0),np.quantile(paths,.75,axis=0),color=color,alpha=.13,lw=0)
            ax.plot(np.median(paths,axis=0),color=color,lw=2,label=LABELS[t])
        ax.axhline(0,color='#888888',lw=.7);ax.axvspan(60,67,color='#AAAAAA',alpha=.1)
        ax.set(title=title,xlabel='Period',ylabel='Capacity difference / initial capacity (%)',xlim=(0,67));ax.grid(True)
        ax.legend(fontsize=8,frameon=False,loc='best')
    fig.suptitle('The response has a shape, not just a change count',fontsize=21,x=.065,ha='left',y=1.015)
    fig.text(.065,-.02,f'{len(seeds)} matched worlds. Lines: median capacity difference; bands: middle half. Each difference is measured against its matched control.\nGeography uses stationary reference-site concentration; other panels use constant demand. Capacity sums process stages.',fontsize=10)
    fig.tight_layout(pad=2)
    finish(fig,'Techgraph_Demand_Response_Paths.png')

if __name__=='__main__':
    hs,es,summary=load()
    assert summary['complete']==summary['planned']==500
    inputs(hs);atlas(hs);effects(summary);returns(hs,es);capacity_paths(hs,es)
    print(OUT)
