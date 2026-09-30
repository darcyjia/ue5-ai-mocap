"""运镜预演场景：两个 MetaHuman（UE 导出的身体/衣服/脸网格 + 重定向后的动画）+ 擂台 + 原机位参考相机。
blender -b --factory-startup --python previz_mh.py -- --clip-dir <aimocap_work/素材> --out X.blend
UE→FBX→Blender 与我们导出的 FBX 坐标一致（Z 朝上、米、原点在地面），原机位相机沿用 camera.json。
脸：刚性挂到身体的 head 骨（预演只看构图，不带表情），删掉几百个表情变形减重。头发（groom）导不出来，不带。"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(__file__))
from common import args

A = args()
C = A["clip_dir"]
EXP = os.path.join(C, "ue", "export")
cam_j = json.load(open(os.path.join(C, "clean", "camera.json")))
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
COLORS = [(0.15, 0.3, 0.85, 1), (0.25, 0.6, 0.2, 1)]


def imp(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path, use_anim=True, ignore_leaf_bones=False, automatic_bone_orientation=False)
    return [o for o in bpy.data.objects if o not in before]


def mat(name, rgba):
    m = bpy.data.materials.new(name)
    m.diffuse_color = rgba
    return m


CM = Matrix.Scale(0.01, 4)                          # UE 导出的 FBX 是厘米


def lod0(objs):
    """一个网格 FBX 会带所有 LOD：只留 LOD0，其余和导入产生的空物体一起删掉。"""
    meshes = [o for o in objs if o.type == "MESH"]
    keep = next((o for o in meshes if "LOD0" in o.name), meshes[0] if meshes else None)
    for o in objs:
        if (o.type == "MESH" and o is not keep) or o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    return keep


people, L = [], 0
for k in range(2):
    man = json.load(open(os.path.join(EXP, f"meshes_p{k}.json"), encoding="utf-8"))
    new = imp(man["meshes"]["body"])
    rig = next(o for o in new if o.type == "ARMATURE")
    rig.name = f"p{k}_rig"
    rig.parent = None                               # 导入时外面多包一层 0.01 的空物体，会缩两次
    rig.matrix_world = CM
    body = lod0([o for o in new if o is not rig])
    body.name = f"p{k}_body"
    body.data.materials.clear()
    body.data.materials.append(mat(f"p{k}_skin", COLORS[k]))
    anim = imp(man["anim"])
    arig = next(o for o in anim if o.type == "ARMATURE")
    act = arig.animation_data.action
    act.name = f"p{k}_{man['bp']}"
    rig.animation_data_create()
    rig.animation_data.action = act
    if getattr(act, "slots", None):              # Blender 4.4+ 的分槽动作：不指定槽位动画不生效
        rig.animation_data.action_slot = act.slots[0]
    for o in anim:
        bpy.data.objects.remove(o, do_unlink=True)
    L = max(L, int(act.frame_range[1]))
    for key, path in man["meshes"].items():
        if key == "body":
            continue
        objs = imp(path)
        rest = [x for x in objs if x.type != "ARMATURE"]
        for x in objs:
            if x.type == "ARMATURE":
                bpy.data.objects.remove(x, do_unlink=True)
        o = lod0(rest)
        if o is None:
            continue
        o.name = f"p{k}_{key}"
        if o.data.shape_keys:
            o.shape_key_clear()
        for m in list(o.modifiers):
            o.modifiers.remove(m)
        o.parent = None
        o.matrix_world = CM
        if key == "face":                          # 静止姿态下对齐，刚性挂到 head 骨
            rig.data.pose_position = "REST"
            bpy.context.view_layer.update()
            o.parent, o.parent_type, o.parent_bone = rig, "BONE", "head"
            bpy.context.view_layer.update()
            o.matrix_world = CM
            rig.data.pose_position = "POSE"
        else:                                       # 衣服：同一套骨架蒙皮
            o.parent = rig
            o.matrix_world = CM
            o.modifiers.new("Armature", "ARMATURE").object = rig
        o.data.materials.clear()
        o.data.materials.append(mat(f"p{k}_{key}_m", (0.8, 0.68, 0.58, 1) if key == "face" else COLORS[k]))
    people.append(rig)

sc.render.fps = int(cam_j["fps"])
sc.frame_start, sc.frame_end = 1, L
# 活动范围（骨盆轨迹）→ 擂台
xs, ys = [], []
for f in range(1, L + 1, 4):
    sc.frame_set(f)
    for rig in people:
        p = rig.matrix_world @ rig.pose.bones["pelvis"].matrix.translation
        xs.append(p.x)
        ys.append(p.y)
cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
ext = max(max(xs) - min(xs), max(ys) - min(ys))
size = max(12.0, math.ceil((ext + 5.0) / 2) * 2)          # 武道会擂台要显得开阔：至少 12 米
bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, -0.5))
ring = bpy.context.active_object
ring.name, ring.scale = "ring", (size, size, 1.0)
ring.data.materials.append(mat("ring_m", (0.62, 0.6, 0.55, 1)))
bpy.ops.mesh.primitive_plane_add(size=80, location=(cx, cy, -1.0))
bpy.context.active_object.name = "arena_ground"
bpy.context.active_object.data.materials.append(mat("ground_m", (0.3, 0.33, 0.3, 1)))
info = {"center": [round(cx, 3), round(cy, 3)], "extent_m": round(ext, 2), "ring_size_m": size, "ring_height_m": 1.0,
        "x_range": [round(min(xs), 2), round(max(xs), 2)], "y_range": [round(min(ys), 2), round(max(ys), 2)], "frames": L}
# 原机位参考相机
cd = bpy.data.cameras.new("orig_cam")
cd.lens, cd.sensor_width, cd.sensor_fit = cam_j["lens"], 36, "HORIZONTAL"
cam = bpy.data.objects.new("orig_cam", cd)
sc.collection.objects.link(cam)
cam.matrix_world = Matrix.Rotation(math.radians(90), 4, "X") @ Matrix([list(r) + [p] for r, p in zip(cam_j["R"], cam_j["pos"])] + [[0, 0, 0, 1]])
sc.camera = cam
sc.render.resolution_x, sc.render.resolution_y = cam_j["res"]
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.color_type = "MATERIAL"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.2, 0.2, 0.22)
json.dump(info, open(os.path.join(C, "blender", "ring.json"), "w"), indent=1)
bpy.ops.wm.save_as_mainfile(filepath=A["out"])
print("@@ ring", json.dumps(info))
print("@@ saved", A["out"])
