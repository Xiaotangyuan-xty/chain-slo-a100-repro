# A40 → 8×A100 80GB SXM/NVLink

## 提速会改变什么

固定到达率、工作量和 SLO 后，A100 提速可能降低排队、提高窗口完成比例，让某些低速点接近全满足；也可能让方法间差距缩小。这是同一负载下的结果，应原样报告。不要为了维持原 A40 饱和度偷偷提高负载或缩短 SLO。

主窗口由 N/λ 决定，不随 token/s 缩短。0.2 链/s 的 200 链实验仍观察 1000 秒，一小时实验仍是 3600 秒。A100 对总体墙钟的主要帮助是允许多个互不共享 GPU/KV 的实例并行，以及降低加载/预热/清理开销；不能把 A40 用时直接除以某个 GPU 理论算力倍数。

8B/14B 建议从 TP1 开始；30B-A3B 激活参数约 3B，但全部专家权重仍需驻留，BF16 权重约 61GB（十进制），80GB 上能否容纳权重、工作区与默认 KV 必须实测；70B BF16 权重约 141GB（十进制），TP4 是起点提案。TP 数不与方法混用，TP4 的一次 1000 秒实验消耗约 4000 GPU 秒。不要把 TP4 与 TP1 的运行时间直接叫作等资源对照。

## 只生成一次的部署档案

按模型×后端×TP 固定：模型 HF commit、BF16 dtype、tokenizer/chat formatter、后端源码 SHA、依赖 lock、CUDA/driver/NCCL、GPU 型号/拓扑、max_model_len、batch/seq limits、chunked prefill、prefix caching、eager/CUDA graph、memory utilization 的真实默认值，以及默认 KV blocks、block size、每卡/合计物理字节解释。

同一后端下的方法使用相同构建和基准配置。第 2 类每个方法按其测得 B_m 冻结一次，以后五档仅 override blocks；记录 `B_m,f,floor(fB_m),actual_blocks`。Sarathi 的 block 定义不一定与 vLLM 一致，必须同时记录 tokens 和 bytes。

官方 8B QRF、用于14B的官方7B QRF 是现成资产。30B/70B 的预测器迁移策略尚未确认/验证，不能自动假装存在对应官方 QRF，也不应自动启动预测器或整链模型重训。固定算法并不意味着跨模型的 tokenization、QRF 与服务时间标定可以跳过。

## 构建与资格顺序

1. 使用独立新 checkout、数据/模型根目录和输出目录。旧 A40 路径与旧 GPU UUID 只保留在 `legacy/` 与来源文档，不能用作新机器的授权或验收配置。
2. Linux x86_64 + Python3.10，CUDA12.1 开发工具链；安装 Torch2.5.0+cu121，然后从 vendored 自定义 vLLM 源码重新编译 `TORCH_CUDA_ARCH_LIST=8.0`。**不要复制 A40 的 venv、.so 或官方 vLLM wheel 来替代 fork。** CMake 还会取 CUTLASS v3.5.1 与源码声明的 flash-attention commit；需网络/缓存。
3. 原始后端依赖见 `vendor/jitserve/third_party/vllm/requirements-{build,cuda,common}.txt`。使用 `--no-build-isolation` 前必须先安装 `requirements-build.txt`；QRF 依赖由 `environment/requirements-qrf.txt` 显式安装。`environment/constraints-a40.txt` 只约束版本，不会主动安装包，且**不是完整 transitive lock**。全量新环境仍需构建后 `pip freeze`，连同编译日志冻结。Sarathi 放入独立环境，不覆盖现有 vLLM。
4. 下载官方权重/QRF，校验哈希；新模型验证每个 shard、架构、tokenizer 与 prompt hash。固定目标输出 token 数，不把 8B 的 tokenizer token ID 当成 30B/70B 的真值。
5. 实现 portable host adapters 后，单独资格运行验证真实 executor、调度实际安装、预测结果无 fallback、阶段 barrier、窗口边界和自有进程清理。一次引擎一个独占 GPU 集合；整个小时实验中不可按模板批次重启。
6. 保存原始完整轨迹：到达/请求/阶段/整链时间、token deltas、KV/调度/CPU 采样、预测事件、executor 事件、最终截止快照、cleanup、原始文件 SHA。窗口后清理成功才允许下一组，gate FAIL 原样保留，不自动重试。
7. 独立 CPU 复算窗口结果并严格比较同一输入、同一配置、同一指标口径。窗口外完成不能回填。跨后端按系统整体对照报告实际容量差异。

示意构建命令（**尚未在 A100 构建验证**，不能当作一键部署承诺）：

```bash
python -m pip install torch==2.5.0 torchvision==0.20.0 --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r vendor/jitserve/third_party/vllm/requirements-build.txt -c environment/constraints-a40.txt
python -m pip install -r vendor/jitserve/third_party/vllm/requirements-cuda.txt -c environment/constraints-a40.txt
python -m pip install -r environment/requirements-qrf.txt -c environment/constraints-a40.txt
TORCH_CUDA_ARCH_LIST=8.0 VLLM_TARGET_DEVICE=cuda python -m pip install --no-build-isolation -e vendor/jitserve/third_party/vllm
python -m pip install -e vendor/jitserve
python -m pip check
python -c "import sklearn, quantile_forest, scipy, joblib; print('QRF dependency imports OK')"
```

最后一条只验证依赖可导入；真实 QRF pickle 的反序列化与预测仍需下载并核对官方 SHA 后，在该环境中验证，不能用 import 成功代替模型加载资格。

8 个并发进程的 QRF、CPU 线程与磁盘日志也可能瓶颈；每个实例独立端口、CPU 预算、输出目录和所有权锁。NVLink 是 TP 通讯资源，不能把多实验混跑同一张卡视作“8 倍并发”。
