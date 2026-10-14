"""环境检查：逐项看本机能不能跑 aimocap，缺什么、怎么补。

    python -m aimocap doctor          # 表格
    python -m aimocap doctor --json   # 给编辑器插件用

每项结果：ok（可用）/ warn（缺了只影响部分功能）/ fail（主流程跑不了）。有 fail 时退出码 1。
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import dreamina
from .config import PATH_KEYS
from .util import ROOT

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SETUP = "python -m aimocap setup --write"
GVHMR_CKPTS = [
    "inputs/checkpoints/gvhmr/gvhmr_siga24_release.ckpt",
    "inputs/checkpoints/hmr2/epoch=10-step=25000.ckpt",
    "inputs/checkpoints/vitpose/vitpose-h-multi-coco.pth",
    "inputs/checkpoints/yolo/yolov8x.pt",
    "inputs/checkpoints/body_models/smplx/SMPLX_NEUTRAL.npz",
    "inputs/checkpoints/body_models/smpl/SMPL_NEUTRAL.pkl",
]
GVHMR_DOC = "https://github.com/zju3dv/GVHMR/blob/main/docs/INSTALL.md"
SMPLX_SITE = "https://smpl-x.is.tue.mpg.de/（SMPL：https://smpl.is.tue.mpg.de/），需注册，非商用许可"


def _run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                           creationflags=NO_WINDOW)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as ex:
        return -1, str(ex)


def wsl_distros():
    """已装的 WSL 发行版名；没装 WSL 返回 None。wsl -l 的输出是 UTF-16LE。"""
    if not shutil.which("wsl.exe") and not shutil.which("wsl"):
        return None
    try:
        p = subprocess.run(["wsl.exe", "-l", "-q"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
                           creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = p.stdout
    text = raw.decode("utf-16-le", errors="ignore") if b"\x00" in raw else raw.decode("utf-8", "ignore")
    return [l.strip().strip("\x00﻿") for l in text.splitlines() if l.strip().strip("\x00﻿")]


def _item(name, level, detail, fix=""):
    return {"name": name, "level": level, "detail": detail, "fix": fix}


def _exe(p):
    return bool(p) and Path(p).is_file()


def check_config(cfg):
    local = ROOT / "config.local.toml"
    missing = [k for k in PATH_KEYS if not (cfg.get("paths") or {}).get(k)]
    if missing:
        return _item("本机配置", "fail" if set(missing) & {"work_root", "python", "blender", "ffmpeg", "wsl_distro", "gvhmr_dir"}
                     else "warn", f"缺少 paths：{', '.join(missing)}", f"运行 {SETUP}")
    return _item("本机配置", "ok", str(local) if local.exists() else "config.toml（建议用 setup 生成 config.local.toml）")


def check_work_root(cfg, key="work_root", name="工作目录", level="fail"):
    p = (cfg.get("paths") or {}).get(key)
    if not p:
        return _item(name, level, "没配置", f"运行 {SETUP}")
    d = Path(p)
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".aimocap_write_test"
        t.write_text("ok")
        t.unlink()
        return _item(name, "ok", str(d))
    except OSError as ex:
        return _item(name, level, f"{d} 不可写：{ex}", f"在 config.local.toml 里改 paths.{key}")


def check_python(cfg):
    py = (cfg.get("paths") or {}).get("python")
    if not py:
        return _item("系统 Python", "fail", "没配置", f"运行 {SETUP}")
    code, out = _run([py, "-c", "import sys,numpy,scipy,matplotlib;"
                                "print(sys.version.split()[0], numpy.__version__, scipy.__version__, matplotlib.__version__)"])
    if code != 0:
        return _item("系统 Python", "fail", f"{py}：{out.strip().splitlines()[-1] if out.strip() else '无法运行'}",
                     f'"{py}" -m pip install numpy scipy matplotlib')
    v = out.split()
    return _item("系统 Python", "ok", f"Python {v[0]}，numpy {v[1]}，scipy {v[2]}，matplotlib {v[3]}")


def check_hands(cfg):
    h = cfg.get("hands", {})
    if not h.get("enabled", True):
        return _item("手型识别", "ok", "已关闭（hands.enabled = false）")
    py = ROOT / h.get("python", ".venv-tools/Scripts/python.exe")
    model = ROOT / h.get("model", "models/hand_landmarker.task")
    if not py.is_file():
        return _item("手型识别", "warn", f"没有独立环境 {py}（手会保持平伸）", "python -m aimocap setup --install-tools")
    code, out = _run([str(py), "-c", "import mediapipe,cv2;print(mediapipe.__version__, cv2.__version__)"])
    if code != 0:
        return _item("手型识别", "warn", "环境里缺 mediapipe / opencv", "python -m aimocap setup --install-tools")
    if not model.is_file():
        return _item("手型识别", "warn", f"缺模型 {model}", "python -m aimocap setup --install-tools")
    v = out.split()
    return _item("手型识别", "ok", f"mediapipe {v[0]}，opencv {v[1]}")


def check_blender(cfg):
    b = (cfg.get("paths") or {}).get("blender")
    if not _exe(b):
        return _item("Blender", "fail", f"找不到：{b or '没配置'}", f"装 Blender 4.x（https://www.blender.org/download/），再运行 {SETUP}")
    code, out = _run([b, "--version"], timeout=90)
    m = re.search(r"Blender (\d+)\.(\d+)(?:\.(\d+))?", out)
    if not m:
        return _item("Blender", "warn", f"{b}：读不到版本", "")
    ver = ".".join(x for x in m.groups() if x)
    if int(m.group(1)) < 4:
        return _item("Blender", "warn", f"Blender {ver}，建议 4.x", "")
    return _item("Blender", "ok", f"Blender {ver}")


def check_ffmpeg(cfg):
    f = (cfg.get("paths") or {}).get("ffmpeg")
    if not _exe(f):
        return _item("ffmpeg", "fail", f"找不到：{f or '没配置'}", f"winget install Gyan.FFmpeg，再运行 {SETUP}")
    code, out = _run([f, "-version"])
    m = re.search(r"ffmpeg version (\S+)", out)
    return _item("ffmpeg", "ok" if code == 0 else "fail", f"ffmpeg {m.group(1) if m else '?'}")


def check_dreamina(cfg):
    st = dreamina.status(cfg, tries=1)
    if not st["installed"]:
        return _item("即梦（Seedance）", "warn", "没装命令行（只影响「生成视频」，导入现成视频不需要）",
                     "Git Bash 里运行 curl -fsSL https://jimeng.jianying.com/cli | bash")
    if not st["logged_in"]:
        return _item("即梦（Seedance）", "warn", "没登录或登录已过期",
                     "UE 菜单「AI 动捕 → 即梦账号 / 连接…」，或 python -m aimocap dreamina login")
    return _item("即梦（Seedance）", "ok", f"已登录，余额 {st['credit']} 积分（会员 {st['vip_level']}）")


def check_wsl_gvhmr(cfg):
    p = cfg.get("paths") or {}
    distro, g = p.get("wsl_distro"), p.get("gvhmr_dir")
    ds = wsl_distros()
    if ds is None:
        return [_item("WSL", "fail", "没装 WSL", "管理员 PowerShell：wsl --install -d Ubuntu-24.04")]
    if not distro or distro not in ds:
        return [_item("WSL", "fail", f"没有发行版 {distro or '（没配置）'}；已装：{', '.join(ds) or '无'}",
                      f"wsl --install -d Ubuntu-24.04，或运行 {SETUP} 选已有的")]
    out = [_item("WSL", "ok", distro)]
    if not g:
        return out + [_item("GVHMR", "fail", "没配置 gvhmr_dir", f"运行 {SETUP}")]
    script = (f"cd {g} 2>/dev/null || {{ echo NO_DIR; exit 0; }}; "
              + "; ".join(f'[ -f "{c}" ] && echo "OK {c}" || echo "MISS {c}"' for c in GVHMR_CKPTS)
              + "; [ -x .venv/bin/python ] && .venv/bin/python -c "
                "\"import torch,smplx,cv2;print('TORCH',torch.__version__,torch.cuda.is_available())\" 2>&1 | tail -1 "
                "|| echo NO_VENV")
    code, txt = _run(["wsl.exe", "-d", distro, "--", "bash", "-lc", script], timeout=180)
    if "NO_DIR" in txt:
        return out + [_item("GVHMR", "fail", f"{distro} 里没有 {g}", f"按 {GVHMR_DOC} 装到 {g}，或在配置里改 gvhmr_dir")]
    miss = [l[5:] for l in txt.splitlines() if l.startswith("MISS ")]
    m = re.search(r"TORCH (\S+) (True|False)", txt)
    if "NO_VENV" in txt or not m:
        out.append(_item("GVHMR 环境", "fail", f"{g}/.venv 不可用：{txt.strip().splitlines()[-1] if txt.strip() else ''}",
                         f"在 {g} 里建 .venv 并按 {GVHMR_DOC} 安装依赖（另需 smplx、opencv-python）"))
    elif m.group(2) != "True":
        out.append(_item("GVHMR 环境", "fail", f"torch {m.group(1)} 用不了 CUDA", "装和显卡驱动匹配的 CUDA 版 torch"))
    else:
        out.append(_item("GVHMR 环境", "ok", f"torch {m.group(1)}，CUDA 可用"))
    if miss:
        body = [x for x in miss if "body_models" in x]
        out.append(_item("GVHMR 模型", "fail", "缺：" + "，".join(Path(x).name for x in miss),
                         f"权重见 {GVHMR_DOC}" + (f"；人体模型从 {SMPLX_SITE} 下载" if body else "")))
    else:
        out.append(_item("GVHMR 模型", "ok", f"{len(GVHMR_CKPTS)} 个权重 / 人体模型都在"))
    return out


def check_ue(cfg):
    p = cfg.get("paths") or {}
    out = []
    if _exe(p.get("ue_cmd")):
        out.append(_item("UE 命令行", "ok", p["ue_cmd"]))
    else:
        out.append(_item("UE 命令行", "warn", f"找不到 {p.get('ue_cmd') or '（没配置）'}（只影响命令行导入；编辑器插件不需要）",
                         f"运行 {SETUP}"))
    proj = p.get("ue_project")
    if not proj or not Path(proj).is_file():
        out.append(_item("UE 工程", "warn", f"默认工程找不到：{proj or '（没配置）'}",
                         "python -m aimocap setup --project <你的.uproject> --write"))
        return out
    d = json.loads(Path(proj).read_text(encoding="utf-8"))
    eng = d.get("EngineAssociation", "?")
    link = Path(proj).parent / "Plugins" / "AIMocap"
    extra = [x.replace("\\", "/") for x in d.get("AdditionalPluginDirectories", [])]
    installed = link.exists() or str((ROOT / "ue_plugin").as_posix()) in extra
    out.append(_item("UE 工程", "ok" if installed else "warn",
                     f"{Path(proj).name}（UE {eng}）" + ("，插件已安装" if installed else "，插件还没装"),
                     "" if installed else f'python -m aimocap install-ue-plugin --project "{proj}"'))
    return out


def run_all(cfg):
    items = [check_config(cfg), check_work_root(cfg),
             check_work_root(cfg, "render_root", "渲染输出目录", "warn"),
             check_python(cfg), check_hands(cfg), check_blender(cfg), check_ffmpeg(cfg)]
    items += check_wsl_gvhmr(cfg)
    items += check_ue(cfg)
    items.append(check_dreamina(cfg))
    return items


ICON = {"ok": "✓", "warn": "!", "fail": "✗"}


def _pad(text, width):
    """按显示宽度补空格（中文算两格）。"""
    w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
    return text + " " * max(1, width - w)


def cmd(cfg, a):
    items = run_all(cfg)
    if a.json:
        print(json.dumps(items, ensure_ascii=False))
    else:
        w = 18
        for i in items:
            print(f" {ICON[i['level']]} {_pad(i['name'], w)}{i['detail']}")
            if i["level"] != "ok" and i["fix"]:
                print(f"   {' ' * w}→ {i['fix']}")
        n = {k: sum(i["level"] == k for i in items) for k in ICON}
        print(f"\n{n['ok']} 项正常，{n['warn']} 项提醒，{n['fail']} 项缺失" +
              ("。全部就绪。" if not n["fail"] and not n["warn"] else ""))
    if any(i["level"] == "fail" for i in items):
        raise SystemExit(1)
