"""aimocap：AI 视频 → 双人动捕 → MetaHuman。

  python -m aimocap new   <素材> --video v.mp4                 导入已有视频
  python -m aimocap new   <素材> --prompt 编排.txt --plate 构图板.jpg   准备生成
  python -m aimocap plate <素材> --prompt 构图板提示词.txt [--n 4]      免费出构图板候选
  python -m aimocap run   <素材> [--from 阶段] [--to 阶段] [--only 阶段] [--force]
  python -m aimocap status <素材>
  python -m aimocap test  [--update]                          回归测试
  python -m aimocap install-ue-plugin                          把编辑器插件链接进 UE 工程
  python -m aimocap dreamina status|login|logout              即梦账号：查状态 / 扫码登录 / 退出
  python -m aimocap setup [--write] [--project X.uproject]   新电脑初始化：探测工具路径，写 config.local.toml
  python -m aimocap doctor                                     环境检查：缺什么、怎么补
  python -m aimocap previz <素材> [--auto-shots]              运镜预演：自动镜头表 → Blender 预演 → UE 相机和景深
（插件内部用：quote / uejob / mark）
阶段顺序：generate → solve → clean → hands → impact → face → preview → fbx → ue → qc
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from . import config as C
from .state import Clip, State
from .stages import clean, face, fbx, generate, hands, impact, preview, qc, solve, ue
from .util import load_json, log, params_hash

STAGES = [("generate", generate), ("solve", solve), ("clean", clean), ("hands", hands), ("impact", impact), ("face", face),
          ("preview", preview),
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


def mark_done(cfg, clip_name, stage, info=None):
    """外部（编辑器插件）完成了某阶段时登记到 state.json，参数指纹与 run 的算法一致。"""
    c = Clip(cfg, clip_name)
    st = State(c)
    i = NAMES.index(stage)
    mod = dict(STAGES)[stage]
    p = mod.params(c, cfg)
    p["_upstream"] = st.hash_of(NAMES[i - 1]) if i > 0 else ""
    st.mark(stage, params_hash(p), mod.outputs(c, cfg), info or {})


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
    ap.add_argument("--version", action="version", version=f"aimocap {__version__}")
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
    s.add_argument("--allow-spend", action="store_true", help="允许花积分生成视频")
    s.add_argument("--no-preview", action="store_true", help="跳过 Blender 预览")
    s = sub.add_parser("status")
    s.add_argument("clip")
    s = sub.add_parser("quote")
    s.add_argument("--resolution")
    s.add_argument("--duration", type=int)
    s = sub.add_parser("uejob")
    s.add_argument("clip")
    s = sub.add_parser("mark")
    s.add_argument("clip")
    s.add_argument("stage", choices=NAMES)
    s = sub.add_parser("install-ue-plugin")
    s.add_argument("--project", help="装到哪个 .uproject（默认 config 的 ue_project）")
    s = sub.add_parser("test")
    s.add_argument("--update", action="store_true")
    s = sub.add_parser("dreamina", help="即梦账号：status / login / check / logout")
    s.add_argument("action", choices=["status", "login", "check", "logout"])
    s.add_argument("--json", action="store_true", help="login：只发起登录并打印授权信息（插件用）")
    s.add_argument("--device-code", help="check：login --json 返回的 device_code")
    s.add_argument("--poll", type=int, default=300, help="等扫码授权的最长秒数")
    s = sub.add_parser("setup", help="探测本机工具路径，写 config.local.toml")
    s.add_argument("--write", action="store_true", help="写入（不加只预览）")
    s.add_argument("--project", help="默认 UE 工程 .uproject（也决定用哪个版本的引擎）")
    s.add_argument("--work-root", help="素材工作目录")
    s.add_argument("--render-root", help="UE 渲染输出目录")
    s.add_argument("--install-plugin", action="store_true", help="写完顺便把插件装进 --project 指定的工程")
    s.add_argument("--install-tools", action="store_true", help="建手型识别环境 .venv-tools、下载手部模型")
    s = sub.add_parser("doctor", help="环境检查")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("previz", help="运镜预演：镜头表 → Blender 预演 → 导出 UE 相机和景深")
    s.add_argument("clip")
    s.add_argument("--res", default="1128x480", help="预演渲染分辨率（宽x高，2.35:1 = 1128x480）")
    s.add_argument("--auto-shots", action="store_true", help="按受力检测重新生成镜头表（已有的会备份）")
    s.add_argument("--no-render", action="store_true", help="只出相机，不渲染预演视频（快很多）")
    s.add_argument("--force", action="store_true", help="重建 Blender 预演场景")
    a = ap.parse_args(argv)
    cfg = C.load(a.config)
    if a.cmd == "new":
        cmd_new(cfg, a)
    elif a.cmd == "plate":
        generate.make_plates(Clip(cfg, a.clip), cfg, Path(a.prompt), a.n, a.ratio)
    elif a.cmd == "run":
        if a.no_preview:
            cfg["preview"]["enabled"] = False
        run_stages(cfg, a.clip, a.frm, a.to, a.only, a.force, a)
    elif a.cmd == "status":
        cmd_status(cfg, a)
    elif a.cmd == "quote":
        print(json.dumps({"estimate": generate.estimate(cfg, a.resolution, a.duration), "balance": generate.credits(cfg),
                          "max_credits": cfg["generate"]["max_credits"]}, ensure_ascii=False))
    elif a.cmd == "uejob":
        print(json.dumps(ue.build_job(Clip(cfg, a.clip), cfg), ensure_ascii=False))
    elif a.cmd == "mark":
        mark_done(cfg, a.clip, a.stage, load_json(Clip(cfg, a.clip).ue / "result.json") if a.stage == "ue" else None)
        log(f"已登记 {a.clip} 的 {a.stage} 阶段")
    elif a.cmd == "install-ue-plugin":
        from .install import install_ue_plugin
        install_ue_plugin(cfg, a.project)
    elif a.cmd == "test":
        from .regression import run_tests
        sys.exit(run_tests(cfg, a.update))
    elif a.cmd == "dreamina":
        from . import dreamina
        dreamina.cmd(cfg, a)
    elif a.cmd == "setup":
        from . import setup_cmd
        setup_cmd.cmd(cfg, a)
    elif a.cmd == "doctor":
        from . import doctor
        doctor.cmd(cfg, a)
    elif a.cmd == "previz":
        from . import previz
        previz.run(cfg, a.clip, a)
