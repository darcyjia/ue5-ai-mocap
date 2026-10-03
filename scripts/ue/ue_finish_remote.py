"""在开着的编辑器里完成 ue 阶段（导入 FBX → 重定向到 MetaHuman → 表情/声音 → 关卡序列），不弹任何对话框。
和插件菜单「导入」走同一套代码（ue_pipeline.run_job），供 scripts/tools/ue_remote.py 远程调用：

    python scripts/tools/ue_remote.py --project <工程> file scripts/ue/ue_finish_remote.py <素材>
"""
import importlib
import sys

import unreal
from aimocap_ue import core


def main(clip):
    import ue_pipeline
    importlib.reload(ue_pipeline)
    job = core.cli_json(["uejob", clip])
    res = ue_pipeline.run_job(job, step=lambda m: print(f"[ue] {m}"))
    core.cli(["mark", clip, "ue"])
    core.cli(["run", clip, "--only", "qc"])
    for r in res["persons"]:
        print(f"p{r['p']}：躯干误差 {r['torso_err_mean']:+.1f}°，头部 {r['head_err_mean']:+.1f}°，手臂 {r['arm_err_mean']:.1f}°")
    print(f"两人间距比 {res.get('spacing_ratio_median')}（水平缩放 {res['horizontal_scale']}）")
    print(f"关卡 {res.get('level')}\n序列 {res['sequence']}")
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(unreal.load_asset(res["sequence"]))


if __name__ == "__main__":
    main(sys.argv[1])
