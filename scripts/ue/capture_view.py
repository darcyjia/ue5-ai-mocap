"""用 SceneCapture2D 从指定机位渲染一张 PNG（编辑器窗口不在前台也能出图）。
    capture_view.py <输出.png> x y z pitch yaw [fov] [宽] [高]"""
import os
import sys

import unreal


def main(a):
    out, x, y, z, pitch, yaw = a[0], *map(float, a[1:6])
    fov = float(a[6]) if len(a) > 6 else 40.0
    w, h = (int(a[7]), int(a[8])) if len(a) > 8 else (1600, 900)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    rt = unreal.RenderingLibrary.create_render_target2d(world, w, h, unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    cap = eas.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(x, y, z), unreal.Rotator(0, pitch, yaw))
    try:
        c = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
        c.set_editor_property("texture_target", rt)
        c.set_editor_property("fov_angle", fov)
        c.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_TONE_CURVE_HDR)
        c.set_editor_property("capture_every_frame", False)
        for _ in range(3):  # 前几次 Lumen/曝光没收敛
            c.capture_scene()
        d, f = os.path.split(os.path.abspath(out))
        unreal.RenderingLibrary.export_render_target(world, rt, d, f)
        print("saved", out)
    finally:
        cap.destroy_actor()


if __name__ == "__main__":
    main(sys.argv[1:])
