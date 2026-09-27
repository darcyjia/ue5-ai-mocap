"""阶段 solve：在 WSL 里跑追踪 + GVHMR，导出共享坐标系下的 SMPL-X 动作。"""
from ..util import SCRIPTS, file_sig, load_json, run as sh, win2wsl


def params(c, cfg):
    return {"video": file_sig(c.video), **cfg["solve"], "gvhmr": cfg["paths"]["gvhmr_dir"],
            "script": file_sig(SCRIPTS / "wsl" / "solve_wsl.py")}


def outputs(c, cfg):
    n = cfg["solve"]["num_people"]
    return [c.solve / "camera.json", c.solve / "track.json", c.solve / "smplx_common.npz"] + \
           [c.solve / f"p{k}.npz" for k in range(n)]


def run(c, cfg, args):
    if not c.video.exists():
        raise SystemExit(f"缺少 {c.video}")
    s, p = cfg["solve"], cfg["paths"]
    g = p["gvhmr_dir"]
    inner = (f"cd {g} && ./.venv/bin/python {win2wsl(SCRIPTS / 'wsl' / 'solve_wsl.py')} "
             f"--video {win2wsl(c.video)} --work {win2wsl(c.solve)} "
             f"--out {g}/outputs/aimocap/{c.name} --num {s['num_people']} --f_mm {s['f_mm']}")
    sh(["wsl.exe", "-d", p["wsl_distro"], "--", "bash", "-lc", inner], c.logs / "solve.log")
    info = load_json(c.solve / "solve.json", {})
    info["track"] = load_json(c.solve / "track.json", {}).get("people")
    return info
