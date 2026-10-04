from dataclasses import asdict
from techgraph.catalog import Design
from techgraph.flows import Port
from techgraph.variation import Candidate
from stateful_replay import FrozenProposalReplay
from run_stateful_campaign import execute


def toy():
    d=Design('G0','process',10,input_ports=(Port('F0','L0'),),output_ports=(Port('F1','L0'),),conserve_mass=True,activity_unit='tonne/h')
    c=Candidate(d,'generic',('A',),'generic_mutation',0,0,4,{'generation':1})
    d2=Design('G1','process',9,input_ports=(Port('F0','L0'),),output_ports=(Port('F1','L0'),),conserve_mass=True,activity_unit='tonne/h')
    c2=Candidate(d2,'generic',('G0',),'generic_mutation',1,0,4,{'generation':2})
    return {'inputs':{'scenario':{'designs':{'A':{}}}},'search_config':{'attempt_cost':.01},'result':{'events':[
        {'proposals':[{'candidate':c.manifest(),'status':'feasible'}],'generative_attempts':[{'designs':['G0']}],'proposal_charge':.01},
        {'proposals':[{'candidate':c2.manifest(),'status':'feasible'}],'generative_attempts':[{'designs':['G1']}],'proposal_charge':.01}]}}


def test_operated_parent_filter_retains_knowledge_and_charges_all_attempts():
    source=FrozenProposalReplay(toy());knowledge=frozenset({'A','G0'})
    batch=source.propose(None,None,knowledge,1,{})
    assert batch.candidates==()
    assert batch.charge==.01
    assert knowledge==frozenset({'A','G0'})
    assert source.exclusions[0]['unoperated_generated_parents']==['G0']


def test_previously_operated_parent_remains_eligible():
    source=FrozenProposalReplay(toy())
    batch=source.propose(None,None,frozenset({'A','G0'}),1,{'G0':2.})
    assert [c.design.name for c in batch.candidates]==['G1']
    assert source.exclusions==[]


def test_full_replay_reproduces_unseeded_history():
    from run_stateful_campaign import prepare
    from techgraph.vsr import run_vsr,audit_vsr
    spec={'seed':106,'volatility':.18,'profile':'full','epochs':12,'horizon':4}
    base=execute(spec);assert base['record']['status']=='complete'
    w,_,cfg=prepare(spec)
    r=run_vsr(w.scenario,w.trajectory,w.params,w.history,(),config=cfg,stocks=w.stocks,realizability=w.realizability,
        candidate_context=w.candidate_context,proposal_source=FrozenProposalReplay(base,'all'))
    from techgraph.discovery import canonical
    assert canonical(r['lineage'])==canonical(base['result']['lineage'])
    import pytest
    assert audit_vsr(r)['all_in_objective']==pytest.approx(base['result']['audit']['all_in_objective'],rel=1e-9)
