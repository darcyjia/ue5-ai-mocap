"""把预演相机按剪辑表导出成 UE 坐标（给 UE 建镜头序列用）。
blender -b previz_cams.blend --python export_cams_ue.py -- --edl edl.json --out cameras_ue.json
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


out = {"fps": E["fps"], "film_frames": E["film_frames"], "shots": []}
for s in E["shots"]:
    cam = bpy.data.objects[s["camera"]]
    a, b = s["key_frames"]
    keys = [cam_at(cam, f) for f in range(a, b + 1)]
    out["shots"].append({**s, "loc": [k[0] for k in keys], "rot": [k[1] for k in keys]})
oc = bpy.data.objects["orig_cam"]
out["orig_cam"] = {"loc": cam_at(oc, 1)[0], "rot": cam_at(oc, 1)[1], "lens": oc.data.lens}
json.dump(out, open(A["out"], "w", encoding="utf-8"), ensure_ascii=False)
print("@@ shots", len(out["shots"]), "orig_cam", json.dumps(out["orig_cam"]))
