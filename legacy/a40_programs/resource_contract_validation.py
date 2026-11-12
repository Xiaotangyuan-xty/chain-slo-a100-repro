"""CPU-only resource proof from actual capacity and immutable launch registry."""
import math

def values(command,flag):
 out=[]
 for i,arg in enumerate(command):
  if arg==flag:out.append(command[i+1]if i+1<len(command)else None)
  elif arg.startswith(flag+'='):out.append(arg.split('=',1)[1])
 return out

def numeric_one(command,flag):
 v=values(command,flag)
 try:return float(v[0])if len(v)==1 else None
 except (TypeError,ValueError):return None

def verify(protocol,common,registry):
 resources=protocol['resources'];actual=common['resources'];servers=[r for r in registry if r['name']=='server'];server=servers[0]if len(servers)==1 else{};command=server.get('command',[]);override=resources.get('num_gpu_blocks_override');flags=values(command,'--num-gpu-blocks-override');util=numeric_one(command,'--gpu-memory-utilization');blocks=actual.get('gpu_blocks');dtype=values(command,'--dtype');model=values(command,'--model')
 checks={'resource_proof_single_registered_server':len(servers)==1,'resource_proof_GPU_visibility':server.get('cuda_visible_devices')==resources['gpu_uuid'],'resource_proof_model_arg_and_engine':model==[protocol['model_path']]and actual.get('model_path')==protocol['model_path'],'resource_proof_BF16_arg_and_engine':dtype==['bfloat16']and str(actual.get('dtype','')).endswith('bfloat16'),'resource_proof_memory_util_arg':util is not None and math.isclose(util,resources['gpu_memory_utilization'],rel_tol=0,abs_tol=1e-12),'resource_proof_actual_positive_GPU_blocks':isinstance(blocks,int)and blocks>0}
 if override is None:
  checks['resource_proof_no_override_arg']=not flags
  checks['resource_proof_default_policy']=resources['gpu_memory_utilization']==.85 and 'gpu_blocks'not in protocol['expected_resource_caps']
 else:
  checks['resource_proof_fixed_capacity']=blocks==override==protocol['expected_resource_caps']['gpu_blocks']
  checks['resource_proof_fixed_override_arg']=flags==[str(override)]
 # Older observers omit these configuration fields. Never substitute protocol
 # values for missing observations; use the independently recorded launch argv.
 if 'num_gpu_blocks_override'in actual:checks['resource_proof_optional_override_observation']=actual['num_gpu_blocks_override']==override
 if 'gpu_memory_utilization'in actual:checks['resource_proof_optional_util_observation']=actual['gpu_memory_utilization']==resources['gpu_memory_utilization']
 return {'gate':'PASS'if all(checks.values())else'FAIL','checks':checks,'mode':'native_default_auto_KV'if override is None else'fixed_physical_KV','observed_gpu_blocks':blocks,'launch_memory_utilization':util,'launch_override_values':flags,'original_observer_has_override_field':'num_gpu_blocks_override'in actual,'registered_server_pid':server.get('pid'),'registered_server_start_ticks':server.get('proc_start_ticks'),'evidence':'Actual engine capacity and server launch registry; original observer/config fields not fabricated.'}
