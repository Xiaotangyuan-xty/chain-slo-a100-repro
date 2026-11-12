# Unreleased — deployment and audit corrections

- Explicitly install vLLM build requirements before `--no-build-isolation`, and install the constrained QRF runtime requirements separately.
- Reset the tokenizer and text-count cache per case in both batch auditors; reject executor starts at or after H without a 10ms tolerance, including in the primary gates.
- Exclude receipt self-hashes, bind reused model directories to one revision, and reject missing/extra payload files against the pinned official repository listing.
- Preserve the original auxiliary provenance record and reconcile current hashes to the authoritative 28-file suite.
- Extend integrity coverage to the complete published checkout, including tools/configs/tests; detect changed, missing and unlisted files. The SHA manifest excludes itself and is bound by Git; it is not a signature.
- Add CPU regression fixtures; no live runner, historical PASS receipt, frozen algorithm file or GPU experiment changed.

# v0.1.0 — frozen sources and CPU reproduction plans

Initial public release for 8×A100 80GB SXM/NVLink migration preparation.

- Preserves the exact 28-file v47pro3 candidate, actual A40 JITServe/custom-vLLM source, runtime overlays, fixed-window cleanup fixes, and corrected Oracle/ablation source.
- Defines all 134 nominal cases across six suites, with backend-specific default/relative KV rules and fixed window cutoff without drain.
- Includes the frozen 504,695-target-token DR200 workload, Azure mapped arrivals, pinned official QRF download manifests, CPU preparation/qualification tools and CI.
- Separates weighted settled credit from output token throughput and deadline misses from right censoring.

Validation: CPU contract tests, real cutoff wrapper boundary test, source hash verification, syntax/publication scan and clean-clone preparation. No GPU experiments were started for this release.

Known limitations: **no A100 validation; no portable full-suite GPU launcher; no Sarathi integration; Oracle/ablations need cutoff integration; 30B tokenizer/MoE/predictor and 70B TP/predictor need qualification.** Model revisions must be resolved/pinned on the new server. See docs/READINESS.md before running inference.
