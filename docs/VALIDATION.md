# v0.1.0 验证记录

日期：2026-11-12。验收范围：公开源码、CPU 规划和输入准备，不包含任何 GPU 性能验证。

- 9 个新 CPU 合同测试通过：134 组计数/窗口、各后端 B 的整数取整、共享到达数组、仅完成 SLO 缩放、720 链唯一 ID/连续输入、未验证 profile 拒绝、删失分类、修复后 Oracle 可见性，以及真实 executor 截断 wrapper。
- 36 个原 service/forecast/event 单元测试通过，直接使用冻结候选模块；不把旧 PASS receipt 当作测试结果。
- 28 个候选文件分别与发布 commit `f8c5d84048536861a017adaa53648b6b753487e6` 和当前使用源码对照，一致。
- 1762 个归档源码/输入/配置文件逐项 SHA256 校验通过。凭据模式扫描、压缩数据扫描、Python 语法检查通过；无权重、QRF pickle、.so 或超20MB文件。
- 隔离 CPU 虚拟环境 editable 安装通过；安装后的 CLI 可生成134组计划和200/720链输入；`doctor` 按设计返回未就绪，不会启动GPU。
- 从首次提交重新进行干净 Git clone，重新 editable 安装，45 项测试、源码/发布扫描及134组计划、200链/720链输入生成全部通过。
- 原归档源码的既有空白格式保持原样，未为了 lint 重写冻结文件；新增打包代码单独做空白检查。

本地验证使用 macOS CPU Python3.9.6（直接源码检查）及 Python3.13.11（隔离安装/合同检查）；发行支持版本为 Python≥3.10，GPU部署建议 Python3.10。GitHub Actions 配置另外检查 Python3.10/3.11，以实际 Actions 结果为准。

未验证：A100 构建/模型加载、GPU模型输出、实际默认KV、TP/NCCL、多卡并发、Sarathi、整套134组GPU运行。详细缺项见 READINESS.md。
