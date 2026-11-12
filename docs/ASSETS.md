# 还需要下载或准备什么

| 资产 | 仓库内 | 新服务器需要 |
|---|---|---|
| v47pro3/A/FCFS/Oracle/消融源码 | 有，来源与 SHA 固定 | 从源码构建，移植 host adapter |
| DR200 prompt/目标/结构/SLO | 有，gzip JSON | 无须再次生成或采集；保留来源许可 |
| Azure 映射到达数组 | 有，200 项冻结数组 | 直接回放；原始 Azure trace 不在本仓库，不支持从原 trace 再生 |
| 整链 CHAIN_MODEL、图训练数据 | 有，保持原冻结内容 | 不自动重训 |
| 8B 官方 QRF + vectorizer | 无，约1.35GB | pinned HF revision 下载，SHA 校验 |
| 14B 使用的官方7B QRF + vectorizer | 无，约1.40GB | 同上；明确跨模型尺寸迁移 |
| 8B/14B/30B/70B BF16 权重 | 无，约16.1/29.5/61.1/141.1GB（十进制） | 官方仓库下载完整 shards；Llama 需批准访问 |
| CUDA/PyTorch/custom vLLM 编译产物 | 无 | A100 sm80 重新构建并冻结依赖 |
| Sarathi | 无集成实现 | 固定版本、独立环境、adapter 与资格检查 |
| A100 profile/容量/截止资格 | 无 | 一次性标定后冻结 |

QRF 官方仓库 `En-2863/jitserve-qrf-length-predictor`，revision `1e587124a9671f54f4c659f97bccbbe890b3d8af`。四个文件的大小和 SHA256 位于 `configs/assets.json`。本版不上传 pickle、模型权重、缓存或本地认证信息。

```bash
python -m pip install huggingface_hub
python tools/fetch_assets.py qrf --out downloads/predictors
```

模型 revision 必须先从官方仓库选定一个 **40 位 immutable commit**。为了避免替用户选择未知模型 revision，本版模型 revision 标为未固定；8B/14B 已提供历史 snapshot 的逐文件 SHA，下载器会拒绝把不同 snapshot 当成相同实验输入。

```bash
python tools/fetch_assets.py model --model llama8 --revision YOUR_40_HEX_COMMIT --out models/llama8
```

下载器不读取/输出 token 值；HF 登录和 gated 访问按官方工具在服务器自行配置。资产 receipt 只证明下载和内容哈希，不证明模型成功加载，也不自动授权 GPU 实验。
