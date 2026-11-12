# Chain SLO A100 reproduction bundle — v0.1.0

本仓库保存 **v47pro3 冻结调度代码、A/vLLM-FCFS 对照实现、Oracle/消融代码、固定工作量、窗口截断与审计工具**，以及面向 **8×A100 80GB SXM/NVLink** 的六类实验计划。

**这是首版源码与 CPU 准备包，尚不是在 A100 上一键跑完 134 组的发行版。** 原 A40 launcher 含机器路径和旧设备绑定，归档在 `legacy/`；不要直接执行。Sarathi adapter 尚未实现，30B/70B、多卡、各方法的 A100 截断与清理仍需资格验证。本版不会用占位执行器产生“实验结果”，也不携带旧 PASS 作为新服务器的通过凭据。

## 从新服务器开始

```bash
git clone https://github.com/Xiaotangyuan-xty/chain-slo-a100-repro.git
cd chain-slo-a100-repro
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python tools/check_release.py
chainbench plan --out runs/plan
chainbench prepare --case s1-001 --out runs/s1-001
chainbench doctor
```

以上命令仅使用 CPU。`doctor` 在缺少 A100 验证时**有意返回退出码 2**。`prepare` 生成固定输入，不启动推理。`chainbench` 必须从完整 Git checkout 安装；算法、数据、后端源码通过 checkout 相对路径绑定，不支持只复制 Python wheel。

模型与 QRF 大文件另行下载；见 [ASSETS.md](docs/ASSETS.md)。A100 环境、资格流程和当前阻塞项见 [A100_MIGRATION.md](docs/A100_MIGRATION.md) 和 [READINESS.md](docs/READINESS.md)。

## 已冻结的 134 组

| 类别 | 目的与配置 | 组数 | 每组主窗口 |
|---|---|---:|---:|
| 1 到达率/模型 | 200 链；0.2/0.4/0.6/0.8/1 链/s；4 方法；4 模型 | 80 | 1000/500/333.333/250/200 s |
| 2 KV 容量 | 200 链，0.2/s，8B；4 方法；各自默认 B 的 0.2/0.4/0.6/0.8/1.0 | 20 | 1000 s |
| 3 机制消融 | 200 链，0.2/s，8B；v47pro3/Oracle/no_credit/no_kv/no_event/chain_EDF | 6 | 1000 s |
| 4 到达形状 | 200 链，0.2/s，8B；Poisson/Azure 映射；4 方法 | 8 | 1000 s |
| 5 持续在线 | 720 链，0.2/s；8B/14B；4 方法；连续一个引擎 | 8 | 3600 s |
| 6 SLO 敏感性 | 200 链，0.2/s，8B；4 方法；完成 SLO ×0.5/1/1.5 | 12 | 1000 s |

4 方法为 **v47pro3、A、vllm-FCFS、sarathi-serve**。模型为 **Llama-3.1-8B-Instruct、Qwen2.5-14B-Instruct、Qwen3-30B-A3B-Instruct-2507、Llama-3.1-70B-Instruct**，BF16。保留名义重复配置供各实验独立执行，不自动去重。

所有窗口合计 **30.9259 个逻辑实例小时**，不含加载、预热、清理和资格验证。它不是 8 卡整机墙钟预测；TP 和并行资源分配会改变 GPU 小时与墙钟时间。

## 实验语义

- 使用旧 DR200 的 **200 链、1197 次调用、504,695 个目标输出 token**；保留原 prompt、输出长度、阶段依赖和 SLO。它是已知工作流回放，不声称 held-out。
- 原 `received_slo[2]` 为每阶段完成预算，整链期限为该值乘阶段数，原范围 **80–480 秒**。第 6 类仅缩放完成预算；TTFT/TBT 槽保持原值。
- Poisson 采用给定 N(H)=N 的条件 Poisson，即 N 个 Uniform(0,H) 顺序统计量；不是无条件到达流。各方法共享同一到达数组；Azure 使用冻结映射数组。
- 冷加载和预热在窗口外。主窗口使用同机 monotonic 时钟 `[0,H)`；即便所有工作提前完成也观察到 H。
- **H 到达后停止新增 executor 调用，冻结证据，取消未完成请求，清理自有进程，再进入下一组；不排空。** 边界前已经提交的 GPU kernel 可能返回，但 H 后观察到的输出/完成不计入窗口。
- 完整回放/排空指标为 N/A。分别报告已知超时与右删失，保留 SLO 达成率上下界。
- 历史 settled credit 为满足整链完成期限后一次结算的 `Σ(input_tokens + 8×output_tokens)`，除以 H 得到 credit/s。它不是纯 output token/s。原始吞吐、完成链数和该加权 goodput 必须分别列出。
- 默认 KV 按各后端自动分配并记录实际容量。第 2 类按每个方法/后端对应的默认 B 独立标定，再显式设置 `max(1,floor(f×B))`。不声称跨后端相同 GiB。
- 固定调度算法；每个模型/后端/TP 只冻结一份部署与标定档案。硬件提速后不自动改变 SLO、到达率或工作量。

## 仓库内容

- `vendor/v47pro3/`：发布 commit `f8c5d84048536861a017adaa53648b6b753487e6` 对应的 28 文件候选树，独立 SHA 检查。
- `vendor/jitserve/`：实际 A40 使用的 JITServe + 自定义 vLLM 0.6.1 后端源码，含 Qwen3 MoE backport；不是最新上游 vLLM。
- `vendor/runtime_overlay/`、`vendor/common_runtime/`：运行时覆盖与共享预测/观测适配器。
- `legacy/`：修复清理竞态后的 Stage87、Stage88 小时窗口、Stage69 消融和修复顺序/ABI 后的 Stage82 Oracle 源码。旧设备校验文件名仅作来源证据，不代表本版授权任何设备操作。
- `data/`：两个模型的冻结 DR200 压缩 JSON，以及 Azure 映射数组。
- `chainbench/`：相对路径配置、134 组矩阵、固定输入生成、KV 规则、资格缺项检查。
- `configs/`、`profiles/`：官方资产清单和无机器绑定的部署档案模板。
- `provenance/`：候选校验与源码 SHA 清单；`tests/`：CPU 合同和真实截断 wrapper 测试。

公开前仅有两项兼容/脱敏修改，详见 `provenance/PUBLICATION_ADJUSTMENTS.json`：上游示例的硬编码 HF 凭据改为本地环境变量、历史日志字符串的 Python 引号兼容修正。冻结候选算法保持原字节。

完整上传清单见 [UPLOAD_INVENTORY.md](docs/UPLOAD_INVENTORY.md)。代码许可与数据来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
