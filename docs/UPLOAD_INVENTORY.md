# 首版上传清单

| 路径 | 内容 | 发布处理 |
|---|---|---|
| `vendor/v47pro3` | 原发布 28 文件候选树、CHAIN_MODEL | 字节冻结，单独对照 commit/SHA |
| `vendor/jitserve` | 当前实际 JITServe/custom vLLM 后端、Qwen3 MoE backport、许可 | 只源码；去除 .git、.so、缓存和日志 |
| `vendor/runtime_overlay` | 13 个运行时覆盖模块 | 冻结来源，部署时需要明确 import 优先级 |
| `vendor/common_runtime` | 共享预测、原生链和观测、length-only Oracle | 保留公共实现；Oracle 正确修复版另见 legacy/oracle_order2 |
| `legacy/stage87_cutoff_cleanupfix` | 正确窗口停止、清理竞态修复、gate/独立统计源码 | 机器绑定历史 harness，禁止直接在新主机执行 |
| `legacy/stage88_hour` | 小时工作量与持续在线窗口源码 | 同上；采用 prepare_hour12，非继承的旧 prepare_study |
| `legacy/ablations` | no_credit/no_KV/no_event/chain_EDF 候选差异 | 每种保留独立 SUITE_SPEC；未宣称新窗口验证 |
| `legacy/oracle_order2`、`oracle_recovery_tools` | Oracle 真值可见性、顺序与 add_seq_group ABI 修复 | 不用失败的旧 adapter 代替；需要新窗口整合 |
| `legacy/a40_programs` | 当前运行源码上下文与原始统计/预测工具 | 归档，非新机器执行入口；含历史未选方法上下文，不加入134组 |
| `data` | DR200 两种 tokenizer 元数据、冻结 Azure offset | gzip 原 JSON；不重写 prompt/目标 |
| `chainbench` | CPU 矩阵、准备、相对路径、KV 档与资格检查 | 可安装，完整 checkout 为运行前提 |
| `configs/assets.json` | 官方模型 ID、QRF revision、逐文件 SHA/大小 | 不含大文件 |
| `environment`、`profiles` | 版本约束、A100 部署模板 | 未验证字段留空，不伪造 PASS |
| `tests`、`.github/workflows` | CPU 合同、真实截止 wrapper、CI | 不启动 GPU |

不上传：权重/QRF pickle、虚拟环境、编译产物、密钥/token、SSH配置、GPU进程快照、完整历史结果/日志、旧 PASS receipts、本地交接 ZIP。现有 A40 runner、队列、watcher 与自动化设置没有改动。

仓库中出现的旧主机路径位于历史来源代码与数据元信息，用于追溯，不能作为新机器配置。新 CPU 工具没有 `/mnt/sda1`、用户名或固定 GPU 号依赖。
