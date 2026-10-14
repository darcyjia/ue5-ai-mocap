"""定位 aimocap 仓库、读配置、同步/后台调用命令行工具。
UE 自带的 Python 没有 numpy，所以解算、清理、质检都交给系统 Python 跑 `python -m aimocap`，
插件只负责界面和编辑器内的 UE 阶段（scripts/ue/ue_pipeline.py）。"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import unreal

NO_WINDOW = 0x08000000


def repo_root():
    """插件目录是指向仓库 ue_plugin/AIMocap 的目录链接，realpath 能找回仓库根。"""
    for p in Path(os.path.realpath(__file__)).parents:
        if (p / "aimocap" / "cli.py").exists():
            return p
    env = os.environ.get("AIMOCAP_REPO")
    if env and (Path(env) / "aimocap" / "cli.py").exists():
        return Path(env)
    raise RuntimeError("找不到 aimocap 仓库（插件应通过 python -m aimocap install-ue-plugin 安装）")


REPO = repo_root()
if str(REPO / "scripts" / "ue") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts" / "ue"))


def config():
    cfg = {}
    for name in ("config.toml", "config.local.toml"):
        p = REPO / name
        if p.exists():
            d = tomllib.loads(p.read_text(encoding="utf-8"))
            for k, v in d.items():
                cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


def work_root():
    w = (config().get("paths") or {}).get("work_root")
    if not w:
        raise RuntimeError("aimocap 还没配置本机路径。先在命令行运行：python -m aimocap setup --project <本工程.uproject> --write\n"
                           "然后用菜单「环境检查…」确认。")
    return Path(w)


def clip_dir(name):
    return work_root() / name


def _cmd(args):
    return [config()["paths"].get("python", "python"), "-m", "aimocap", *args]


def _env():
    e = os.environ.copy()
    e["PYTHONIOENCODING"] = "utf-8"
    for k in ("PYTHONHOME", "PYTHONPATH"):           # 别把 UE 内置 Python 的环境带给系统 Python
        e.pop(k, None)
    return e


def cli(args, timeout=600):
    """同步调用，返回 (退出码, 输出)。只用于几秒内能完成的命令。"""
    p = subprocess.run(_cmd(args), cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=_env(),
                       creationflags=NO_WINDOW, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", errors="replace")


def cli_json(args):
    code, out = cli(args)
    if code != 0:
        raise RuntimeError(out[-1500:])
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError("没有拿到 JSON 输出：\n" + out[-800:])


class BackgroundJob:
    """后台跑 `python -m aimocap …`，每帧把输出转到 Output Log；结束后在主线程回调 on_done(job, ok)。"""

    def __init__(self, title, clip, args, on_done, log_args=True):
        self.title, self.clip, self.on_done = title, clip, on_done
        self.lines, self.stage, self.t0 = [], "启动", time.time()
        self.q = queue.Queue()
        self.proc = subprocess.Popen(_cmd(args), cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     env=_env(), creationflags=NO_WINDOW)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.handle = unreal.register_slate_post_tick_callback(self._tick)
        unreal.log(f"[AI 动捕] 开始：{title}" + (f"（{' '.join(args)}）" if log_args else ""))   # 登录的设备码不进日志

    @property
    def running(self):
        return self.handle is not None

    def _read(self):
        for raw in iter(self.proc.stdout.readline, b""):
            self.q.put(raw.decode("utf-8", errors="replace").rstrip())

    def _tick(self, _dt):
        while not self.q.empty():
            line = self.q.get_nowait()
            self.lines = (self.lines + [line])[-300:]
            if "== " in line and "开始" in line:
                self.stage = line.split("== ")[1].split(" ")[0]
            unreal.log(f"[AI 动捕] {line}")
        if self.proc.poll() is not None and not self.reader.is_alive() and self.q.empty():
            unreal.unregister_slate_post_tick_callback(self.handle)
            self.handle = None
            ok = self.proc.returncode == 0
            unreal.log(f"[AI 动捕] 结束：{self.title}（{'成功' if ok else '失败'}，{time.time() - self.t0:.0f}s）")
            try:
                self.on_done(self, ok)
            except Exception:
                import traceback
                tb = traceback.format_exc()
                unreal.log_error(f"[AI 动捕] 后续步骤出错：\n{tb}")
                unreal.EditorDialog.show_message(
                    "AI 动捕：出错", f"「{self.clip}」后台处理已完成，但编辑器内的后续步骤出错：\n\n{tb[-1500:]}\n\n"
                    "修好后可以用「换角色 / 重做重定向…」只重做 UE 部分。",
                    unreal.AppMsgType.OK, unreal.AppReturnType.OK)

    def elapsed(self):
        return time.time() - self.t0


CURRENT = None


def start(title, clip, args, on_done):
    global CURRENT
    CURRENT = BackgroundJob(title, clip, args, on_done)
    return CURRENT


def busy():
    return CURRENT is not None and CURRENT.running


def open_path(p):
    os.startfile(str(p))
