"""本机初始化：自动探测各工具路径，写进 config.local.toml（不进仓库）。

    python -m aimocap setup                          # 只看探测结果，不写
    python -m aimocap setup --write                  # 写 config.local.toml
    python -m aimocap setup --project X.uproject --write --install-plugin
    python -m aimocap setup --install-tools          # 建手型识别环境 .venv-tools，下载手部模型

规则：现有配置里的路径还能用就保留；不能用或没配置的，换成探测到的。命令行给的 --project / --work-root /
--render-root 优先。写完建议跑 python -m aimocap doctor。
"""
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

from . import dreamina
from .config import PATH_KEYS
from .doctor import NO_WINDOW, _run, wsl_distros
from .util import ROOT, log

LOCAL = ROOT / "config.local.toml"
HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/"
                  "float16/latest/hand_landmarker.task")


def _drives():
    return [f"{d}:/" for d in string.ascii_uppercase if os.path.exists(f"{d}:/")]


def _ver_key(p):
    return tuple(int(x) for x in re.findall(r"\d+", str(p))[:3]) or (0,)


# ---------------- 探测 ----------------
def find_blender():
    cands = []
    for d in _drives():
        for pat in ("Program Files/Blender Foundation/Blender */blender.exe", "Program Files/blender-*/blender.exe",
                    "Program Files (x86)/Steam/steamapps/common/Blender/blender.exe", "blender*/blender.exe"):
            cands += Path(d).glob(pat)
    w = shutil.which("blender")
    if w:
        cands.append(Path(w))
    cands = [c for c in cands if c.is_file()]
    four = [c for c in cands if re.search(r"[\\/-]4\.\d", str(c))] or cands   # 优先 4.x
    return str(max(four, key=_ver_key)).replace("\\", "/") if four else None


def find_ffmpeg():
    cands = [shutil.which("ffmpeg"), "C:/FFmpeg/bin/ffmpeg.exe",
             os.path.expandvars("%LOCALAPPDATA%/Microsoft/WinGet/Links/ffmpeg.exe")]
    for d in _drives():
        cands += [str(p) for p in Path(d).glob("ffmpeg*/bin/ffmpeg.exe")]
    for c in cands:
        if c and Path(c).is_file():
            return str(Path(c)).replace("\\", "/")
    return None


def find_python():
    """要能 import numpy / scipy / matplotlib。先试当前解释器，再试 PATH 和 py 启动器。"""
    cands = [sys.executable, shutil.which("python")]
    code, out = _run(["py", "-0p"], timeout=20)
    if code == 0:
        cands += re.findall(r"([A-Za-z]:\\\S+python\.exe)", out)
    for c in cands:
        if c and Path(c).is_file() and "WindowsApps" not in c:
            ok, _ = _run([c, "-c", "import numpy,scipy,matplotlib"])
            if ok == 0:
                return str(Path(c)).replace("\\", "/")
    return None


def ue_installs():
    """Epic 启动器装的引擎：{版本: 引擎根目录}。"""
    dat = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Epic/UnrealEngineLauncher/LauncherInstalled.dat"
    out = {}
    try:
        for i in json.loads(dat.read_text(encoding="utf-8"))["InstallationList"]:
            if i["AppName"].startswith("UE_"):
                out[i["AppName"][3:]] = i["InstallLocation"]
    except (OSError, ValueError, KeyError):
        pass
    return out


def find_ue_cmd(project=None):
    inst = ue_installs()
    want = None
    if project and Path(project).is_file():
        want = json.loads(Path(project).read_text(encoding="utf-8")).get("EngineAssociation")
    order = ([want] if want in inst else []) + sorted(inst, key=_ver_key, reverse=True)
    for v in order:
        exe = Path(inst[v]) / "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
        if exe.is_file():
            return str(exe).replace("\\", "/")
    return None


def gvhmr_in(distro, current=None):
    """在发行版里找 GVHMR 目录（有 hmr4d 子目录的那个）。"""
    cands = ([current] if current else []) + ["~/mocap/GVHMR", "~/GVHMR", "~/code/GVHMR", "~/projects/GVHMR"]
    script = "; ".join(f'[ -d {c}/hmr4d ] && echo "FOUND {c}"' for c in cands) + \
             '; find ~ -maxdepth 3 -type d -name GVHMR 2>/dev/null | head -3 | sed "s/^/ANY /"'
    code, out = _run(["wsl.exe", "-d", distro, "--", "bash", "-lc", script], timeout=60)
    for l in out.splitlines():
        if l.startswith("FOUND "):
            return l[6:].strip()
    for l in out.splitlines():
        if l.startswith("ANY "):
            p = l[4:].strip()
            home = _run(["wsl.exe", "-d", distro, "--", "bash", "-lc", "echo $HOME"], timeout=20)[1].strip()
            return p.replace(home, "~", 1) if home and p.startswith(home) else p
    return None


def find_wsl(current_distro=None, current_gvhmr=None):
    ds = wsl_distros() or []
    order = ([current_distro] if current_distro in ds else []) + [d for d in ds if d != current_distro]
    for d in order:
        if "docker" in d.lower():
            continue
        g = gvhmr_in(d, current_gvhmr if d == current_distro else None)
        if g:
            return d, g
    ubuntu = [d for d in ds if d.lower().startswith("ubuntu")]
    return (ubuntu[0] if ubuntu else (ds[0] if ds else None)), None


# ---------------- 有效性 ----------------
def _valid(key, val, distros):
    if not val:
        return False
    if key in ("python", "blender", "ffmpeg", "dreamina", "ue_cmd", "ue_project"):
        return Path(val).is_file()
    if key in ("work_root", "render_root"):
        return Path(val).is_dir()
    if key == "wsl_distro":
        return val in (distros or [])
    return True       # gvhmr_dir 在 find_wsl 里一起核对


def plan(cfg, a):
    cur = dict(cfg.get("paths") or {})
    distros = wsl_distros()
    det = {}
    det["python"] = find_python()
    det["blender"] = find_blender()
    det["ffmpeg"] = find_ffmpeg()
    det["dreamina"] = (dreamina.exe(cfg) or "").replace("\\", "/") or None
    proj = a.project or (cur.get("ue_project") if _valid("ue_project", cur.get("ue_project"), distros) else None)
    det["ue_project"] = str(Path(proj)).replace("\\", "/") if proj else None
    det["ue_cmd"] = find_ue_cmd(proj)
    d, g = find_wsl(cur.get("wsl_distro"), cur.get("gvhmr_dir"))
    det["wsl_distro"], det["gvhmr_dir"] = d, g
    wr = a.work_root or cur.get("work_root") or str(ROOT.parent / "aimocap_work")
    det["work_root"] = str(Path(wr)).replace("\\", "/")
    rr = a.render_root or cur.get("render_root")
    if not rr:
        w = Path(det["work_root"])
        cands = [w.parent / "UE_Output", Path(w.anchor) / "UE_Output"]
        rr = next((str(c) for c in cands if c.is_dir()), str(w / "_renders"))
    det["render_root"] = str(Path(rr)).replace("\\", "/")

    rows = []
    for k in PATH_KEYS:
        c, dv = cur.get(k), det.get(k)
        forced = (k == "ue_project" and a.project) or (k == "work_root" and a.work_root) or \
                 (k == "render_root" and a.render_root)
        if forced:
            choose, why = dv, "命令行指定"
        elif k == "gvhmr_dir":
            choose, why = (dv, "探测到") if dv else (c, "保留（没探测到，请确认）" if c else "没找到")
        elif k in ("work_root", "render_root"):
            choose, why = (c, "保留") if c else (dv, "探测到" if Path(dv).is_dir() else "默认（会自动创建）")
        elif _valid(k, c, distros):
            choose, why = c, "保留"
        elif dv:
            choose, why = dv, "探测到"
        else:
            choose, why = None, "没找到"
        rows.append((k, c, choose, why))
    return rows


# ---------------- 写 TOML ----------------
def _toml_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_val(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def _dump(d, prefix=""):
    lines, tables = [], []
    for k, v in d.items():
        if isinstance(v, dict):
            tables.append((k, v))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            tables.append((k, v))
        else:
            lines.append(f"{k} = {_toml_val(v)}")
    out = "\n".join(lines) + ("\n" if lines else "")
    for k, v in tables:
        name = f"{prefix}{k}"
        if isinstance(v, list):
            for x in v:
                out += f"\n[[{name}]]\n" + _dump(x, name + ".")
        else:
            out += f"\n[{name}]\n" + _dump(v, name + ".")
    return out


def write_local(paths):
    old = tomllib.loads(LOCAL.read_text(encoding="utf-8")) if LOCAL.exists() else {}
    old.setdefault("paths", {})
    old["paths"].update({k: v for k, v in paths.items() if v})
    head = ("# 本机配置（python -m aimocap setup 生成，不进仓库）。会叠加在 config.toml 之上。\n"
            "# 路径用正斜杠。改完运行 python -m aimocap doctor 检查。\n")
    if LOCAL.exists():
        shutil.copy(LOCAL, LOCAL.with_suffix(".toml.bak"))
    LOCAL.write_text(head + _dump(old), encoding="utf-8")


# ---------------- 手型识别环境 ----------------
def install_tools(cfg):
    h = cfg.get("hands", {})
    venv = ROOT / Path(h.get("python", ".venv-tools/Scripts/python.exe")).parents[1]
    py = venv / "Scripts" / "python.exe"
    if not py.is_file():
        base = None
        for c in (["py", "-3.12"], ["py", "-3.11"], ["py", "-3.10"]):      # mediapipe 的 Windows 轮子最高到 3.12
            if _run([*c, "-c", "print(1)"], timeout=20)[0] == 0:
                base = c
                break
        if base is None:
            raise SystemExit("mediapipe 需要 Python 3.10–3.12：请先安装 Python 3.12（python.org），再重试")
        log(f"建手型识别环境：{venv}（{' '.join(base)}）")
        subprocess.run([*base, "-m", "venv", str(venv)], check=True)
    log("安装 mediapipe / opencv-python / numpy")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "mediapipe", "opencv-python", "numpy"], check=True)
    model = ROOT / h.get("model", "models/hand_landmarker.task")
    if not model.is_file():
        model.parent.mkdir(parents=True, exist_ok=True)
        log(f"下载手部模型 → {model}")
        tmp = model.with_suffix(".part")
        urllib.request.urlretrieve(HAND_MODEL_URL, tmp)
        tmp.replace(model)
    log("手型识别环境就绪")


def cmd(cfg, a):
    if a.install_tools:
        install_tools(cfg)
        if not a.write:
            return
    log("探测本机工具（扫描各盘 Program Files、Epic 启动器清单、WSL）……")
    rows = plan(cfg, a)
    w = max(len(k) for k in PATH_KEYS) + 2
    for k, c, choose, why in rows:
        mark = "=" if choose == c and choose else ("+" if choose else "?")
        print(f" {mark} {k:<{w}}{choose or '（空）'}    [{why}]")
        if c and choose != c:
            print(f"   {'':<{w}}原来：{c}")
    missing = [k for k, _, ch, _ in rows if not ch]
    if missing:
        print("\n没找到：" + "、".join(f"{k}（{PATH_KEYS[k]}）" for k in missing) + "。装好后重跑，或手动写进 config.local.toml。")
        if "ue_project" in missing:
            print("默认 UE 工程用 --project 指定，例如：python -m aimocap setup --project D:/MyProj/MyProj.uproject --write")
    if not a.write:
        print("\n这是预览。确认无误后加 --write 写入 config.local.toml。")
        return
    write_local({k: ch for k, _, ch, _ in rows})
    log(f"已写入 {LOCAL}")
    if a.install_plugin:
        from .install import install_ue_plugin
        from .config import load
        install_ue_plugin(load(), a.project)
    print("下一步：python -m aimocap doctor")
