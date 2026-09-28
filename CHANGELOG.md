# 更新记录

版本号：`主.次.修订`。改了阶段产物格式或配置项 → 次版本；修 bug、调阈值 → 修订号。
发版：`git tag -a vX.Y.Z -m "说明" && git push origin vX.Y.Z`

## v0.2.0 — 2026-09-28

- **UE 编辑器插件**（纯 Python）：主菜单「AI 动捕」，新建动捕 / 构图板候选 / 换角色重做 / 任务状态 / 质检报告；表单用属性面板对话框（文件选择、MetaHuman 蓝图选择器）；解算在后台跑，编辑器不卡；完成后在编辑器里重定向并打开序列
- **完整 MetaHuman**：每段素材一个专用关卡，放入 MetaHuman 蓝图并绑定 Body 组件（原来是无头身体网格）。命令行模式同样生效
- `[[person]]` 改用 `mh_bp`（蓝图）；单段素材可用 `input/persons.json`、`input/generate.json` 覆盖角色和生成参数
- 花积分必须显式确认：命令行要 `--allow-spend`，插件弹窗显示预估和余额
- 新命令：`install-ue-plugin`、`quote`、`uejob`、`mark`；`run --no-preview`
- `ue_pipeline.py` 重构为 `run_job()`，命令行入口 `ue_commandlet.py`
- **手型**：新阶段 hands（clean 与 preview 之间）。MediaPipe 识别四指弯曲 → 拳 / 半握 / 掌，平滑后套预设到 SMPL-X 手指关节；识别不到按前后手型和出拳动作兜底；`input/hands.json` 手动覆盖；质检报告加手型时间线和识别抽样。测试素材识别率 75–93%
- 插件新增「手型修正…」「查看手型识别…」
- preview / fbx 改读 `hands/`；FBX 导出全部 55 个关节（原来只有身体 22 个）
- 修复：素材第二次进 UE 时一直用第一次导入的旧动作（UE 对已存在的骨骼网格走 atomic reimport，只重导网格不重导动画）。源资产改为按 FBX 指纹放进 `<素材>/src/p<k>_<指纹>`，用完删掉旧目录
- 新增 `[hands]` 配置段、`[qc] min_hand_detect`；手部识别用独立环境 `.venv-tools`（不进 git）

## v0.1.0 — 2026-09-28

第一个可用版本，把手工搭建的流程固定成命令行工具。

- 七个阶段 generate → solve → clean → preview → fbx → ue → qc，参数指纹缓存，`--from/--only/--force`
- 质检报告 `qc/report.html`：追踪、脚滑、重投影、重定向误差，超阈值标红
- 回归测试 `python -m aimocap test`（只重跑 clean + qc）；基准素材 `ywp_1080p`
- 两人可分配不同 MetaHuman（`[[person]]` 按画面从左到右）
- 统一水平缩放：UE 只缩放骨盆垂直运动，水平用统一系数匹配目标角色腿长（强制 0.8 验证：间距比 1.017 → 0.821）
- 合并被切碎的着地片段：基准素材蓝衣着地脚深度速度 26.8 → ~0 cm/s
- 重定向只对齐手臂/手指（修复驼背约 30°、低头约 55°）

已知限制：无手指；720p 积分单价为估算。
