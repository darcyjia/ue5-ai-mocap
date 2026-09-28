"""表单：用 Python 定义的 UObject，在 UE 自带的属性面板对话框里编辑（带文件选择和资产选择器）。
上次填的内容存在 <工程>/Saved/AIMocap/last.json。"""
import json
from pathlib import Path

import unreal


@unreal.uenum()
class AIMocapSource(unreal.EnumBase):
    EXISTING_VIDEO = unreal.uvalue(0, meta={"DisplayName": "已有视频"})
    GENERATE = unreal.uvalue(1, meta={"DisplayName": "用提示词生成（花积分，会先确认）"})


@unreal.uenum()
class AIMocapResolution(unreal.EnumBase):
    R480 = unreal.uvalue(0, meta={"DisplayName": "480p（约 12 积分/秒，做动捕够用）"})
    R720 = unreal.uvalue(1, meta={"DisplayName": "720p（约 32 积分/秒，估算）"})
    R1080 = unreal.uvalue(2, meta={"DisplayName": "1080p（约 64 积分/秒）"})


RES_NAME = {0: "480p", 1: "720p", 2: "1080p"}


@unreal.uclass()
class AIMocapNewJob(unreal.Object):
    # 注意：UE 属性面板按声明的【逆序】显示，所以这里从 5 写到 1
    blender_preview = unreal.uproperty(bool, meta={"Category": "5 选项", "DisplayName": "生成 Blender 预览三联画",
                                                   "ToolTip": "多约 3 分钟；质检报告里会带这段视频"})
    right_character = unreal.uproperty(unreal.Blueprint, meta={"Category": "4 角色", "DisplayName": "画面右边的人"})
    left_character = unreal.uproperty(unreal.Blueprint, meta={"Category": "4 角色", "DisplayName": "画面左边的人",
                                                              "ToolTip": "MetaHuman 蓝图（BP_xxx）"})
    duration = unreal.uproperty(int, meta={"Category": "3 用提示词生成", "DisplayName": "时长（秒）",
                                           "ClampMin": "4", "ClampMax": "30"})
    resolution = unreal.uproperty(AIMocapResolution, meta={"Category": "3 用提示词生成", "DisplayName": "分辨率"})
    plate_image = unreal.uproperty(unreal.FilePath, meta={"Category": "3 用提示词生成", "DisplayName": "构图板图片",
                                                          "FilePathFilter": "jpg",
                                                          "ToolTip": "锁定机位和构图的首帧；可先用「出构图板候选」免费生成"})
    prompt_file = unreal.uproperty(unreal.FilePath, meta={"Category": "3 用提示词生成", "DisplayName": "编排提示词（txt）",
                                                          "FilePathFilter": "txt"})
    video = unreal.uproperty(unreal.FilePath, meta={"Category": "2 已有视频", "DisplayName": "视频文件",
                                                    "FilePathFilter": "mp4", "ToolTip": "来源选「已有视频」时填"})
    source = unreal.uproperty(AIMocapSource, meta={"Category": "1 素材", "DisplayName": "来源"})
    clip_name = unreal.uproperty(str, meta={"Category": "1 素材", "DisplayName": "素材名",
                                            "ToolTip": "英文、数字、下划线。工作目录和 UE 资产都用这个名字"})


@unreal.uclass()
class AIMocapRedo(unreal.Object):
    # 逆序声明（UE 属性面板倒着显示）
    right_character = unreal.uproperty(unreal.Blueprint, meta={"Category": "角色", "DisplayName": "画面右边的人"})
    left_character = unreal.uproperty(unreal.Blueprint, meta={"Category": "角色", "DisplayName": "画面左边的人"})
    clip_folder = unreal.uproperty(unreal.DirectoryPath, meta={"Category": "素材", "DisplayName": "素材目录",
                                                               "ToolTip": "aimocap_work 下的某个素材文件夹"})


@unreal.uclass()
class AIMocapPlates(unreal.Object):
    count = unreal.uproperty(int, meta={"Category": "构图板", "DisplayName": "张数", "ClampMin": "1", "ClampMax": "10"})
    prompt_file = unreal.uproperty(unreal.FilePath, meta={"Category": "构图板", "DisplayName": "构图板提示词（txt）",
                                                          "FilePathFilter": "txt"})
    clip_name = unreal.uproperty(str, meta={"Category": "构图板", "DisplayName": "素材名"})


@unreal.uclass()
class AIMocapPickClip(unreal.Object):
    clip_folder = unreal.uproperty(unreal.DirectoryPath, meta={"Category": "素材", "DisplayName": "素材目录"})


# ---------------- 记住上次填写的内容 ----------------
def _last_path():
    return Path(unreal.Paths.project_saved_dir()) / "AIMocap" / "last.json"


def load_last():
    p = _last_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_last(d):
    p = _last_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = load_last()
    cur.update(d)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def fp(path):
    return unreal.FilePath(file_path=path or "")


def dp(path):
    return unreal.DirectoryPath(path=path or "")


def bp(path):
    return unreal.load_asset(path) if path and unreal.EditorAssetLibrary.does_asset_exist(path) else None


def asset_path(obj):
    return obj.get_path_name().split(".")[0] if obj else None


def show(title, obj):
    """模态属性面板对话框，点确定返回 True。"""
    opts_cls = getattr(unreal, "EditorDialogLibraryObjectDetailsViewOptions", None)
    if opts_cls:
        opts = opts_cls()
        for k, v in (("show_object_name", False), ("allow_search", False), ("min_width", 560), ("min_height", 420)):
            try:
                opts.set_editor_property(k, v)
            except Exception:
                pass
        return unreal.EditorDialog.show_object_details_view(title, obj, opts)
    return unreal.EditorDialog.show_object_details_view(title, obj)
