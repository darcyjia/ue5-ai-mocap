"""用 SMPL-X 在 Blender 里还原多人动作 + 原机位相机。
blender -b --factory-startup --python build_blend.py -- --npz-dir D --out X.blend"""
import glob
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(__file__))
from common import PALETTE, SMPLX, args

A = args()
D = A["npz_dir"]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
com = np.load(os.path.join(D, "smplx_common.npz"))
faces, W, par = com["faces"], com["weights"], com["parents"]
cam_j = json.load(open(os.path.join(D, "camera.json")))

world = bpy.data.objects.new("SMPL_Yup_to_Zup", None)
sc.collection.objects.link(world)
world.rotation_euler = (math.radians(90), 0, 0)


def material(name, rgba):
    m = bpy.data.materials.new(name)
    m.diffuse_color = rgba
    return m


files = sorted(glob.glob(os.path.join(D, "p*.npz")))
L = 0
for k, f in enumerate(files):
    P = np.load(f)
    rv, rj, quat, tr = P["rest_verts"], P["rest_joints"], P["quat"].copy(), P["transl"]
    L = quat.shape[0]
    for t in range(1, L):                                   # 四元数符号连续
        flip = (quat[t] * quat[t - 1]).sum(-1) < 0
        quat[t][flip] *= -1
    ad = bpy.data.armatures.new(f"p{k}_rig")
    arm = bpy.data.objects.new(f"p{k}_rig", ad)
    sc.collection.objects.link(arm)
    arm.parent = world
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = []
    for i, n in enumerate(SMPLX):                           # 骨骼一律朝 +Y，静止矩阵为单位阵
        eb = ad.edit_bones.new(n)
        eb.head = rj[i].tolist()
        eb.tail = (rj[i] + np.array([0, 0.05, 0])).tolist()
        eb.roll = 0
        ebs.append(eb)
    for i, p in enumerate(par):
        if p >= 0:
            ebs[i].parent = ebs[p]
    bpy.ops.object.mode_set(mode="OBJECT")
    me = bpy.data.meshes.new(f"p{k}_body")
    me.from_pydata(rv.tolist(), [], faces.tolist())
    me.update()
    for poly in me.polygons:
        poly.use_smooth = True
    body = bpy.data.objects.new(f"p{k}_body", me)
    sc.collection.objects.link(body)
    body.parent = arm
    body.data.materials.append(material(f"p{k}_mat", PALETTE[k % len(PALETTE)]))
    for j, n in enumerate(SMPLX):
        vg = body.vertex_groups.new(name=n)
        for v in np.nonzero(W[:, j] > 1e-4)[0]:
            vg.add([int(v)], float(W[v, j]), "REPLACE")
    body.modifiers.new("Armature", "ARMATURE").object = arm
    pb = arm.pose.bones
    for b in pb:
        b.rotation_mode = "QUATERNION"
    for t in range(L):
        pb["pelvis"].location = tr[t].tolist()
        pb["pelvis"].keyframe_insert("location", frame=t + 1)
        for i in range(55):
            pb[SMPLX[i]].rotation_quaternion = quat[t, i].tolist()
            pb[SMPLX[i]].keyframe_insert("rotation_quaternion", frame=t + 1)

bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
bpy.context.active_object.name = "floor"
bpy.context.active_object.data.materials.append(material("floor_mat", (0.45, 0.45, 0.47, 1)))
cd = bpy.data.cameras.new("orig_cam")
cd.lens, cd.sensor_width, cd.sensor_fit = cam_j["lens"], 36, "HORIZONTAL"
cam = bpy.data.objects.new("orig_cam", cd)
sc.collection.objects.link(cam)
cam.parent = world
cam.matrix_basis = Matrix([list(r) + [p] for r, p in zip(cam_j["R"], cam_j["pos"])] + [[0, 0, 0, 1]])
sc.camera = cam
sc.render.fps = cam_j["fps"]
sc.frame_start, sc.frame_end = 1, L
sc.render.resolution_x, sc.render.resolution_y = cam_j["res"]
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.color_type = "MATERIAL"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.18, 0.18, 0.2)
bpy.ops.wm.save_as_mainfile(filepath=A["out"])
print("@@ saved", A["out"], "people", len(files), "frames", L)
