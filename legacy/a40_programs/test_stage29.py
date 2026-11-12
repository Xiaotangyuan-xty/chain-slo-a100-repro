from types import SimpleNamespace as S
import math,unittest
from baseline_budget import cumulative_ratio
from study_math import arrivals,choose,normal_blocks,ports
class Stage29(unittest.TestCase):
 def ctx(self,times=None):return S(collection_deepresearch_unfinished_dict={1:S(convert_to_unfinished_graph=lambda *a:None)},_encode_prompt_len=len,dynamic_clustering=S(find_best_match=lambda _:S(times=times)if times is not None else None))
 def test_first_and_last_stage(self):
  self.assertEqual(cumulative_ratio(self.ctx(),4,[1]*4,'p',1,0),.25)
  self.assertEqual(cumulative_ratio(self.ctx(),4,[1]*4,'p',1,3),1)
 def test_equal_depth_history_and_uniform_floor(self):
  self.assertEqual(cumulative_ratio(self.ctx([100,1,1,1]),4,[1]*4,'p',1,0),100/103)
  self.assertEqual(cumulative_ratio(self.ctx([1,100,1,1]),4,[1]*4,'p',1,0),.25)
 def test_bad_depth_or_time_uses_actual_declared_depth(self):
  for times in [[1]*6,[1,-1,1,1],[0]*4,[float('nan')]*4]:self.assertEqual(cumulative_ratio(self.ctx(times),4,[1]*4,'p',1,0),.25)
 def test_common_arrival_rate_preserves_shape(self):
  a=arrivals([1,2,4],.2);b=arrivals([1,2,4],.4)
  self.assertEqual(3/a[-1],.2);self.assertEqual(a,[2*x for x in b])
 def test_selects_lowest_rate_near_Astar_peak(self):
  rows=[{'rate':r,'goodput':g,'gate':'PASS'}for r,g in [(.1,90),(.2,96),(.4,100),(.8,75)]]
  self.assertEqual(choose(rows)[0]['rate'],.2)
 def test_invalid_or_zero_calibration_never_launches_formal(self):
  with self.assertRaises(ValueError):choose([{'rate':1,'goodput':0,'gate':'PASS'}])
  with self.assertRaises(AssertionError):choose([{'rate':1,'goodput':100,'gate':'FAIL'}])
 def test_case_ports_are_unique_and_valid(self):
  values=[ports(i)for i in range(40)];self.assertEqual(len({x[0]for x in values}),40);self.assertEqual(len({x[1]for x in values}),40);self.assertTrue(all(0<a<65536 and 0<b<65536 for a,b in values))
 def test_normal_KV_has_headroom_and_rejects_old_tiny_pool(self):
  n=normal_blocks(12000);self.assertGreater(n,512);self.assertLessEqual(n,10800);self.assertEqual(n%64,0)
  with self.assertRaises(AssertionError):normal_blocks(512)
if __name__=='__main__':unittest.main()
