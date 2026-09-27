"""阶段 fbx：Blender 导出 UE 用的 FBX（每人一个，p0.fbx / p1.fbx）。"""
from ..util import SCRIPTS, file_sig, run as sh


def params(c, cfg):
    n = cfg["solve"]["num_people"]
    return {"in": [file_sig(c.clean / f"p{k}.npz") for k in range(n)],
            "script": file_sig(SCRIPTS / "blender" / "export_fbx.py")}


def outputs(c, cfg):
    return [c.fbx / f"p{k}.fbx" for k in range(cfg["solve"]["num_people"])]


def run(c, cfg, args):
    _, out = sh([cfg["paths"]["blender"], "-b", "--factory-startup", "--python-exit-code", "1", "--python",
                 SCRIPTS / "blender" / "export_fbx.py", "--", "--npz-dir", c.clean, "--out-dir", c.fbx],
                c.logs / "fbx.log")
    return {"exported": [l.split("@@ ")[1] for l in out.splitlines() if "@@ exported" in l]}
