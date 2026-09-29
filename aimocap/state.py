import time
from pathlib import Path

from .util import load_json, save_json


class Clip:
    """一条素材的工作目录。"""
    DIRS = ("input", "solve", "clean", "hands", "impact", "face", "blender", "fbx", "ue", "qc", "logs")

    def __init__(self, cfg, name):
        self.name = name
        self.root = Path(cfg["paths"]["work_root"]) / name
        for d in self.DIRS:
            setattr(self, d, self.root / d)
        self.video = self.input / "video.mp4"
        self.prompt = self.input / "prompt.txt"

    def plate(self):
        for ext in (".jpg", ".png", ".jpeg", ".webp"):
            p = self.input / f"plate{ext}"
            if p.exists():
                return p
        return None

    def mk(self):
        for d in self.DIRS:
            getattr(self, d).mkdir(parents=True, exist_ok=True)


class State:
    """state.json：记录每个阶段完成时的参数指纹和产物，用来跳过已是最新的阶段。"""

    def __init__(self, clip):
        self.path = clip.root / "state.json"
        self.d = load_json(self.path, {})

    def done(self, stage, h):
        rec = self.d.get(stage)
        return bool(rec) and rec["hash"] == h and all(Path(o).exists() for o in rec["outputs"])

    def mark(self, stage, h, outputs, extra=None):
        self.d[stage] = {"hash": h, "outputs": [str(o) for o in outputs],
                         "time": time.strftime("%Y-%m-%d %H:%M:%S"), "info": extra or {}}
        save_json(self.path, self.d)

    def hash_of(self, stage):
        return self.d.get(stage, {}).get("hash", "")
