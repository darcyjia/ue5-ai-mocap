"""回归测试：对 tests/golden.json 里登记的素材，重跑 clean + qc（不重跑 GVHMR/UE），
与登记的指标比较。改了清理或质检代码后跑一遍，确认没有变差。
  python -m aimocap test            比较
  python -m aimocap test --update   把当前结果登记为基准"""
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
    fails = 0
    for name in list(g["clips"]):
        log(f"== 回归：{name}")
        run_stages(cfg, name, frm="clean", to="qc", force=True)
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
    if update:
        GOLDEN.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        log("已更新基准")
    return 1 if fails else 0
