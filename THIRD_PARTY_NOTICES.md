# Third-party code, data and model assets

- JITServe source retains its Apache-2.0 `vendor/jitserve/LICENSE` and upstream authorship. This bundle does not claim authorship of that project.
- The custom vLLM source retains `vendor/jitserve/third_party/vllm/LICENSE` and individual source notices. Upstream build dependencies retain their respective licenses; CUTLASS/flash-attention are fetched at build time according to the vendored CMake source.
- New packaging/preparation code in this repository is Apache-2.0; top-level LICENSE contains that license. Historical experimental modifications retain the upstream code notices.
- The known DeepResearch workflow inputs originate from the JITServe benchmark used by the existing experiments. `WORKLOAD.source_files` stores the upstream trace/client hashes. They are provided as frozen research inputs, not a newly collected held-out dataset; their contents and third-party text are not relicensed by this repository. Azure timing data is a frozen derived mapping, not the original trace dataset.
- Hugging Face model weights and predictors are **not redistributed**. The downloader retrieves official repositories and records immutable revisions/hashes. Model and dataset access remains subject to their publishers' licenses/terms, including the Llama 3.1 Community License and any gated-repository approval.
- The official QRF asset source is `https://huggingface.co/En-2863/jitserve-qrf-length-predictor` at the revision in `configs/assets.json`. Verify pinned SHA256 before deserializing joblib/pickle assets.

Provenance/source hashes describe the archived contents, not an endorsement by the upstream projects or an A100 validation result.
