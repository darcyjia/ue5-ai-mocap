# 更新记录

版本号：`主.次.修订`。改了阶段产物格式或配置项 → 次版本；修 bug、调阈值 → 修订号。
发版：`git tag -a vX.Y.Z -m "说明" && git push origin vX.Y.Z`

## v0.3.0 — 2026-10-01

阶段顺序：generate → solve → clean → **hands → impact → face** → preview → fbx → ue → qc。首个生产素材 ring01（55 秒擂台戏，四段尾帧接力拼接）全流程跑通。

**新阶段**
- **hands 手型**：MediaPipe 识别四指弯曲 → 拳 / 半握 / 掌 / 放松，平滑后套预设到 SMPL-X 手指关节；识别不到按前后手型和出拳动作兜底；`input/hands.json` 手动覆盖。测试素材识别率 64–93%。FBX 导出全部 55 个关节（原来只有身体 22 个）
- **impact 受力反馈**：检测打击（拳/肘/脚/膝高速到达对方部位并骤停），给被打方叠加临界阻尼冲击（头/胸/腹/格挡手臂）；躯干高频按视频校准放大；`input/impacts.json` 手动增删调。fight_test_03 冲拳段头部晃动 0.58 → 1.15 px（视频 1.40）
- **face 表情**：由动作驱动，不还原视频里的脸：眼神盯对手、随机眨眼、受击表情、性格底色（`[[person]] face_style`：calm / fierce），写进 MetaHuman 面部控制板

**UE**
- 序列加「原声」音轨（视频声音 48kHz，第 0 帧、不变速）
- 面部控制板轨道直接写通道关键帧（只在编辑器里加，命令行没有 Slate 会崩）
- 重定向时导出 MetaHuman 网格（Body / Face / 衣服）供 Blender 预演，按蓝图名缓存
- 插件新增：手型修正、查看手型识别、受力修正、查看受力检测、导入运镜（Blender 预演）

**运镜预演（Blender → UE）**
- `previz_mh.py` 预演场景（工程里的 MetaHuman + 擂台 + 原机位参考）；`previz_cams.py` 按镜头表 `shots.json` 自动建相机（跟拍 / 过肩 / 环绕 / 打击震动 / 开场定格 / 重复剪辑）并按剪辑表渲染；`assemble_edit.py` 拼原声；`export_cams_ue.py` 导出 UE 坐标
- 插件建成片序列 `LS_<素材>_edit`：镜头轨道，每个镜头一个子序列（相机 + 镜头切换 + 表演副本），原声按剪辑表逐段对齐

**修复**
- 素材第二次进 UE 时一直用第一次导入的旧动作（UE 对已存在的骨骼网格只重导网格）：源资产按 FBX 指纹导入新目录
- 脚部锁定加运动学备用着地判据（GVHMR 着地概率失准时兜底）：ring01 两人着地脚深度速度 25.0/16.7 → 4.1/3.8 cm/s；基准 ywp 绿衣 5.86 → 0.001，回归基准已更新
- 视频下载先写 `.part` 并校验大小、失败重试，不再留下残缺的 video.mp4

**配置**：新增 `[hands]`、`[impact]`、`[face]`，`[clean] kin_*`，`[qc] min_hand_detect`，`[[person]] face_style`。手部识别用独立环境 `.venv-tools`（不进 git）。

## v0.2.0 — 2026-09-28

- **UE 编辑器插件**（纯 Python）：主菜单「AI 动捕」，新建动捕 / 构图板候选 / 换角色重做 / 任务状态 / 质检报告；表单用属性面板对话框（文件选择、MetaHuman 蓝图选择器）；解算在后台跑，编辑器不卡；完成后在编辑器里重定向并打开序列
- **完整 MetaHuman**：每段素材一个专用关卡，放入 MetaHuman 蓝图并绑定 Body 组件（原来是无头身体网格）。命令行模式同样生效
- `[[person]]` 改用 `mh_bp`（蓝图）；单段素材可用 `input/persons.json`、`input/generate.json` 覆盖角色和生成参数
- 花积分必须显式确认：命令行要 `--allow-spend`，插件弹窗显示预估和余额
- 即梦：读不到登录状态时重试；提交时未登录、图片上传失败属于不扣费失败，自动重试最多 2 次；提示 Claude 桌面应用（MSIX）会隔离凭据，需在普通终端 `dreamina login`
- 插件：切换关卡前的未保存检查改用 `get_dirty_map_packages`；后台完成后的步骤出错改为弹窗
- 新命令：`install-ue-plugin`、`quote`、`uejob`、`mark`；`run --no-preview`
- `ue_pipeline.py` 重构为 `run_job()`，命令行入口 `ue_commandlet.py`

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
