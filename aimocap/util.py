import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def win2wsl(p):
    """G:/a/b -> /mnt/g/a/b"""
    s = str(Path(p).resolve()).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    if not m:
        raise ValueError(f"不是盘符路径: {s}")
    return f"/mnt/{m.group(1).lower()}/{m.group(2)}"


def run(cmd, logfile=None, env=None, cwd=None, timeout=None, check=True):
    """执行命令，输出写入 logfile，返回 (退出码, 输出文本)。
    直接用 subprocess 调 wsl.exe / blender / UE，不经过 Git Bash，
    因此没有 MSYS 路径改写和多行脚本 CR 的问题。"""
    shown = " ".join(str(c) for c in cmd)
    log("$ " + (shown if len(shown) < 240 else shown[:240] + " …"))
    e = os.environ.copy()
    e.update(env or {})
    p = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=e, cwd=cwd, timeout=timeout)
    out = p.stdout.decode("utf-8", errors="replace")
    if logfile:
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        Path(logfile).write_text(out, encoding="utf-8")
    if check and p.returncode != 0:
        tail = "\n".join(out.splitlines()[-40:])
        raise RuntimeError(f"命令失败（退出码 {p.returncode}）：{cmd[0]}\n日志：{logfile}\n{tail}")
    return p.returncode, out


def params_hash(d):
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


def file_sig(p):
    p = Path(p)
    if not p.exists():
        return None
    st = p.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def extract_json(text):
    """从命令输出里取第一个完整的 JSON 值（dreamina CLI 偶尔夹带非 JSON 行）。"""
    try:
        return json.loads(text)
    except Exception:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return dec.raw_decode(text[i:])[0]
            except Exception:
                continue
    return None


def load_json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save_json(p, d):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
