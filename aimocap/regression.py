"""回归测试：对 tests/golden.json 里登记的素材，只重跑 clean 和 qc（不重跑 GVHMR/Blender/UE），
与登记的指标比较。改了清理或质检代码后跑一遍，确认没有变差。
  python -m aimocap test            比较
  python -m aimocap test --update   把当前结果登记为基准
测试素材（工作目录里的解算结果）不进仓库：本机没有某条素材就跳过它，全都没有时直接通过并提示。"""
import json

from .cli import run_stages
from .state import Clip
from .util import ROOT, load_json, log

GOLDEN = ROOT / "tests" / "golden.json"
KEYS = [("after", "dep3d", 2.0), ("after", "lat3d", 2.0), ("after", "reproj_cm", 1.0), ("after", "penetration_pct", 2.0)]


def _extract(m):
    out = {}
    for k, p in enumerate(m["persons"]):
        for stage, key, _ in KEYS:
            out[f"p{k}.{stage}.{key}"] = round(p[stage][key], 3)
    return out


def run_tests(cfg, update=False):
    g = load_json(GOLDEN, {"clips": {}})
    if not g["clips"]:
        print(f"{GOLDEN} 里没有登记素材。先完整跑一条素材，再在 golden.json 的 clips 里加上它的名字并 --update。")
        return 1
    from .stages import solve
    fails, ran = 0, 0
    for name in list(g["clips"]):
        try:
            c = Clip(cfg, name)
            missing = [p for p in solve.outputs(c, cfg) if not p.exists()]
        except SystemExit:                                # 没配置工作目录（新克隆的仓库）
            missing = ["paths.work_root"]
        if missing:
            print(f"  跳过 {name}：本机没有这条测试素材（缺 {missing[0]}）")
            continue
        ran += 1
        log(f"== 回归：{name}")
        run_stages(cfg, name, only="clean", force=True)   # 只重跑清理和质检，不动 GVHMR/Blender/UE
        run_stages(cfg, name, only="qc", force=True)
        cur = _extract(load_json(Clip(cfg, name).qc / "metrics.json"))
        if update:
            g["clips"][name] = cur
            continue
        tol = {f"p{k}.{s}.{key}": t for k in range(4) for s, key, t in KEYS}
        for key, ref in g["clips"][name].items():
            v = cur.get(key)
            worse = v is None or v > ref + tol.get(key, 1.0)
            print(f"  {'FAIL' if worse else 'ok  '} {key}: {v}（基准 {ref}）")
            fails += worse
    if not ran:
        print("没有可用的测试素材，跳过回归测试（测试素材只在作者本机；要启用：先完整跑一条素材，"
              "把名字登记进 tests/golden.json 的 clips，再运行 python -m aimocap test --update）")
        return 0
    if update:
        GOLDEN.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        log("已更新基准")
    return 1 if fails else 0
