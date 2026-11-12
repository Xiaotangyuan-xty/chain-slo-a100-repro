"""Insertion hook for FUTURE isolated serving wrappers. Does not start an engine.

Call after the existing Astar/v47 installer and before engine construction.
Do not install in or modify the ongoing Stage33 Qwen process.
"""
from pathlib import Path
import hashlib,json
from native_tot_adapter import install_server_annotations,install_astar_tot_budget,install_v47_metadata_bridge


def install(server, output_dir, protocol):
    methods = ['A','Astar','v47']
    method = protocol['candidate_version']
    if method not in methods:
        raise ValueError('Explicit qualified method required')
    enabled = protocol.get('contains_native_tot', False)
    receipt = {'schema':'stage34-runtime-adapter/v1','method':method,'enabled':enabled,
               'engine_started_by_installer':False,'scoring_formula_changed':False,
               'ToT_route':'native implicit, requests_per_stage absent',
               'adapter_module_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if enabled:
        from jitserve.request_analyzer.graph_context import GraphMatchContext
        receipt['shared_annotations']=install_server_annotations(server)
        if method=='Astar':
            if not protocol.get('baseline_budget_adapter_sha256'):
                raise ValueError('Install and bind existing DR Astar adapter first')
            receipt['Astar_ToT_budget']=install_astar_tot_budget(GraphMatchContext)
        elif method=='v47':
            from native_chain import ChainCompletionPolicy
            if ChainCompletionPolicy.version!='v47_token_reward_deadline_drain_cached_forecast':
                raise ValueError('Frozen v47 source/runtime required')
            receipt['v47_known_structure_bridge']=install_v47_metadata_bridge(ChainCompletionPolicy)
    out=Path(output_dir)
    if not out.is_dir():
        raise ValueError('Existing isolated attempt directory required; installer creates no experiment')
    (out/'STAGE34_NATIVE_TOT_ADAPTER.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt
