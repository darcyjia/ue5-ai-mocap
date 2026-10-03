"""在开着的编辑器里完成 ue 阶段（导入 FBX → 重定向到 MetaHuman → 表情/声音 → 关卡序列），不弹任何对话框。
和插件菜单「导入」走同一套代码（ue_pipeline.run_job），供 scripts/tools/ue_remote.py 远程调用：

    python scripts/tools/ue_remote.py --project <工程> file scripts/ue/ue_finish_remote.py <素材>
    python scripts/tools/ue_remote.py --project <工程> file scripts/ue/ue_finish_remote.py <素材> edit   # 导入运镜（同插件「导入运镜」）
"""
import importlib
import json
import sys
from pathlib import Path

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


def edit(clip):
    """导入 Blender 运镜：每个镜头一个子序列 + 表演副本，返回成片序列路径。相机文件按 input/ue.json 里当前工程的 cameras。"""
    import ue_edit
    importlib.reload(ue_edit)
    folder = core.clip_dir(clip)
    proj = Path(unreal.Paths.get_project_file_path()).stem
    uej = folder / "input" / "ue.json"
    ov = (json.loads(uej.read_text(encoding="utf-8")) if uej.exists() else {}).get(proj, {})
    cams = folder / ov.get("cameras", "blender/cameras_ue.json")
    cd = f"{core.config()['ue']['content_root']}/{clip}"
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(f"{cd}/L_{clip}")
    seq = ue_edit.import_edit(str(folder), cd, clip, cams=str(cams), log=lambda *a: print("[edit]", *a),
                              step=lambda m: print(f"[edit] {m}"))
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)
    print(f"成片序列 {seq.get_path_name()}")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "edit":
        edit(sys.argv[1])
    else:
        main(sys.argv[1])
