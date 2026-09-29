# aimocap：AI 视频 → 双人动捕 → MetaHuman

用 Seedance 生成武打视频，GVHMR 解算双人动作，清理脚滑，重定向到 UE 5.8 的 MetaHuman，自动生成关卡序列和质检报告。个人使用。

## 快速开始

```bash
cd G:/claude/video/aimocap

# 已有视频
python -m aimocap new fight_01 --video 某视频.mp4
python -m aimocap run fight_01

# 从提示词生成（花积分：必须加 --allow-spend，且不超过 config 的 max_credits）
python -m aimocap plate fight_01 --prompt 构图板提示词.txt   # 免费出 4 张构图板候选到 input/plates/
python -m aimocap new   fight_01 --prompt 编排.txt --plate input/plates/挑中的那张.jpg
python -m aimocap run   fight_01              # 会先报预估积分并停下
python -m aimocap run   fight_01 --allow-spend

python -m aimocap status fight_01         # 各阶段状态
python -m aimocap run fight_01 --from ue  # 从某一阶段重跑（改了角色、重定向参数时）
python -m aimocap test                    # 回归测试
```

跑 `ue` 阶段前**必须关闭 UE 编辑器**（命令行模式写资产，编辑器开着会冲突；关闭时不要保存本素材的资产）。

## UE 编辑器插件（「AI 动捕」菜单）

安装一次：`python -m aimocap install-ue-plugin`（把 `ue_plugin/AIMocap` 以目录链接装进工程的 Plugins，并在 .uproject 里启用）。重新打开工程后，主菜单栏出现「AI 动捕」：

- **新建动捕…**：填素材名，选已有视频（或编排提示词 + 构图板），选画面左右两人各用哪个 MetaHuman 蓝图 → 后台解算（5–8 分钟，编辑器可以照常用，进度在 Output Log 搜「AI 动捕」）→ 完成后自动在编辑器里重定向，建素材专用关卡和序列，弹出质检摘要
- **用提示词生成时会先弹窗**，显示预估积分和当前余额，点「是」才会提交
- **出构图板候选（免费）…**：即梦文生图出几张候选，完成后打开所在文件夹
- **换角色 / 重做重定向…**：已解算的素材换 MetaHuman，只重做 UE 部分（几十秒）
- **手型修正…**：把某人某只手在某段时间（秒）改成拳 / 半握 / 掌 / 放松，写进 `input/hands.json`，只重做手型、导出和 UE 部分（不重新识别）
- **查看手型识别…**：打开素材的手型时间线图
- **受力修正…**：某个时间点（秒）的受击反应调幅度 / 删掉 / 补一下，写进 `input/impacts.json`，只重做受力、导出和 UE 部分（约 15 秒）
- **查看受力检测…**：打开受力时间线（每一下打在哪、多大）
- **任务状态 / 打开质检报告 / 打开工作目录 / 打开配置文件**

插件是纯 Python（UE 5.8 自带 Python 插件），界面用 UE 的属性面板对话框。重活由系统 Python 跑本工具的命令行，UE 阶段在编辑器里运行（与命令行共用 `scripts/ue/ue_pipeline.py`）。

**声画同步**：动画和视频逐帧对应（Seedance 24fps → GVHMR 每帧一个姿态 → FBX/UE 按 24fps），时长相同，倍数 1.0。序列里自带「原声」音轨（视频的声音，从第 0 帧开始）。Seedance 的帧时间戳是 3:2 交替（挂在 60fps 网格上），按均匀 24fps 播放每帧最多偏 8 毫秒，听不出来。以后要整体变速，动画和声音用同一个倍数。

**每段素材一个专用关卡** `/Game/AIMocap/<素材>/L_<素材>`：两个完整的 MetaHuman 蓝图放在关卡里，序列绑定它们的 Body 组件（头、衣服、头发都在），不会动你正在编辑的关卡。

## 阶段

| 阶段 | 运行环境 | 做什么 | 产物（`aimocap_work/<素材>/`） |
|---|---|---|---|
| generate | Windows / 即梦 CLI | 构图板 + 编排提示词 → Seedance 视频；已有视频则跳过 | `input/video.mp4` |
| solve | WSL2 / GVHMR | 多人追踪（按画面从左到右编号 p0、p1…）→ 每人 GVHMR → 共享坐标系、重力对齐、贴地 | `solve/p*.npz`、`camera.json`、`track.json` |
| clean | Windows | 脚部锁定：每人贴地、着地检测并合并碎片、根部水平校正、腿部 IK | `clean/p*.npz`、`cleanup.json` |
| hands | Windows / `.venv-tools`（MediaPipe） | 识别四指弯曲 → 拳 / 半握 / 掌，平滑后把预设手型套到手指关节；`input/hands.json` 手动覆盖 | `hands/p*.npz`、`hands.json`、`timeline.png` |
| impact | Windows | 受力反馈：检测打击，给被打方叠加短促冲击；躯干高频按视频校准放大；`input/impacts.json` 手动增删调 | `impact/p*.npz`、`impacts.json`、`timeline.png` |
| face | Windows | 表情：眼神盯对手、眨眼、受击表情、性格底色 → MetaHuman 面部控制板控件曲线（UE 端只在编辑器插件里写入序列） | `face/face_p*.json`、`face.json`、`timeline.png` |
| preview | Blender 4.5 | SMPL-X 场景 + 原机位/3/4 机位渲染 + 三联画 | `blender/preview.blend`、`triptych.mp4` |
| fbx | Blender 4.5 | UE 骨骼命名、厘米、Z 朝上的 FBX | `fbx/p*.fbx` |
| ue | UE 5.8（命令行或编辑器插件） | 导入 → IK Rig → 重定向到 MetaHuman → 专用关卡 + 完整 MetaHuman + 序列 → 度量 | UE 里 `/Game/AIMocap/<素材>/`，`ue/result.json` |
| qc | Windows | 质检报告 | `qc/report.html`、`metrics.json` |

每个阶段记录参数指纹（`state.json`），输入和参数没变就跳过；上游重跑后下游自动失效。

## 配置（config.toml）

- `[paths]`：各工具路径、UE 工程、WSL 发行版、GVHMR 目录
- `[generate]`：分辨率（动捕源 480p 足够，1080p 实测没有改善）、时长、积分上限、失败重试次数
- `[[person]]`：**按画面从左到右**指定每个人用哪个 MetaHuman 身体网格
- `[ue] uniform_horizontal_scale`：两人使用统一的水平缩放（= 两人"目标骨盆高 / 源骨盆高"的平均），让步幅匹配目标角色的腿长，同时保持两人相对位置
- `[hands]`：手型识别阈值（弯曲角 ≥110° 拳、<55° 掌）、平滑、识别不到时的兜底；`enabled = false` 恢复平伸手
- `[impact]`：打击检测门槛（各打击点最低速度、骤停比例、接触距离）、各部位冲击幅度 `amp_deg`、冲击快慢 `tau`；`enabled = false` 关闭
- `[face]`：表情强度、眨眼间隔、眼神转动比例 `gaze_gain` / 上限 `gaze_limit`、方向正负 `gaze_x_sign`（UE 里眼睛看反了就改 -1）；`[[person]] face_style` 设性格
- `[qc]`：质检阈值
- 临时覆盖写在 `config.local.toml`（不进 git）

## 质检报告怎么看

`qc/report.html`：
- **追踪**：身份数多于人数 = 有断轨或串号；覆盖率低于 95% 标红
- **着地脚深度速度**：清理后着地脚在镜头方向的滑动，应接近画面实测（几 cm/s）
- **脚踝重投影误差**：3D 结果投影回画面和 ViTPose 的差，超过 6 cm 说明解算和视频对不上
- **重定向误差**：躯干前倾、头部俯仰、手臂方向与源动作的差；驼背/低头类问题在这里会被拦下
- 俯视脚印图：锁定成功时，每次着地聚成一个点
- **手型**：每只手的识别率和拳/半握/掌占比，时间线图（色块 = 最终手型，黑点 = 识别出的弯曲角），和识别抽样裁剪图

## 手型（hands 阶段）

识别在单独的 Python 环境里跑（MediaPipe 和主环境的依赖不混）。装一次：

```
py -3.12 -m venv .venv-tools
.venv-tools\Scripts\python -m pip install mediapipe==1.0.1 opencv-python
mkdir models
curl -L -o models/hand_landmarker.task https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

做法：沿前臂方向在手腕外侧裁出手部、放大到 224，交给 MediaPipe HandLandmarker 取 3D 关键点，算四指总弯曲角；
≥110° 拳、<55° 掌、中间半握。识别不到的短缺口沿用前后手型，长缺口里"手臂快速伸直"判为拳，其余半握。
然后 7 帧投票、去掉短于 5 帧的片段，预设旋转沿时间平滑出约 5 帧的过渡。识别结果缓存，改阈值或手动覆盖只要 1 秒。

手动覆盖 `input/hands.json`（帧号；插件「手型修正…」按秒填，会自动换算）：
```json
[{"p": 0, "hand": "R", "from": 120, "to": 180, "state": "palm"}]
```
`hand` 可以是 `L`、`R`、`LR`（双手）；`state` 是 `fist` / `guard` / `palm` / `relaxed`。

## 已知限制

- **手指是状态，不是逐指还原**：GVHMR 不解手指，hands 阶段只判断拳 / 半握 / 掌 / 放松四种手型，再套预设。识别不到的帧（约 10–25%）按前后手型或动作兜底；手势类细节（剑指、鹰爪）需要手动覆盖或新增预设（`aimocap/handpose.py`）
- Seedance 在快速肢体交错时会形变，没有技术对策，一条编排多生成几版挑干净的
- 720p 的积分单价未实测，是估算值

## 版本管理

- 仓库：https://github.com/darcyjia/aimocap（私有），默认分支 `main`
- 新克隆后执行一次 `git config core.hooksPath hooks`，启用推送前的回归测试钩子
- 日常：改代码 → `python -m aimocap test` → 提交 → `git push`（钩子会再跑一次测试，指标变差会拒绝推送）
- 大改动或试验性改动开分支：`git switch -c 试验名`，验证通过再合回 `main`
- 发版：更新 `CHANGELOG.md`，然后 `git tag -a vX.Y.Z -m "说明" && git push origin vX.Y.Z`
- 基准素材的中间产物（`aimocap_work/`）不进仓库，只登记指标在 `tests/golden.json`

## 踩过的坑（代码里已处理，改代码时别退回去）

- **重定向姿态只对齐手臂/手指**。`auto_align_all_bones` 会让 MetaHuman 驼背约 30°、低头约 55°
- **GVHMR 的 global 结果每人各自归一化**，多人必须用相机空间结果 + 重力方向
- **GVHMR 自带清理只修 global 的根平移**，相机空间结果的脚滑集中在深度方向，所以需要 clean 阶段
- **地面只用站立帧估计**：躺地帧常被单目估到地面以下
- **SMPL-X 静止姿态原点在腰部**：导出 FBX 时抬到脚底 z=0，否则 UE 按负骨盆高度缩放
- **UE 只按比例缩放骨盆的垂直运动，水平原样传递**：所以需要统一水平缩放
- 同名资产删除后立刻 `create_asset` 返回 None：已存在的资产一律加载后重新配置
- 命令行模式无渲染：不能导出带网格的 FBX
- 序列用 spawnable 模板绑定 MetaHuman 拿不到蓝图组件（Body/Face 是构造时才生成的）→ 改为把角色放进专用关卡再 possessable 绑定
- UE 内置 Python 没有 numpy：插件不 import 本工具，而是调用系统 Python 的命令行（清掉 PYTHONHOME/PYTHONPATH）
- Blender 的 Python 出错时退出码仍为 0：所有调用都加了 `--python-exit-code 1`
- 通过 Python subprocess 调用 wsl.exe，不经过 Git Bash，避免了路径改写和多行脚本 CR 问题
- SMPL/SMPL-X 为非商用研究许可，仅限个人使用
