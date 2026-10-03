"""生成无缝环形背景（cyclorama）网格：剖面“地板边缘 → 1/4 圆弧墙脚 → 直墙”绕 Z 轴旋转，外加顶盖，导出 FBX 给 UE。

    blender -b -P make_cyc.py -- <out.fbx> --radius 22 --height 20 --cove 3 --gap 200,290 [--segments 180]

单位：米（导出 FBX 后 UE 里是厘米）。缺口角度用 UE 偏航角（度）。UE 的 Y = −Blender Y，所以角度在这里取反。
法线朝里（朝圆心/朝下），平滑着色，墙和顶是同一个材质槽 M_Cyc。"""
import argparse
import math
import sys

import bmesh
import bpy


def args():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--radius", type=float, default=22.0)
    ap.add_argument("--height", type=float, default=20.0)
    ap.add_argument("--cove", type=float, default=3.0)
    ap.add_argument("--gap", default="200,290")
    ap.add_argument("--segments", type=int, default=180)
    return ap.parse_args(sys.argv[sys.argv.index("--") + 1:])


def main():
    a = args()
    g0, g1 = (float(v) for v in a.gap.split(","))
    span = (g0 - g1) % 360 or 360
    R, H, rc = a.radius, a.height, a.cove
    # 剖面 (r, z)：圆弧 12 段 + 直墙
    prof = [(R - rc + rc * math.sin(t), rc - rc * math.cos(t)) for t in
            (k / 12 * math.pi / 2 for k in range(13))]
    prof.append((R, H))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    me = bpy.data.meshes.new("Cyc")
    bm = bmesh.new()
    rings = []
    n = max(2, int(a.segments * span / 360))
    for i in range(n + 1):
        ue_yaw = math.radians(g1 + span * i / n)
        ang = -ue_yaw                                   # UE → Blender：Y 取反等于角度取反
        rings.append([bm.verts.new((r * math.cos(ang), r * math.sin(ang), z)) for r, z in prof])
    for i in range(n):
        for j in range(len(prof) - 1):
            bm.faces.new((rings[i][j], rings[i][j + 1], rings[i + 1][j + 1], rings[i + 1][j]))
    # 顶盖：在墙顶高度封住（只盖墙这一侧的扇形 + 缺口也盖上，仰拍任何方向都不见黑）
    c = bm.verts.new((0, 0, H))
    top = [bm.verts.new((R * math.cos(-math.radians(k * 5)), R * math.sin(-math.radians(k * 5)), H)) for k in range(72)]
    for k in range(72):
        bm.faces.new((c, top[k], top[(k + 1) % 72]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("SM_Cyc", me)
    bpy.context.scene.collection.objects.link(ob)
    # 法线朝里（朝圆心 / 朝下）
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(bpy.data.materials.new("M_Cyc"))
    bpy.ops.export_scene.fbx(filepath=a.out, use_selection=True, object_types={"MESH"}, mesh_smooth_type="FACE",
                             apply_unit_scale=True, bake_space_transform=True)
    print(f"[cyc] R={R}m H={H}m cove={rc}m 墙 {span:.0f}°（缺口 {g0:.0f}–{g1:.0f}）{n} 段 → {a.out}")


main()
