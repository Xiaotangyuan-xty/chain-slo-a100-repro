"""Shared-observer mode checks; no model or CUDA initialization."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
from abc_observation import Observation


class SelectionObservation(unittest.TestCase):
    def observe(self,native_foreground,has_selection=True):
        class Executor:
            async def execute_model_async(self,*args,**kwargs):return 'done'
        Executor.__module__='vllm.executor.cpu_fixture'
        class Policy:
            version='fixture';schedule_interval=50;draining=False
        class Scheduler:
            policy=Policy();search_strategy='sliding_window';max_swaps_per_iter=3
            _foreground_native=native_foreground;last_recorded_selected=frozenset()
            block_manager=S(get_num_free_gpu_blocks=lambda:512,get_num_free_cpu_blocks=lambda:1170)
        if not has_selection:
            del Scheduler.last_recorded_selected
            del Policy.draining
        executor=Executor()
        llm=S(model_executor=executor,scheduler=[Scheduler()],
              cache_config=S(num_gpu_blocks=512,num_cpu_blocks=1170,block_size=16,swap_space_bytes=1073741824.,enable_prefix_caching=False),
              scheduler_config=S(max_num_seqs=32,max_num_batched_tokens=2048,chunked_prefill_enabled=True),
              model_config=S(max_model_len=8192,dtype='torch.bfloat16',enforce_eager=True))
        with tempfile.TemporaryDirectory()as directory:
            obs=Observation(Path(directory),'C',Path(directory),{'physical_gpu_index':0})
            try:
                with patch.dict('os.environ',{'STUDY_C_VERSION':'fixture'}),patch('abc_observation.inspect.getfile',return_value=__file__):
                    obs.engine_ready(S(engine=llm))
                asyncio.run(executor.execute_model_async(S(seq_group_metadata_list=[S(request_id='other')])) )
                return obs.stats['outside_selected_executed_groups']
            finally:obs.finalize()

    def test_foreground_native_execution_is_not_misclassified_as_chain_selection(self):
        self.assertEqual(self.observe(True),0)

    def test_native_GMAX_has_no_selected_set_contract(self):
        self.assertEqual(self.observe(False,False),0)

    def test_actual_selection_violation_is_still_detected(self):
        self.assertEqual(self.observe(False),1)


if __name__=='__main__':unittest.main()
