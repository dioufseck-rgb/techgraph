import json
from dataclasses import replace
from pathlib import Path
import pytest
from techgraph import dynamic
from techgraph.discovery import (CONTRACT, canonical, pilot_specs, ancestry, classify_exception,
    prepare, input_record, execute, epoch_records, read_trace)
from techgraph.experiment_contract import validate_discovery_contract
from techgraph.interface_examples import lifecycle_world
from techgraph.dynamic import run_policy, path_objective
from techgraph.vsr import run_vsr
from run_discovery_pilot import run_one, rebuild_tables


def test_discovery_contract_does_not_invent_a_hypothesis():
    manifest=CONTRACT.manifest()
    assert manifest['mode']=='discovery' and 'hypothesis' not in manifest and 'falsifier' not in manifest
    with pytest.raises(ValueError):validate_discovery_contract(replace(CONTRACT,validation_plan=''))


def test_pilot_identity_and_ancestry_keep_matched_cases_together():
    specs=pilot_specs()
    assert len(specs)==len({canonical(s) for s in specs})==96
    assert {f:sum(s['family']==f for s in specs) for f in ('production','interface','vsr')}=={'production':48,'interface':32,'vsr':16}
    assert ancestry(specs[0])==ancestry({**specs[0],'horizon':6,'construction_lead':1})
    assert ancestry({'family':'vsr','seed':0})==ancestry(specs[0])


@pytest.mark.parametrize('metadata,expected',[({'status':'Infeasible'},'certified_infeasible'),({'status':'Not Solved'},'unresolved')])
def test_proven_infeasibility_is_not_confused_with_timeout(metadata,expected):
    assert classify_exception(RuntimeError('Optimization not proved optimal: '+repr(metadata)))[0]==expected
    assert classify_exception(RuntimeError('infeasible maybe'))[0]=='error'


@pytest.mark.parametrize('horizon',[1,5])
def test_recording_is_observational_and_callback_cannot_mutate_solver_records(horizon):
    sc,tr,prm,hist=lifecycle_world(1,None,.1,False)
    baseline=run_policy(sc,tr,prm,hist,horizon=horizon)
    seen=[]
    def callback(e):
        seen.append(e['epoch']);e['operating']['builds'].clear()
    recorded=run_policy(sc,tr,prm,hist,horizon=horizon,epoch_callback=callback)
    assert seen==list(range(5))
    assert path_objective(tr,recorded)==pytest.approx(path_objective(tr,baseline))
    assert [e['builds'] for e in recorded['epochs']]==[e['builds'] for e in baseline['epochs']]


def test_partial_history_survives_a_later_solver_failure(monkeypatch):
    sc,tr,prm,hist=lifecycle_world(1,None,.1,False)
    original=dynamic.solve_window;seen=[];count=0
    def fail_second(*args,**kwargs):
        nonlocal count
        count+=1
        if count==2:raise RuntimeError("Optimization not proved optimal: {'status': 'Not Solved'}")
        return original(*args,**kwargs)
    monkeypatch.setattr(dynamic,'solve_window',fail_second)
    with pytest.raises(RuntimeError):run_policy(sc,tr,prm,hist,horizon=1,epoch_callback=seen.append)
    assert len(seen)==1 and seen[0]['epoch']==0 and seen[0]['operating']['operating_states']


def test_input_serialization_preserves_typed_interface_keys_and_missingness():
    spec=next(s for s in pilot_specs() if s['family']=='interface')
    ctx=prepare(spec,10);record=input_record(ctx,spec)
    assert '__typed_mapping__' in record['scenario']['interface_system']['versions']
    assert record['capabilities']['physical_stocks']=='disabled' and record['stocks'] is None
    assert json.loads(canonical(record))==record


@pytest.mark.parametrize('horizon',[1,5])
def test_case_resume_and_tables_preserve_trace_identity(tmp_path,horizon):
    spec=next(s for s in pilot_specs() if s['family']=='interface')
    spec={**spec,'horizon':horizon}
    first=run_one(spec,str(tmp_path),'test_model',10)
    trace=tmp_path/first['trace'];original=trace.read_bytes()
    second=run_one(spec,str(tmp_path),'test_model',10)
    assert second['resumed'] and trace.read_bytes()==original
    coverage=rebuild_tables(tmp_path)
    assert coverage['recorded_histories']==1 and coverage['completed_epoch_records']==5
    record=read_trace(trace)
    journal=[json.loads(line) for line in (tmp_path/first['journal']).read_text().splitlines()]
    assert journal[-1]['kind']=='attempt_finished'
    assert [e['epoch'] for e in journal if e['kind']=='completed_epoch']==list(range(5))
    assert record['result']['audit']['passed']
    assert record['result']['epochs'][0]['stocks'] is None
    assert record['counterfactual_status']=='not_measured'
    assert all('quantity_unit' in v for v in record['result']['epochs'][0]['service_by_requirement'].values())


def test_vsr_callback_preserves_search_and_recorded_knowledge():
    spec=next(s for s in pilot_specs() if s['family']=='vsr')
    ctx=prepare(spec,10);ctx['cfg']=replace(ctx['cfg'],proposals_per_epoch=1)
    seen=[];result=execute(ctx,spec,seen.append)
    assert result['status']=='complete' and result['audit']['search']['passed']
    assert len(seen)==4 and all('search_event' in e for e in seen)
    known=[set(e['known_designs']) for e in result['epochs']]
    assert all(a<=b for a,b in zip(known,known[1:]))


def test_breadth_tranche_counts_and_holdout_ancestries():
    from techgraph.discovery import discovery_specs
    specs=discovery_specs()
    assert len(specs)==len({canonical(s) for s in specs})==1024
    assert {f:sum(s['family']==f for s in specs) for f in ('production','interface','vsr')}=={'production':768,'interface':128,'vsr':128}
    holdout={ancestry(s) for s in specs if s.get('seed') in (8,9)}
    discovery={ancestry(s) for s in specs if s.get('seed') not in (8,9)}
    assert not holdout & discovery


def test_breadth_parameters_reach_physics_and_policy():
    from techgraph.discovery import discovery_specs
    spec=next(s for s in discovery_specs() if s['family']=='production' and s['n_sites']==5 and not s['quality_shock'] and s['residual_capacity']==2.)
    ctx=prepare(spec,10)
    assert len(ctx['sc'].locations)==5 and ctx['metadata']['requirement_shock_epoch'] is None
    assert ctx['metadata']['residual_capacity']==2.
    spec=next(s for s in discovery_specs() if s['family']=='vsr' and s['evaluation_horizon']==3)
    assert prepare(spec,10)['cfg'].evaluation_horizon==3
