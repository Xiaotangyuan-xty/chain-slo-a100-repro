from pathlib import Path
import ast,hashlib,json
D=Path(__file__).resolve().parent
R='/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1'
name='stage88_v47pro3_A_FCFS_llama8_qwen14_hour3600_r0p1_r0p2_autoKV_gpu1_20261111_v3'
names=['bundle_runtime.py','execution_base.py','controller.py','window_client.py','window_server.py','cutoff_observation.py','window_metrics.py','window_gate.py','resource_sampler.py','cutoff_statistics.py','scheduler_cpu.py','saturation_checks.py','native_graph_observation.py','native_dispatch.py','install_suite_runtime.py','abc_observation.py','rate_contract.py','resource_contract_validation.py','window_summary.py','workflow.py','test_window_cpu.py','test_saturation_cpu.py','test_contract_cpu.py','test_cleanup_recovery.py']
sources={n:(D/n).read_text()for n in names}
for n,s in sources.items():ast.parse(s,filename=n)
ast.parse((D/'prepare_hour12.py').read_text(),filename='prepare_hour12.py')
test=Path('/Users/xuetianyou/Documents/Codex/2026-11-08/gpu-node1-stage47-gpu0-stage45-gpu1-2/outputs/GPU0_GPU1_Oracle接口恢复与新增验收_2026-11-11/证据/test_followup_contracts.py').read_text().replace("model_key='llama8'","model_key=p['model_key']")
instruction='GPU1: run v47pro3/A/vLLM-FCFS on Llama8/Qwen14, fixed3600s continuous arrival at0.1/0.2 chains/s (360/720 roots), automaticKV without block override, stop and clean at one hour without drain. Continue to later cases after any final gate result once terminal cleanup is safe. Preserve GPU0, noGPU2/GitHub/push/training.'
packet={'study_name':name,'user_instruction':instruction,'references':json.loads((D/'references.json').read_text()),'sources':sources,'test_followup_contracts':test}
(D/'prepare_hour12_packet.json').write_text(json.dumps(packet,ensure_ascii=False))
control={'study':R+'/'+name,'files':{n:(D/n).read_text()for n in['watch_and_audit.py','recompute_window_readonly.py']}}
(D/'qualify_hour12_control_packet.json').write_text(json.dumps(control,ensure_ascii=False))
(D/'LOCAL_SOURCE_SHA256.json').write_text(json.dumps({n:hashlib.sha256(s.encode()).hexdigest()for n,s in sources.items()},indent=2)+'\n')
print(json.dumps({'study':R+'/'+name,'cases':12,'hours':12,'sources':len(sources),'GPU_started':False}))
