"""aimocap：AI 视频 → 双人动捕 → MetaHuman。

  python -m aimocap new   <素材> --video v.mp4                 导入已有视频
  python -m aimocap new   <素材> --prompt 编排.txt --plate 构图板.jpg   准备生成
  python -m aimocap plate <素材> --prompt 构图板提示词.txt [--n 4]      免费出构图板候选
  python -m aimocap run   <素材> [--from 阶段] [--to 阶段] [--only 阶段] [--force]
  python -m aimocap status <素材>
  python -m aimocap test  [--update]                          回归测试
阶段顺序：generate → solve → clean → preview → fbx → ue → qc
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

from . import config as C
from .state import Clip, State
from .stages import clean, fbx, generate, preview, qc, solve, ue
from .util import log, params_hash

STAGES = [("generate", generate), ("solve", solve), ("clean", clean), ("preview", preview),
          ("fbx", fbx), ("ue", ue), ("qc", qc)]
NAMES = [n for n, _ in STAGES]


def cmd_new(cfg, a):
    c = Clip(cfg, a.clip)
    c.mk()
    if a.video:
        shutil.copy(a.video, c.video)
    if a.prompt:
        shutil.copy(a.prompt, c.prompt)
    if a.plate:
        for old in c.input.glob("plate.*"):
            old.unlink()
        shutil.copy(a.plate, c.input / ("plate" + Path(a.plate).suffix.lower()))
    log(f"素材目录：{c.root}")


def run_stages(cfg, clip_name, frm=None, to=None, only=None, force=False, args=None):
    c = Clip(cfg, clip_name)
    c.mk()
    st = State(c)
    i0 = NAMES.index(only or frm) if (only or frm) else 0
    i1 = i0 + 1 if only else (NAMES.index(to) + 1 if to else len(NAMES))
    prev = st.hash_of(NAMES[i0 - 1]) if i0 > 0 else ""
    for name, mod in STAGES[i0:i1]:
        if name == "preview" and not cfg["preview"]["enabled"]:
            log("== preview: 已在配置里关闭，跳过")
            continue
        p = mod.params(c, cfg)
        p["_upstream"] = prev
        h = params_hash(p)
        if not force and name != (only or frm) and st.done(name, h):
            log(f"== {name}: 已是最新，跳过")
            prev = h
            continue
        log(f"== {name} 开始")
        t0 = time.time()
        info = mod.run(c, cfg, args) or {}
        st.mark(name, h, mod.outputs(c, cfg), info)
        prev = h
        log(f"== {name} 完成（{time.time() - t0:.0f}s）")
    return c


def cmd_status(cfg, a):
    c = Clip(cfg, a.clip)
    st = State(c)
    for n in NAMES:
        rec = st.d.get(n)
        print(f"  {n:<9} {'✓ ' + rec['time'] if rec else '—'}")
    rep = c.qc / "report.html"
    if rep.exists():
        print(f"  报告：{rep}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aimocap", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new")
    s.add_argument("clip")
    s.add_argument("--video")
    s.add_argument("--prompt")
    s.add_argument("--plate")
    s = sub.add_parser("plate")
    s.add_argument("clip")
    s.add_argument("--prompt", required=True)
    s.add_argument("--n", type=int, default=4)
    s.add_argument("--ratio", default="4:3")
    s = sub.add_parser("run")
    s.add_argument("clip")
    s.add_argument("--from", dest="frm", choices=NAMES)
    s.add_argument("--to", choices=NAMES)
    s.add_argument("--only", choices=NAMES)
    s.add_argument("--force", action="store_true")
    s.add_argument("--regen", action="store_true", help="已有视频也重新生成（会花积分）")
    s = sub.add_parser("status")
    s.add_argument("clip")
    s = sub.add_parser("test")
    s.add_argument("--update", action="store_true")
    a = ap.parse_args(argv)
    cfg = C.load(a.config)
    if a.cmd == "new":
        cmd_new(cfg, a)
    elif a.cmd == "plate":
        generate.make_plates(Clip(cfg, a.clip), cfg, Path(a.prompt), a.n, a.ratio)
    elif a.cmd == "run":
        run_stages(cfg, a.clip, a.frm, a.to, a.only, a.force, a)
    elif a.cmd == "status":
        cmd_status(cfg, a)
    elif a.cmd == "test":
        from .regression import run_tests
        sys.exit(run_tests(cfg, a.update))
