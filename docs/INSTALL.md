# 安装（新电脑从零开始）

整个流程只在 **Windows 10/11 + NVIDIA 显卡** 上测过（作者用 RTX 3090，24 GB 显存）。装完用 `python -m aimocap doctor` 逐项检查，缺什么它会告诉你怎么补。

## 1. 先装这些

| 软件 | 用途 | 说明 |
|---|---|---|
| Unreal Engine 5.8 | MetaHuman、重定向、渲染 | Epic 启动器安装；工程里要有 MetaHuman 角色 |
| Python 3.13 | 主程序 | python.org 安装，然后 `python -m pip install numpy scipy matplotlib` |
| Python 3.12 | 手型识别（MediaPipe） | 只用来建 `.venv-tools`，第 3 步会自动建 |
| Blender 4.x | 预览、导出 FBX | blender.org，装在哪都行，setup 会找 |
| ffmpeg | 抽音轨、拼视频 | `winget install Gyan.FFmpeg` |
| WSL2 + Ubuntu 24.04 | 跑 GVHMR | 管理员 PowerShell：`wsl --install -d Ubuntu-24.04` |
| 即梦命令行 dreamina | 生成视频（可选） | Git Bash：`curl -fsSL https://jimeng.jianying.com/cli \| bash`。只用现成视频可以不装 |

## 2. 在 WSL 里装 GVHMR

按 [GVHMR 官方安装说明](https://github.com/zju3dv/GVHMR/blob/main/docs/INSTALL.md) 装，有两点和官方说明不一样：

- 放到 `~/mocap/GVHMR`（放别处也行，setup 会在家目录下找）
- 环境用**目录里的 venv**：`cd ~/mocap/GVHMR && python3 -m venv .venv`，再用 `.venv/bin/pip` 装 CUDA 版 torch、`requirements.txt`、`pip install -e .`，另外装 `smplx opencv-python`

需要的权重（放在 `inputs/checkpoints/` 下）：

- `gvhmr/gvhmr_siga24_release.ckpt`、`hmr2/epoch=10-step=25000.ckpt`、`vitpose/vitpose-h-multi-coco.pth`、`yolo/yolov8x.pt`
- 人体模型 `body_models/smplx/SMPLX_NEUTRAL.npz`、`body_models/smpl/SMPL_NEUTRAL.pkl`：要在 [SMPL-X](https://smpl-x.is.tue.mpg.de/) / [SMPL](https://smpl.is.tue.mpg.de/) 官网注册后下载

## 3. 初始化

```bash
git clone <仓库地址> aimocap
cd aimocap
python -m aimocap setup --project D:/MyProj/MyProj.uproject            # 预览探测结果
python -m aimocap setup --project D:/MyProj/MyProj.uproject --write --install-plugin
python -m aimocap setup --install-tools                                # 手型识别环境 + 手部模型
python -m aimocap doctor                                               # 全部 ✓ 就可以用了
git config core.hooksPath hooks                                        # 推送前自动跑回归测试（开发用）
```

`setup` 会扫描各盘的 Program Files、Epic 启动器清单和 WSL，自动找到 Blender、ffmpeg、Python、UE、GVHMR，然后写进 `config.local.toml`（只在本机，不进仓库）。找错了就直接改这个文件。素材工作目录默认是仓库旁边的 `aimocap_work`，可以用 `--work-root` 指定；UE 渲染输出用 `--render-root` 指定。

## 4. 在 UE 里

重新打开工程，主菜单栏出现 **AI 动捕**：

1. **环境检查…**：和 `doctor` 一样，结果在弹窗里
2. **即梦账号 / 连接…**：要生成视频的话，用抖音扫码授权一次（不生成视频可以跳过）
3. **新建动捕…**：选视频（或提示词 + 构图板）和两个 MetaHuman，开始

## 许可

本仓库的代码随便用。但它依赖的 **GVHMR 和 SMPL / SMPL-X 只许非商业用途**（研究、教育、个人非营利），商用需要分别找作者和 Meshcapade 授权。即梦 / Seedance 是付费在线服务，生成要花积分。

---

## Installation (English, short)

Tested on Windows 10/11 with an NVIDIA GPU. Install UE 5.8, Python 3.13 (`pip install numpy scipy matplotlib`), Blender 4.x, ffmpeg, WSL2 Ubuntu 24.04, and optionally the Dreamina CLI. Install [GVHMR](https://github.com/zju3dv/GVHMR/blob/main/docs/INSTALL.md) inside WSL at `~/mocap/GVHMR` using an in-folder `.venv` (plus `smplx opencv-python`), with the checkpoints and SMPL/SMPL-X body models listed above. Then:

```bash
python -m aimocap setup --project <your.uproject> --write --install-plugin
python -m aimocap setup --install-tools
python -m aimocap doctor
```

`setup` auto-detects tool paths and writes `config.local.toml`; `doctor` checks every dependency and tells you how to fix what's missing. **GVHMR and SMPL/SMPL-X are non-commercial licenses.** The UE plugin UI is currently Chinese-only.
