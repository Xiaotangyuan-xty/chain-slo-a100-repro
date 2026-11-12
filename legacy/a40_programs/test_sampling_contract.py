import unittest
from pure_metrics import expected_engine_sampling


class SamplingContract(unittest.TestCase):
    def test_zero_temperature_uses_native_greedy_normalization(self):
        generation = {'temperature': 0., 'top_p': 1., 'top_k': 1, 'seed': 42}
        self.assertEqual(expected_engine_sampling(generation, 73), {
            'temperature': 0., 'top_p': 1., 'top_k': -1, 'seed': 42,
            'ignore_eos': True, 'max_tokens': 1024, 'n': 1,
            'target_output_length': 73})

    def test_nonzero_temperature_does_not_rewrite_top_k(self):
        generation = {'temperature': .7, 'top_p': .9, 'top_k': 5, 'seed': 42}
        self.assertEqual(expected_engine_sampling(generation, 19)['top_k'], 5)

    def test_already_normalized_greedy_value_is_stable(self):
        generation = {'temperature': 0., 'top_p': 1., 'top_k': -1, 'seed': 42}
        self.assertEqual(expected_engine_sampling(generation, 19)['top_k'], -1)


if __name__ == '__main__':
    unittest.main()
