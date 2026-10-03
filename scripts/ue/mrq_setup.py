"""Movie Render Queue 影视级渲染设置（输出 H.265 mp4，不留序列帧）：正式版（标准 1920×1080，2.35:1 画面上下黑边，16 次时间采样、EXR + ProRes 422 HQ + WAV）
和草稿版（HD、4 次采样、ProRes 422），外加一个渲染队列 Q_<素材>（草稿在前、正式在后）。
用法：mrq_setup.py [<成片序列> <关卡> <素材名>]（不给参数就是 ring01 那套），命令行 commandlet 或编辑器里（ue_remote.py）都行：
  UnrealEditor-Cmd <uproject> -run=pythonscript -script="mrq_setup.py <SEQ> <MAP> <clip>"   （工程需启用 MovieRenderPipeline、AppleProResMedia）
输出到 G:/UE_Output/<素材>/final 和 draft；给了素材名时配置资产名带 _<素材> 后缀，不同素材互不覆盖。
相机胶片 2.35:1（36 × 15.32mm）且开着约束宽高比，输出 16:9 时上下自动黑边。"""
import sys

import unreal
L = lambda *a: unreal.log("@@ " + " ".join(str(x) for x in a))
EAL = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
DIR = "/Game/Cinematics/MRQ"
ARGS = [a for a in sys.argv[1:] if a]
SEQ, MAP, CLIP = ARGS[:3] if len(ARGS) >= 3 else (
    "/Game/AIMocap/ring01/edit_1001_210635/LS_ring01_edit.LS_ring01_edit", "/Game/AIMocap/ring01/L_ring01.L_ring01", "ring01")
SUF = f"_{CLIP}" if len(ARGS) >= 3 else ""
CVARS = {
    "r.MotionBlurQuality": 4, "r.MotionBlurSeparable": 1, "r.MotionBlur.Max": -1,
    "r.DepthOfFieldQuality": 4, "r.BloomQuality": 5, "r.Tonemapper.Quality": 5,
    "r.SSS.Quality": 1, "r.SSS.HalfRes": 0,                                   # MetaHuman 皮肤次表面
    "r.ShadowQuality": 5,
    "r.Shadow.Virtual.SMRT.RayCountDirectional": 16, "r.Shadow.Virtual.SMRT.SamplesPerRayDirectional": 16,
    "r.Shadow.Virtual.SMRT.RayCountLocal": 16, "r.Shadow.Virtual.SMRT.SamplesPerRayLocal": 16,
    "r.Lumen.ScreenProbeGather.DownsampleFactor": 8, "r.Lumen.Reflections.DownsampleFactor": 1,
    "r.HairStrands.Visibility.MSAA.SamplePerPixel": 8,                        # MetaHuman 头发
    "r.ScreenPercentage": 100, "r.ViewDistanceScale": 50,
}


def make(name, res, temporal, quality, outdir):
    path = f"{DIR}/{name}"
    if EAL.does_asset_exist(path):
        cfg = unreal.load_asset(path)
    else:
        cfg = at.create_asset(name, DIR, unreal.MoviePipelinePrimaryConfig, unreal.MoviePipelinePrimaryConfigFactory())
    o = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    o.output_directory = unreal.DirectoryPath(outdir)
    o.output_resolution = unreal.IntPoint(*res)
    o.file_name_format = "{sequence_name}.{frame_number}"
    o.zero_pad_frame_numbers = 4
    o.override_existing_output = True
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.spatial_sample_count = 1
    aa.temporal_sample_count = temporal                       # 子帧累积：运动模糊和细节都更干净
    aa.override_anti_aliasing = True
    aa.anti_aliasing_method = unreal.AntiAliasingMethod.AAM_NONE
    aa.engine_warm_up_count = 32                              # 每个镜头开拍前预热：Lumen / 毛发 / 运动模糊先稳定
    aa.render_warm_up_count = 32
    aa.use_camera_cut_for_warm_up = False
    g = cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    g.cinematic_quality_settings = True
    g.texture_streaming = unreal.MoviePipelineTextureStreamingMethod.FULLY_LOAD
    g.use_lod_zero = True
    g.disable_hlods = True
    g.use_high_quality_shadows = True
    g.override_view_distance_scale = True
    g.view_distance_scale = 50
    cv = cfg.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
    for k, v in CVARS.items():
        cv.add_or_update_console_variable(k, float(v))
    for cls in (unreal.MoviePipelineImageSequenceOutput_EXR, unreal.MoviePipelineAppleProResOutput):
        old = cfg.find_setting_by_class(cls)
        if old:
            cfg.remove_setting(old)
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)   # 中间帧，编码成 H.265 后删除
    enc = cfg.find_or_add_setting_by_class(unreal.MoviePipelineCommandLineEncoder)
    enc.set_editor_property("quality", quality)
    enc.set_editor_property("delete_source_files", True)
    if hasattr(unreal, "MoviePipelineWaveOutput"):
        cfg.find_or_add_setting_by_class(unreal.MoviePipelineWaveOutput)
    EAL.save_loaded_asset(cfg, only_if_is_dirty=False)   # 直接改属性不会标脏，默认会跳过保存
    L("config", path, res, "temporal", temporal, "quality", quality, "settings", len(cfg.get_all_settings()))
    return cfg


final = make(f"MRQ_Final_1080p_235{SUF}", (1920, 1080), 16, unreal.MoviePipelineEncodeQuality.EPIC, f"G:/UE_Output/{CLIP}/final")
draft = make(f"MRQ_Draft_HD_235{SUF}", (1920, 1080), 4, unreal.MoviePipelineEncodeQuality.HIGH, f"G:/UE_Output/{CLIP}/draft")
q = None
try:
    q = unreal.load_asset(f"{DIR}/Q_{CLIP}") or at.create_asset(f"Q_{CLIP}", DIR, unreal.MoviePipelineQueue, None)
except Exception as ex:
    L("queue asset err", ex)
if q:
    for j in list(q.get_jobs()):
        q.delete_job(j)
    for cfg, nm in ((draft, f"{CLIP} 草稿 HD"), (final, f"{CLIP} 正式 1080p")):
        j = q.allocate_new_job(unreal.MoviePipelineExecutorJob)
        j.job_name = nm
        j.sequence = unreal.SoftObjectPath(SEQ)
        j.map = unreal.SoftObjectPath(MAP)
        j.set_configuration(cfg)
    EAL.save_loaded_asset(q, only_if_is_dirty=False)
    L("queue", q.get_path_name(), "jobs", len(q.get_jobs()))
