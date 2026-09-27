# aimocap：AI 视频 → 双人动捕 → MetaHuman

用 Seedance 生成武打视频，GVHMR 解算双人动作，清理脚滑，重定向到 UE 5.8 的 MetaHuman，自动生成关卡序列和质检报告。个人使用。

## 快速开始

```bash
cd G:/claude/video/aimocap

# 已有视频
python -m aimocap new fight_01 --video 某视频.mp4
python -m aimocap run fight_01

# 从提示词生成（花积分，按 config 的 max_credits 限额）
python -m aimocap plate fight_01 --prompt 构图板提示词.txt   # 免费出 4 张构图板候选到 input/plates/
python -m aimocap new   fight_01 --prompt 编排.txt --plate input/plates/挑中的那张.jpg
python -m aimocap run   fight_01

python -m aimocap status fight_01         # 各阶段状态
python -m aimocap run fight_01 --from ue  # 从某一阶段重跑（改了角色、重定向参数时）
python -m aimocap test                    # 回归测试
```

跑 `ue` 阶段前**必须关闭 UE 编辑器**（命令行模式写资产，编辑器开着会冲突；关闭时不要保存本素材的资产）。

## 阶段

| 阶段 | 运行环境 | 做什么 | 产物（`aimocap_work/<素材>/`） |
|---|---|---|---|
| generate | Windows / 即梦 CLI | 构图板 + 编排提示词 → Seedance 视频；已有视频则跳过 | `input/video.mp4` |
| solve | WSL2 / GVHMR | 多人追踪（按画面从左到右编号 p0、p1…）→ 每人 GVHMR → 共享坐标系、重力对齐、贴地 | `solve/p*.npz`、`camera.json`、`track.json` |
| clean | Windows | 脚部锁定：每人贴地、着地检测并合并碎片、根部水平校正、腿部 IK | `clean/p*.npz`、`cleanup.json` |
| preview | Blender 4.5 | SMPL-X 场景 + 原机位/3/4 机位渲染 + 三联画 | `blender/preview.blend`、`triptych.mp4` |
| fbx | Blender 4.5 | UE 骨骼命名、厘米、Z 朝上的 FBX | `fbx/p*.fbx` |
| ue | UE 5.8 命令行 | 导入 → IK Rig → 重定向到 MetaHuman → 关卡序列 → 度量 | UE 里 `/Game/AIMocap/<素材>/`，`ue/result.json` |
| qc | Windows | 质检报告 | `qc/report.html`、`metrics.json` |

每个阶段记录参数指纹（`state.json`），输入和参数没变就跳过；上游重跑后下游自动失效。

## 配置（config.toml）

- `[paths]`：各工具路径、UE 工程、WSL 发行版、GVHMR 目录
- `[generate]`：分辨率（动捕源 480p 足够，1080p 实测没有改善）、时长、积分上限、失败重试次数
- `[[person]]`：**按画面从左到右**指定每个人用哪个 MetaHuman 身体网格
- `[ue] uniform_horizontal_scale`：两人使用统一的水平缩放（= 两人"目标骨盆高 / 源骨盆高"的平均），让步幅匹配目标角色的腿长，同时保持两人相对位置
- `[qc]`：质检阈值
- 临时覆盖写在 `config.local.toml`（不进 git）

## 质检报告怎么看

`qc/report.html`：
- **追踪**：身份数多于人数 = 有断轨或串号；覆盖率低于 95% 标红
- **着地脚深度速度**：清理后着地脚在镜头方向的滑动，应接近画面实测（几 cm/s）
- **脚踝重投影误差**：3D 结果投影回画面和 ViTPose 的差，超过 6 cm 说明解算和视频对不上
- **重定向误差**：躯干前倾、头部俯仰、手臂方向与源动作的差；驼背/低头类问题在这里会被拦下
- 俯视脚印图：锁定成功时，每次着地聚成一个点

## 已知限制

- **没有手指**：GVHMR 只出身体 21 个关节，MetaHuman 手是平掌
- **序列里是无头的身体网格**：命令行模式拿不到 MetaHuman 蓝图的 Body 组件。要完整角色，在 Sequencer 里把 `BP_<角色>` 拖进去，在它的 Body 组件上加动画轨道，选 `MH_p*_Anim`
- Seedance 在快速肢体交错时会形变，没有技术对策，一条编排多生成几版挑干净的
- 720p 的积分单价未实测，是估算值

## 踩过的坑（代码里已处理，改代码时别退回去）

- **重定向姿态只对齐手臂/手指**。`auto_align_all_bones` 会让 MetaHuman 驼背约 30°、低头约 55°
- **GVHMR 的 global 结果每人各自归一化**，多人必须用相机空间结果 + 重力方向
- **GVHMR 自带清理只修 global 的根平移**，相机空间结果的脚滑集中在深度方向，所以需要 clean 阶段
- **地面只用站立帧估计**：躺地帧常被单目估到地面以下
- **SMPL-X 静止姿态原点在腰部**：导出 FBX 时抬到脚底 z=0，否则 UE 按负骨盆高度缩放
- **UE 只按比例缩放骨盆的垂直运动，水平原样传递**：所以需要统一水平缩放
- 同名资产删除后立刻 `create_asset` 返回 None：已存在的资产一律加载后重新配置
- 命令行模式无渲染：不能导出带网格的 FBX
- Blender 的 Python 出错时退出码仍为 0：所有调用都加了 `--python-exit-code 1`
- 通过 Python subprocess 调用 wsl.exe，不经过 Git Bash，避免了路径改写和多行脚本 CR 问题
- SMPL/SMPL-X 为非商用研究许可，仅限个人使用
