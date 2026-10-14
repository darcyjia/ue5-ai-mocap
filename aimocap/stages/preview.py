"""阶段 preview：Blender 场景 + 原机位/3/4 机位渲染 + 三联画（原视频 | 原机位 | 3/4）。"""
import shutil

from ..util import SCRIPTS, file_sig, run as sh
from ..config import path as cpath

B = SCRIPTS / "blender"


def params(c, cfg):
    n = cfg["solve"]["num_people"]
    return {"in": [file_sig(c.impact / f"p{k}.npz") for k in range(n)],
            "scripts": [file_sig(B / s) for s in ("build_blend.py", "render_preview.py", "common.py")]}


def outputs(c, cfg):
    return [c.blender / "preview.blend", c.blender / "triptych.mp4"]


def run_(c, cfg):
    bl = cpath(cfg, "blender")
    blend = c.blender / "preview.blend"
    sh([bl, "-b", "--factory-startup", "--python-exit-code", "1", "--python", B / "build_blend.py", "--",
         "--npz-dir", c.impact, "--out", blend], c.logs / "preview_build.log")
    for sub in ("anim_orig", "anim_side"):
        shutil.rmtree(c.blender / sub, ignore_errors=True)
    sh([bl, "-b", blend, "--python-exit-code", "1", "--python", B / "render_preview.py", "--", "--out-dir", c.blender],
        c.logs / "preview_render.log")
    fps = 24
    sh([cpath(cfg, "ffmpeg"), "-v", "error", "-y", "-i", c.video,
         "-framerate", fps, "-i", c.blender / "anim_orig" / "f_%04d.png",
         "-framerate", fps, "-i", c.blender / "anim_side" / "f_%04d.png",
         "-filter_complex", "[0:v]scale=560:420,setsar=1,fps=24[a];[1:v]scale=560:420,setsar=1[b];"
                            "[2:v]scale=560:420,setsar=1[c];[a][b][c]hstack=3,format=yuv420p",
         "-c:v", "libx264", "-crf", "18", "-r", fps, "-an", c.blender / "triptych.mp4"], c.logs / "preview_ffmpeg.log")


def run(c, cfg, args):
    run_(c, cfg)
    return {"triptych": str(c.blender / "triptych.mp4")}
