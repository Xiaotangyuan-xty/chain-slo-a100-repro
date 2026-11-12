# 部署与审计修正（2026-11-12）

本次核对的七项建议均成立，修改限于公开仓库副本。没有修改远端 runner、队列、GPU 实验、监控进程或历史 PASS；冻结 v47pro3 的28个文件未改。

1. **构建依赖**：A100 命令先显式安装 vendored `requirements-build.txt`，然后才以 `--no-build-isolation` 构建，补齐 CMake、ninja、setuptools-scm、wheel 等声明依赖。
2. **QRF 依赖**：新增 `environment/requirements-qrf.txt`，显式安装 numpy/scikit-learn/quantile-forest/scipy/joblib/threadpoolctl，并应用原关键版本约束；增加 pip check 与 CPU import 检查。没有把 constraints 误当作安装列表，也没有宣称真实 QRF 已加载。
3. **跨模型独立复算**：Stage87/88 的 tokenizer 和文本计数 cache 改为每项创建。混合 Llama8→Qwen14→Llama8 packet 可按各自 tokenizer 独立结算，不共享文本计数。独立审计仍不导入主 gate 的指标算法。
4. **下载收据与残留文件**：收据不包含自身；复用目录时校验模型/repository/revision 绑定，并从 pinned 官方文件列表检查下载前多余文件、下载后缺失/多余文件。HF 管理的 metadata 不算 payload。没有历史 SHA 时不报告历史匹配为 true。
5. **严格截止审计**：独立复算与主 gate 均拒绝 `executor.start_monotonic >= H`，无10ms容差；非有限启动时间也不能通过。截止前启动、截止后正常返回的调用仍允许。客户端/服务端停止响应的原有容差不被当成 executor 启动容差。合成边界数据验证 H、H+1µs、H+5ms、H+10ms；这不是历史运行越界的证据，不追溯撤销已有 PASS。
6. **辅助溯源**：原始 `SOURCE_ORIGIN` 完整保存在 `provenance/history/SOURCE_ORIGIN_as_published_f8c5d84.json`，并记录原始 SHA。当前 `published_SOURCE_ORIGIN.json` 的20个 runtime 项对齐权威 `a40_SUITE_SPEC.json`，标明原记录11项陈旧，检查器也验证两者一致。
7. **完整性覆盖**：`SOURCE_SHA256.json` 覆盖完整发布 checkout，含 chainbench、配置、下载/检查工具、测试、文档、CI与provenance；漏列的新文件、删除和内容变化均使检查失败。唯一自身哈希例外是 manifest 文件本身，其内容由 Git commit/tag 绑定。生成与验证分离，`check_release` 不会自动刷新哈希。

维护者更新源码后须审查差异，再显式运行：

```bash
python tools/update_source_manifest.py
python -m unittest discover -s tests -v
PYTHONPATH=vendor/v47pro3/programs python -m unittest discover -s legacy/a40_programs -p test_service_forecast.py -v
python tools/check_release.py
git diff -- provenance/SOURCE_SHA256.json
```

SHA 清单用于相对于可信版本的变更检测，不是签名；若源码与清单被同时改写，必须依赖外部可信的 Git 提交身份。A100 编译、真实 QRF 反序列化和 GPU 性能仍需在部署机器验证。

本地结果：21项合同/回归测试（含12项新增）与36项原service/forecast/event测试全部通过，共57项；发布自检覆盖1797个文件的内容SHA及清单文件本身的扫描，28个冻结候选保持一致。回归测试使用合成轨迹与模拟Hub下载，不联网下载权重，不导入真实GPU后端。GitHub Actions继续验证Python3.10/3.11，以对应提交的实际CI结果为准。
