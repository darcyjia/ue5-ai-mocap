"""把预演相机按剪辑表导出成 UE 坐标（给 UE 建镜头序列用）。
blender -b previz_cams.blend --python export_cams_ue.py -- --edl edl.json --out cameras_ue.json [--shots shots.json]
给了 --shots 时，同目录再写 dof.json（每个镜头：镜头中间那帧相机到对焦目标的距离 + 按焦距定的光圈），导入运镜时开景深。
Blender（Z 朝上、米）→ UE（Z 朝上、厘米、左手）：X 不变，Y 取反。相机朝向：Blender 相机看 -Z、上方 +Y；
UE 相机看 +X。输出每帧 位置(cm)、roll/pitch/yaw(度)，以及原机位相机的换算结果（用来和 UE 里的 OrigCam 对照）。"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(__file__))
from common import args

A = args()
E = json.load(open(A["edl"], encoding="utf-8"))
sc = bpy.context.scene


def to_ue(v):
    return Vector((v.x, -v.y, v.z))


def rotator(mw):
    """Blender 相机世界矩阵 → UE (roll, pitch, yaw) 度。"""
    R = mw.to_3x3()
    f = to_ue(R @ Vector((0, 0, -1))).normalized()
    u = to_ue(R @ Vector((0, 1, 0))).normalized()
    yaw = math.atan2(f.y, f.x)
    pitch = math.atan2(f.z, math.hypot(f.x, f.y))
    right0 = Vector((-math.sin(yaw), math.cos(yaw), 0))
    up0 = f.cross(right0)
    roll = -math.atan2(u.dot(right0), u.dot(up0))
    return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]


def cam_at(obj, frame):
    sc.frame_set(frame)
    mw = obj.matrix_world
    return [round(x * 100, 3) for x in to_ue(mw.translation)], [round(x, 4) for x in rotator(mw)]


out = {"fps": E["fps"], "film_frames": E["film_frames"], "aspect": E.get("aspect", 16 / 9), "shots": []}
for s in E["shots"]:
    cam = bpy.data.objects[s["camera"]]
    a, b = s["key_frames"]
    keys = [cam_at(cam, f) for f in range(a, b + 1)]
    out["shots"].append({**s, "loc": [k[0] for k in keys], "rot": [k[1] for k in keys]})
oc = bpy.data.objects["orig_cam"]
out["orig_cam"] = {"loc": cam_at(oc, 1)[0], "rot": cam_at(oc, 1)[1], "lens": oc.data.lens}
json.dump(out, open(A["out"], "w", encoding="utf-8"), ensure_ascii=False)
print("@@ shots", len(out["shots"]), "orig_cam", json.dumps(out["orig_cam"]))

BONE = {"chest": "spine_05", "head": "head"}


def bone_pos(k, part, frame):
    sc.frame_set(frame)
    r = bpy.data.objects[f"p{k}_rig"]
    return r.matrix_world @ r.pose.bones[BONE[part]].head


def focus_target(sh, frame):
    """镜头表里的对焦目标 → Blender 世界坐标：mid = 两人胸口中点；p0 / p1 = 胸口；p0head = 头；过肩镜头对准被看的人的头。"""
    if sh.get("kind") == "ots":
        return bone_pos(int(sh["to"][1]), "head", frame), f"ots {sh['frm']}->{sh['to']}"
    t = sh.get("target", "mid")
    if t == "mid":
        return (bone_pos(0, "chest", frame) + bone_pos(1, "chest", frame)) / 2, t
    return bone_pos(int(t[1]), "head" if t.endswith("head") else "chest", frame), t


if A.get("shots"):
    SH = {s["id"]: s for s in json.load(open(A["shots"], encoding="utf-8"))["shots"]}
    dof = {}
    for s in E["shots"]:
        sh = SH.get(s["id"])
        if not sh:
            continue
        cam = bpy.data.objects[s["camera"]]
        a, b = s["anim_frames"]
        ds = []
        for f in sorted({a, (a + b) // 2, b}):
            tg, label = focus_target(sh, f)
            sc.frame_set(f)
            ds.append((cam.matrix_world.translation - tg).length * 100)
        lens = s["lens"]
        dof[s["id"]] = {"lens": lens, "focus_cm": round(sorted(ds)[len(ds) // 2], 1),
                        "focus_range_cm": [round(min(ds)), round(max(ds))],
                        "fstop": 2.8 if lens >= 45 else (4.0 if lens >= 30 else 5.6), "target": label, "desc": s["desc"]}
    p = os.path.join(os.path.dirname(A["out"]), "dof.json")
    json.dump(dof, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("@@ dof", len(dof), p)
