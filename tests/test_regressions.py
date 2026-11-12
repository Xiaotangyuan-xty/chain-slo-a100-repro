"""CPU regression fixtures for mixed-model audits and repeated asset downloads."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch

from chainbench.core import ROOT,dump,read,sha,source_check
from chainbench.integrity import MANIFEST,manifest_snapshot,verify_manifest

STAGES=('stage87_cutoff_cleanupfix','stage88_hour')

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def jsonl(path,rows):
    path.write_text(''.join(json.dumps(row)+'\n'for row in rows))

def audit_case(parent,model,length,executor_start=199.999):
    case=parent/model;attempt=case/'attempts/one';attempt.mkdir(parents=True)
    prompt='same text across tokenizers';prompt_hash=hashlib.sha256(prompt.encode()).hexdigest()
    slo=[2.,.1,20.];member=dict(request_id=0,prompt=prompt,prompt_sha256=prompt_hash,target_output_tokens=length)
    jobs=[dict(collection_id=i,received_slo=slo,stages=[[member]])for i in range(200)]
    roots=[dict(collection_id=i,received_slo=slo,success=False,stages=[],
        client_chain_start_monotonic=110+i*.001,client_chain_end_monotonic=None)for i in range(200)]
    roots[0].update(success=True,client_chain_end_monotonic=111.,stages=[dict(stage_id=0,success=True,
        requests=[dict(request_id=0,success=True,input_prompt_sha256=prompt_hash,
                       client_request_start_monotonic=110.,client_request_end_monotonic=111.,generated_text=prompt)])])
    dump(case/'WORKLOAD.json',dict(main=jobs))
    dump(case/'PROTOCOL.json',dict(model_path=model,cutoff_seconds=100.,root_count=200))
    dump(attempt/'CLIENT_CUTOFF_SNAPSHOT.json',dict(origin_monotonic=100.,cutoff_monotonic=200.,roots=roots))
    credit=9*length
    metrics=dict(fixed_window_settled_credit=credit,fixed_window_credit_per_second=credit/100,
        arrived_roots=200,completed_chains_before_cutoff=1,SLO_attained_chains_before_cutoff=1,
        definite_SLO_misses_by_cutoff=199,SLO_outcome_right_censored=0,unfinished_chains_at_cutoff=199,
        actual_output_tokens_observed_in_window=length,schedule_calls_main=1,scheduler_CPU_P50_ms=1.,
        scheduler_CPU_P95_ms=1.,scheduler_CPU_total_seconds=.001,
        equal_window_bins=[dict(settled_credit=credit if i==1 else 0)for i in range(12)])
    dump(case/'receipts/RUN_GATE_one.json',dict(gate='PASS',metrics=metrics))
    token_ids=list(range(length))
    jsonl(attempt/'WINDOW_TOKEN_DELTAS.jsonl',[dict(request_uuid='r0',previous_tokens=0,output_tokens=length,
        new_token_ids=token_ids,phase='main',monotonic=110.5)])
    jsonl(attempt/'EXECUTOR_EVENTS.jsonl',[dict(start_monotonic=executor_start,end_monotonic=200.1,error=None)])
    dump(attempt/'EXECUTOR_OBSERVATION.json',dict(events=1))
    dump(attempt/'WINDOW_SERVER_CUTOFF.json',dict(requests=[dict(request_uuid='r0',
        output_prefix_sha256=hashlib.sha256(json.dumps([token_ids]).encode()).hexdigest())]))
    jsonl(attempt/'SCHEDULER_CPU_EVENTS.jsonl',[dict(start_monotonic=120.,thread_cpu_ns=1_000_000)])
    dump(attempt/'SCHEDULER_CPU_RUNTIME.json',dict(calls=1,failed_calls=0))
    return dict(path=str(case),attempt='one',name=model)

def run_audit(stage,cases):
    loaded=[]
    class Tokenizer:
        def __init__(self,length):self.length=length
        def __call__(self,text,**kwargs):return types.SimpleNamespace(input_ids=list(range(self.length)))
    def from_pretrained(model,**kwargs):
        loaded.append(model);return Tokenizer(1 if model=='llama8'else 3)
    transformers=types.ModuleType('transformers')
    transformers.AutoTokenizer=types.SimpleNamespace(from_pretrained=from_pretrained)
    torch=types.ModuleType('torch');torch.cuda=types.SimpleNamespace(is_initialized=lambda:False)
    output=io.StringIO()
    with patch.dict(sys.modules,dict(transformers=transformers,torch=torch)),\
         patch.object(sys,'stdin',io.StringIO(json.dumps(dict(cases=cases)))),\
         contextlib.redirect_stdout(output):
        runpy.run_path(str(ROOT/'legacy'/stage/'recompute_window_readonly.py'),run_name='__main__')
    return json.loads(output.getvalue()),loaded

class AuditRegressionTests(unittest.TestCase):
    def test_mixed_model_packet_counts_same_text_with_each_models_tokenizer(self):
        with tempfile.TemporaryDirectory()as directory:
            llama=audit_case(Path(directory),'llama8',1)
            qwen=audit_case(Path(directory),'qwen14',3)
            for stage in STAGES:
                with self.subTest(stage=stage):
                    result,loaded=run_audit(stage,[llama,qwen,llama])
                    self.assertEqual(result['gate'],'PASS')
                    self.assertEqual(loaded,['llama8','qwen14','llama8'])
                    self.assertEqual([c['independent_metrics']['fixed_window_settled_credit']for c in result['cases']],[9,27,9])

    def test_independent_audit_accepts_pre_cutoff_start_and_rejects_exact_or_late_start(self):
        with tempfile.TemporaryDirectory()as directory:
            case=audit_case(Path(directory),'llama8',1)
            events=Path(case['path'])/'attempts/one/EXECUTOR_EVENTS.jsonl'
            gate=Path(case['path'])/'receipts/RUN_GATE_one.json';original=gate.read_bytes()
            for stage in STAGES:
                for stamp in (199.999999,200.,200.000001,200.005,200.01):
                    with self.subTest(stage=stage,start=stamp):
                        jsonl(events,[dict(start_monotonic=stamp,end_monotonic=200.1,error=None)])
                        if stamp<200.:
                            self.assertEqual(run_audit(stage,[case])[0]['gate'],'PASS')
                        else:
                            with self.assertRaisesRegex(AssertionError,'Model execution started after fixed cutoff'):
                                run_audit(stage,[case])
                        self.assertEqual(gate.read_bytes(),original)

    def test_primary_gate_checks_executor_start_boundary_directly(self):
        with tempfile.TemporaryDirectory()as directory:
            attempt=Path(directory);dump(attempt/'EXECUTOR_OBSERVATION.json',dict(events=1))
            for stage in STAGES:
                gate=load('gate_'+stage,ROOT/'legacy'/stage/'window_gate.py')
                for stamp in (199.999999,200.,200.000001,200.005,200.01,float('nan')):
                    with self.subTest(stage=stage,start=stamp):
                        jsonl(attempt/'EXECUTOR_EVENTS.jsonl',[dict(start_monotonic=stamp,end_monotonic=200.1,error=None)])
                        checks=gate.executor_trace_checks(attempt,200.)
                        self.assertTrue(checks['executor_trace_complete_and_no_pre_cutoff_failure'])
                        self.assertEqual(checks['executor_starts_strictly_before_cutoff'],stamp<200.)

class DownloadReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tool=load('fetch_assets_test',ROOT/'tools/fetch_assets.py')
        self.payload={'config.json':b'{"model_type":"fixture"}',
            'model.safetensors.index.json':json.dumps(dict(weight_map={'weight':'model-00001.safetensors'})).encode(),
            'model-00001.safetensors':b'CPU fixture bytes, not model weights'}
        self.spec=dict(repository='official/test-model',files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            for name,data in self.payload.items()})
        self.api=types.SimpleNamespace(list_repo_files=Mock(return_value=list(self.payload)))
        def download(repo,*,revision,local_dir,allow_patterns):
            self.assertEqual(set(allow_patterns),set(self.payload))
            for name,data in self.payload.items():(local_dir/name).write_bytes(data)
            metadata=local_dir/'.cache/huggingface';metadata.mkdir(parents=True,exist_ok=True)
            (metadata/'download.metadata').write_text('tool-managed metadata')
        self.download=Mock(side_effect=download)

    def fetch(self,directory,**kwargs):
        return self.tool.download_model('fixture','a'*40,directory,kwargs.get('spec',self.spec),self.api,kwargs.get('download',self.download))

    def test_repeat_download_has_identical_payload_manifest_and_no_receipt_self_entry(self):
        with tempfile.TemporaryDirectory()as directory:
            directory=Path(directory);first=self.fetch(directory);first_bytes=(directory/self.tool.RECEIPT).read_bytes()
            second=self.fetch(directory)
            self.assertEqual(first,second);self.assertEqual(first_bytes,(directory/self.tool.RECEIPT).read_bytes())
            self.assertEqual(set(first['files']),set(self.payload))
            self.assertNotIn(self.tool.RECEIPT,first['files'])

    def test_unexpected_existing_file_is_rejected_without_downloading_or_overwriting_receipt(self):
        with tempfile.TemporaryDirectory()as directory:
            directory=Path(directory);self.fetch(directory);original=(directory/self.tool.RECEIPT).read_bytes()
            self.download.reset_mock();(directory/'old-model-shard.safetensors').write_bytes(b'stale')
            with self.assertRaisesRegex(RuntimeError,'Unexpected existing payload files'):self.fetch(directory)
            self.download.assert_not_called();self.assertEqual((directory/self.tool.RECEIPT).read_bytes(),original)

    def test_missing_or_extra_downloaded_files_are_rejected_even_without_historical_hashes(self):
        for alteration in ('missing','extra'):
            with self.subTest(alteration=alteration),tempfile.TemporaryDirectory()as directory:
                directory=Path(directory)
                def damaged_download(*args,**kwargs):
                    self.download(*args,**kwargs)
                    if alteration=='missing':(directory/'config.json').unlink()
                    else:(directory/'unexpected.txt').write_text('stale')
                with self.assertRaisesRegex(RuntimeError,'Snapshot file set mismatch'):
                    self.fetch(directory,spec={'repository':self.spec['repository']},download=damaged_download)
                self.assertFalse((directory/self.tool.RECEIPT).exists())

    def test_foreign_model_revision_receipt_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory()as directory:
            directory=Path(directory);dump(directory/self.tool.RECEIPT,dict(model='other',repository='other/repo',revision='b'*40))
            with self.assertRaisesRegex(RuntimeError,'another model/revision'):self.fetch(directory)
            self.api.list_repo_files.assert_not_called();self.download.assert_not_called()

    def test_unavailable_historical_hashes_are_not_reported_as_a_match(self):
        with tempfile.TemporaryDirectory()as directory:
            result=self.fetch(Path(directory),spec={'repository':self.spec['repository']})
            self.assertIsNone(result['historical_snapshot_matches'])

class IntegrityRegressionTests(unittest.TestCase):
    CRITICAL=('chainbench/core.py','chainbench/cli.py','chainbench/integrity.py',
              'configs/experiments.json','configs/assets.json','tools/fetch_assets.py',
              'tools/check_release.py','tools/update_source_manifest.py',
              'tests/test_contracts.py','tests/test_regressions.py')

    def test_real_manifest_covers_all_new_tools_and_provenance(self):
        manifest=read(ROOT/MANIFEST)
        for name in self.CRITICAL:self.assertIn(name,manifest['files'])
        self.assertEqual(source_check()['gate'],'PASS')

    def test_changes_to_every_critical_tool_are_detected(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory)
            for name in self.CRITICAL:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
            dump(root/MANIFEST,manifest_snapshot(root))
            self.assertEqual(verify_manifest(root)['gate'],'PASS')
            for name in self.CRITICAL:
                with self.subTest(path=name):
                    path=root/name;original=path.read_bytes();path.write_bytes(original+b'\n')
                    result=verify_manifest(root);self.assertEqual(result['gate'],'FAIL');self.assertIn(name,result['changed'])
                    path.write_bytes(original)

    def test_missing_and_unlisted_source_files_cannot_pass(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);dump(root/'configs/test.json',dict(original=True));dump(root/MANIFEST,manifest_snapshot(root))
            (root/'configs/test.json').unlink();dump(root/'configs/new.json',dict(new=True))
            result=verify_manifest(root);self.assertEqual(result['gate'],'FAIL')
            self.assertEqual(result['missing'],['configs/test.json']);self.assertEqual(result['unexpected'],['configs/new.json'])

    def test_origin_is_current_and_original_auxiliary_record_is_preserved(self):
        origin=read(ROOT/'provenance/published_SOURCE_ORIGIN.json')
        history=origin['historical_record'];self.assertEqual(sha(ROOT/history['path']),history['sha256'])
        self.assertEqual(len(history['stale_runtime_entries']),11)
        authority=read(ROOT/origin['authority'])['candidate_hashes']
        for name,value in origin['new_candidate_runtime_files'].items():
            self.assertEqual(value,authority[name]);self.assertEqual(value,sha(ROOT/'vendor/v47pro3'/name))

if __name__=='__main__':unittest.main()
