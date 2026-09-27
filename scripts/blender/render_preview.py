"""渲染原机位和斜上方 3/4 机位的 PNG 序列。
blender -b X.blend --python render_preview.py -- --out-dir D"""
import math
import os
import sys

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, os.path.dirname(__file__))
from common import args

A = args()
sc = bpy.context.scene
rigs = [o for o in bpy.data.objects if o.name.endswith("_rig")]
pts = []
for f in range(1, sc.frame_end + 1, 30):
    sc.frame_set(f)
    for arm in rigs:
        pts.append(arm.matrix_world @ arm.pose.bones["pelvis"].head)
mid = sum(pts, Vector()) / len(pts)
orig = bpy.data.objects["orig_cam"]
fwd = orig.matrix_world.to_3x3() @ Vector((0, 0, -1))
fwd.z = 0
fwd.normalize()
tgt = Vector((mid.x, mid.y, 0.9))
back = -fwd
back.rotate(Euler((0, 0, math.radians(60))))              # 从原机位方向绕竖轴转 60°、俯 25°、距 6 m
el = math.radians(25)
d = Vector((back.x * math.cos(el), back.y * math.cos(el), math.sin(el)))
sd = bpy.data.cameras.new("side_cam")
sd.lens = 50
side = bpy.data.objects.new("side_cam", sd)
sc.collection.objects.link(side)
side.location = tgt + d * 6.0
side.rotation_euler = (tgt - side.location).to_track_quat("-Z", "Y").to_euler()
sc.render.image_settings.file_format = "PNG"
for cam, sub in ((orig, "anim_orig"), (side, "anim_side")):
    sc.camera = cam
    sc.render.filepath = os.path.join(A["out_dir"], sub, "f_")
    bpy.ops.render.render(animation=True)
    print("@@ rendered", sub)
