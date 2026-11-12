# v0.1.0 — frozen sources and CPU reproduction plans

Initial public release for 8×A100 80GB SXM/NVLink migration preparation.

- Preserves the exact 28-file v47pro3 candidate, actual A40 JITServe/custom-vLLM source, runtime overlays, fixed-window cleanup fixes, and corrected Oracle/ablation source.
- Defines all 134 nominal cases across six suites, with backend-specific default/relative KV rules and fixed window cutoff without drain.
- Includes the frozen 504,695-target-token DR200 workload, Azure mapped arrivals, pinned official QRF download manifests, CPU preparation/qualification tools and CI.
- Separates weighted settled credit from output token throughput and deadline misses from right censoring.

Validation: CPU contract tests, real cutoff wrapper boundary test, source hash verification, syntax/publication scan and clean-clone preparation. No GPU experiments were started for this release.

Known limitations: **no A100 validation; no portable full-suite GPU launcher; no Sarathi integration; Oracle/ablations need cutoff integration; 30B tokenizer/MoE/predictor and 70B TP/predictor need qualification.** Model revisions must be resolved/pinned on the new server. See docs/READINESS.md before running inference.
