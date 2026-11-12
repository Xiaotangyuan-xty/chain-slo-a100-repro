import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from model_contract import prepare,resources,profile,resource_checks
class Contracts(unittest.TestCase):
 def fixture(self,d,key='qwen14'):
  from model_contract import ALLOWED_MODELS
  m={'model_key':key,'model_path':ALLOWED_MODELS[key],'qrf_model':'/official/model.pkl','qrf_vectorizer':'/official/vectorizer.pkl',
     'resources':{'num_gpu_blocks_override':512,'swap_space_gib':1.},'expected_resource_caps':{'gpu_blocks':512,'cpu_blocks':341 if key=='qwen14'else 512,'model_path':ALLOWED_MODELS[key]}}
  (d/'MODEL_PROFILE.json').write_text(json.dumps(m));p={'model_key':key,'model_path':m['model_path'],'expected_resource_caps':m['expected_resource_caps'],
    'model_profile_sha256':hashlib.sha256((d/'MODEL_PROFILE.json').read_bytes()).hexdigest()}
  (d/'PROTOCOL.json').write_text(json.dumps(p));return m,p
 def test_preparation_uses_user_requested_generation_model(self):
  for key in ['qwen14','llama8']:
   with tempfile.TemporaryDirectory()as td:
    d=Path(td);m,p=self.fixture(d,key);(d/'PREPARE.json').write_text(json.dumps({'python':'frozen','model':'old7B'}))
    b=prepare(d,d);self.assertEqual(b['model'],m['model_path']);self.assertEqual(b['qrf_model'],m['qrf_model']);self.assertEqual(b['python'],'frozen')
 def test_changed_profile_is_rejected(self):
  with tempfile.TemporaryDirectory()as td:
   d=Path(td);self.fixture(d);(d/'MODEL_PROFILE.json').write_text('{}')
   with self.assertRaises(AssertionError):profile(d)
 def test_model_key_path_mismatch_is_rejected(self):
  with tempfile.TemporaryDirectory()as td:
   d=Path(td);m,p=self.fixture(d);p['model_key']='llama8';(d/'PROTOCOL.json').write_text(json.dumps(p))
   with self.assertRaises(AssertionError):profile(d)
 def test_model_specific_native_CPU_blocks_are_checked(self):
  with tempfile.TemporaryDirectory()as td:
   d=Path(td);m,p=self.fixture(d);self.assertTrue(all(resource_checks(p,m['expected_resource_caps']).values()))
   wrong={**m['expected_resource_caps'],'cpu_blocks':1170};self.assertFalse(resource_checks(p,wrong)['cpu_blocks'])
 def test_wrong_generation_model_is_rejected_by_gate(self):
  with tempfile.TemporaryDirectory()as td:
   d=Path(td);m,p=self.fixture(d);wrong={**m['expected_resource_caps'],'model_path':'old7B'};self.assertFalse(resource_checks(p,wrong)['model_path'])
 def test_common_resource_defaults_are_preserved(self):
  with tempfile.TemporaryDirectory()as td:
   d=Path(td);self.fixture(d);self.assertEqual(resources({'penalty_factor':100},d),{'penalty_factor':100,'num_gpu_blocks_override':512,'swap_space_gib':1.})
if __name__=='__main__':unittest.main()
