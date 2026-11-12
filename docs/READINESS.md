# v0.1.0 实现与可复现性状态

| 项目 | 首版已有 | 尚需完成 |
|---|---|---|
| v47pro3 | 28 文件冻结树、模型档案、原 A40 实际运行源码 | A100 launcher 移除旧绝对路径/设备绑定；重新验证 |
| A | 原生 JITServe 调度 + 相同 QRF 适配器 | A100 环境/默认 KV/截断资格验证 |
| vllm-FCFS | 实际使用的自定义 vLLM 原生 FCFS dispatch | 记录 fork；A100 自动容量与截断验证 |
| Sarathi | 134 组配置中的明确方法项；原生后端容量规则 | **代码未集成**；固定上游版本、独立环境、链 API、token 观测、executor 截断、清理与 raw audit |
| Oracle | 成功修复后的 length-only Oracle + 顺序/ABI 工具 | 在窗口 harness 下重新整合；不沿用旧完整排空 gate |
| 4 项消融 | Stage69 各自修改后的候选源码和 SUITE_SPEC | 冻结 delta 并整合窗口 harness，验证只有指定机制改变 |
| 8B/14B | 原 prompt/target、模型元数据、QRF 官方 pinned revision/SHA | 模型与 QRF 下载；A100 环境/缓存容量标定 |
| 30B MoE | Instruct-2507 已选定；后端 Qwen3Moe 实现 | BF16 完整模型/原生 tokenizer；显存/架构兼容、MoE 路由/输出与预测器迁移验证 |
| 70B | 模型与 TP4 提案 | gated 权重、TP/NCCL/NVLink、TP KV 字节口径、预测器迁移验证 |
| 134 组输入 | 可重复生成矩阵与冻结工作量；CPU 检查 | 所有模型/方法的真实 GPU 执行与最终审计 |

**任何方法当前都没有 A100 PASS。** 旧 A40 的完整排空成绩、窗口成绩和新服务器资格证据必须分别存储。本版不发布历史性能结论，避免同名配置在不同窗口或 GPU 上被误合并。

`chainbench doctor` 的退出码 2 表示上述缺项仍在，不能据此宣称整套实验已就绪。首版以源码可取得、配置可枚举、固定输入可生成、CPU 合同可验证为发布验收口径。

下一版应先实现 8B 的 v47pro3/A/FCFS portable launcher，单独验证：加载→预热→实际 auto KV→主窗口→executor barrier→只清理自有进程→独立复算。通过后再扩充 Sarathi、Oracle/消融和跨模型 TP；不能用“把旧路径全局替换”作为迁移完成证据。
