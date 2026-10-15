# 更新记录

版本号：`主.次.修订`。改了阶段产物格式或配置项 → 次版本；修 bug、调阈值 → 修订号。
发版：`git tag -a vX.Y.Z -m "说明" && git push origin vX.Y.Z`

## v0.5.0 — 2026-10-15

公开发布（github.com/darcyjia/ue5-ai-mocap）。整个流程都能在插件菜单里完成。「运镜预演」「渲染设置」两个菜单是测试版：命令行已测通，编辑器里有问题请提 Issue。

**运镜预演和渲染进菜单**（整个流程不再需要命令行）
- 新命令 `python -m aimocap previz <素材>`：Blender 预演场景 → 自动镜头表 → 相机和预演渲染 → 拼预演视频（带原声）→ 导出 UE 相机和景深。15 秒素材约 2.5 分钟
- 自动镜头表（`aimocap/previz.py`）：按受力检测切镜头，九十年代港片规则——开场定格高机位缓降、全景交代、打中那一下切、侧面跟拍 / 过肩 / 低机位仰拍 / 受击近景轮换（相邻不重复，近景最长 1.2 秒）、最狠的一下两个角度重复、结尾全景环绕；机位都在原机位一侧。已有的 `shots.json` 沿用，`--auto-shots` 重新生成（旧的备份）
- `export_cams_ue.py --shots`：按镜头对焦目标算景深 `dof.json`（焦距 ≥45mm f/2.8，≥30mm f/4，其余 f/5.6），导入运镜时全镜头开景深
- 回归测试：本机没有测试素材时跳过并提示（不再让新克隆和推送前检查失败）
- 新增 MIT 许可证（第三方组件按各自许可，见 LICENSE 末尾）
- 插件新增「运镜预演（Blender）…」（完成后自动打开预演视频，问要不要直接导入运镜）和「渲染设置…」（找最新的成片序列，建 MRQ 草稿 / 正式配置和队列，可以直接开始渲染）

## v0.4.0 — 2026-10-14

可以迁移到别的电脑：`setup` 自动配置路径，`doctor` 检查环境，即梦在插件里扫码登录。

**即梦账号**
- 新命令 `python -m aimocap dreamina status | login | check | logout`。login 用 OAuth 设备码：打开授权页，等抖音扫码，`--json` 只发起登录并打印授权信息（插件用）
- 插件新增「即梦账号 / 连接…」：显示登录状态和余额，没连接时一键打开授权页，后台等扫码（最多 5 分钟），成功后报余额；可以退出账号。登录由 UE 进程发起，令牌存进用户自己的凭据库，绕开 Claude 桌面应用（MSIX）的凭据隔离
- 生成视频、出构图板之前先检查即梦连接；没连接直接问要不要现在连接，不再让用户自己开 PowerShell
- dreamina 路径自动查找：config → PATH → `~/bin/dreamina.exe`；都没有时给出官方安装命令

**可迁移**
- 新命令 `python -m aimocap setup`：扫描各盘 Program Files、Epic 启动器清单和 WSL，自动找到 Python / Blender / ffmpeg / dreamina / UE / GVHMR，写进 `config.local.toml`。还能用的旧路径会保留；`--project` / `--work-root` / `--render-root` 可以手动指定，`--install-plugin` 顺便装插件，`--install-tools` 建手型识别环境并下载手部模型
- 新命令 `python -m aimocap doctor`：13 项检查（配置、工作目录、渲染目录、Python 包、手型环境、Blender、ffmpeg、WSL、GVHMR 环境和 6 个权重、UE 命令行、工程和插件、即梦），每项缺失都给修复办法；`--json` 给插件用。插件新增「环境检查…」
- `config.toml` 不再含本机路径（移到 `config.local.toml`）；缺路径时提示运行 setup，不再 KeyError
- 新增 `paths.render_root`：MRQ 输出目录不再写死 `G:/UE_Output`（没配置时用工程 Saved/MovieRenders）；`ue_remote.py` 按 `ue_cmd` 找引擎
- 安装文档 `docs/INSTALL.md`（中文 + 英文简版）

**运镜与场景**（v0.3.0 之后陆续加入）
- 运镜：急推（snap），震动幅度可调（`shake` 可以写数字）
- 预演可以放进外部场景（导入 UE 关卡 glTF，`--env-scale` 以原点缩放），两人整体放到指定位置；相机自动避让遮挡（换角度 / 升高 / 拉近）
- 按 UE 工程覆盖设置 `input/ue.json`：场景关卡用关卡实例引用、角色和原机位放到指定位置、运镜版本；插件可以装到指定工程；网格缓存按工程分开
- 画幅比例由 `--res` 决定，写进剪辑表；UE 相机胶片按比例、约束宽高比
- 特写景深：导入运镜时读 `dof.json`（按脸部距离对焦 + 光圈）

**渲染（MRQ）**
- `mrq_setup.py` 影视级设置：标准 1080p（2.35 画面上下黑边）、16 次时间采样、H.265 mp4（不留序列帧），草稿版 + 队列；参数化（序列 / 关卡 / 素材名）
- 快门改成帧开始（FRAME_OPEN）、关掉毛发模拟：修掉每个镜头切点第一帧的残影和头发拖影
- 强制保存配置资产（直接改属性不会标脏）

**MetaHuman 与 UE 远程控制**
- `scripts/tools/ue_remote.py`：给运行中的编辑器发 Python（自动挑可用端口，避开 Hyper-V 保留段；`--project` 传工程名）
- `mh_actors.py` 按 JSON 规格捏 MetaHuman 演员（体型、头发、服装）并组装；`mh_outfit.py` 换装（默认不脚本组装，避免把 Creator 里设的 8K 烘焙降回 2K）、改服装颜色；`mh_upgrade.py` 请求 8K 源贴图并重新组装
- 编辑器里远程跑 ue 阶段、导入运镜；场景 glb 导入（编辑器或 commandlet）
- `studio_build.py`：人像 / 戏剧 / 硬光预设影棚，270° 弧形背景墙（自发光），`--here` 直接搭进当前关卡

**修复**
- 重定向：每次新建一个手臂对齐姿态。在已有重定向器上重置姿态再对齐会算错（rec01：前臂偏 58°，手臂误差 1.1° → 14.6°）
- 安装插件：非 NTFS 盘（exFAT）建不了目录链接时，改用工程的 AdditionalPluginDirectories

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
