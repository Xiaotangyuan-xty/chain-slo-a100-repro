from pathlib import Path
import ast,hashlib,json
D=Path(__file__).resolve().parent
R='/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1'
name='stage87_v47pro3_A_FCFS_llama8_qwen14_DR200_autoKV_rates13_cutoff_cleanupfix_gpu0_20261111_v6'
names=['bundle_runtime.py','execution_base.py','controller.py','window_client.py','window_server.py','cutoff_observation.py','window_metrics.py','window_gate.py','resource_sampler.py','cutoff_statistics.py','scheduler_cpu.py','saturation_checks.py','native_graph_observation.py','native_dispatch.py','install_suite_runtime.py','abc_observation.py','rate_contract.py','resource_contract_validation.py','window_summary.py','workflow.py','test_window_cpu.py','test_saturation_cpu.py','test_contract_cpu.py','test_cleanup_recovery.py','handoff.py']
sources={n:(D/n).read_text()for n in names}
for n,s in sources.items():ast.parse(s,filename=n)
test=Path('/Users/xuetianyou/Documents/Codex/2026-11-08/gpu-node1-stage47-gpu0-stage45-gpu1-2/outputs/GPU0_GPU1_Oracle接口恢复与新增验收_2026-11-11/证据/test_followup_contracts.py').read_text().replace("model_key='llama8'","model_key=p['model_key']")
instruction='GPU0 run200 fixed chains, v47pro3/A/vLLM-FCFS, 8B/14B, no artificial KV block cap; stop each run exactly at200/rate seconds, cancel and clean without drain, then next case. Preserve GPU1 and paused application automation; noGPU2/GitHub/push/training.'
steering='Replace rates with0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1,1.2,1.4,1.6; 3x2x13=78cases. This supersedes the initial six-rate36-case request before any new GPU launch.'
packet={'study_name':name,'user_instruction':instruction,'rate_instruction':steering,'references':json.loads((D/'references.json').read_text()),'sources':sources,'test_followup_contracts':test,'recovery':{'from_study':'stage87_v47pro3_A_FCFS_llama8_qwen14_DR200_autoKV_rates13_cutoff_gpu0_20261111_v3','user_instruction':'修复sampler自然退出清理竞态后继续GPU0；不得重跑已通过case1。后续每个case在跑完且自有进程/GPU清理后，无论最终验收PASS或FAIL均继续下一项；失败如实保留，不覆盖v3，不操作GPU1。'}}
(D/'prepare_study_packet.json').write_text(json.dumps(packet,ensure_ascii=False))
control={'study':R+'/'+name,'files':{n:(D/n).read_text()for n in ['watch_and_audit.py','recompute_window_readonly.py']}}
(D/'qualify_control_packet.json').write_text(json.dumps(control,ensure_ascii=False))
(D/'LOCAL_SOURCE_SHA256.json').write_text(json.dumps({n:hashlib.sha256(s.encode()).hexdigest()for n,s in sources.items()},indent=2)+'\n')
print(json.dumps({'study':R+'/'+name,'rates':13,'cases':78,'sources':len(sources),'GPU_started':False}))
