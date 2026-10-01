"""Movie Render Queue 影视级渲染设置：正式版（4K 2.35:1、16 次时间采样、EXR + ProRes 422 HQ + WAV）
和草稿版（HD、4 次采样、ProRes 422），外加一个渲染队列 Q_<素材>（草稿在前、正式在后）。
用法：改下面的 SEQ / MAP / 输出目录，然后
  UnrealEditor-Cmd <uproject> -run=pythonscript -script=mrq_setup.py   （工程需启用 MovieRenderPipeline、AppleProResMedia）
画幅要和相机胶片一致（2.35:1 → 36 × 15.32mm），否则会加黑边。"""
import unreal
L = lambda *a: unreal.log("@@ " + " ".join(str(x) for x in a))
EAL = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
DIR = "/Game/Cinematics/MRQ"
SEQ = "/Game/AIMocap/ring01/edit_1001_210635/LS_ring01_edit.LS_ring01_edit"
MAP = "/Game/AIMocap/ring01/L_ring01.L_ring01"
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


def make(name, res, temporal, exr, prores_codec, outdir):
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
    if exr:
        e = cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_EXR)
        e.compression = unreal.EXRCompressionFormat.PIZ
    pr = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAppleProResOutput)
    pr.codec = prores_codec
    pr.include_audio = True
    if hasattr(unreal, "MoviePipelineWaveOutput"):
        cfg.find_or_add_setting_by_class(unreal.MoviePipelineWaveOutput)
    EAL.save_loaded_asset(cfg)
    L("config", path, res, "temporal", temporal, "exr", exr, "settings", len(cfg.get_all_settings()))
    return cfg


final = make("MRQ_Final_4K_235", (3840, 1634), 16, True, unreal.AppleProResEncoderCodec.PRO_RES_422HQ, "G:/UE_Output/ring01/final")
draft = make("MRQ_Draft_HD_235", (1920, 817), 4, False, unreal.AppleProResEncoderCodec.PRO_RES_422, "G:/UE_Output/ring01/draft")
q = None
try:
    q = at.create_asset("Q_ring01", DIR, unreal.MoviePipelineQueue, None)
except Exception as ex:
    L("queue asset err", ex)
if q:
    for cfg, nm in ((draft, "ring01 草稿 HD"), (final, "ring01 正式 4K")):
        j = q.allocate_new_job(unreal.MoviePipelineExecutorJob)
        j.job_name = nm
        j.sequence = unreal.SoftObjectPath(SEQ)
        j.map = unreal.SoftObjectPath(MAP)
        j.set_configuration(cfg)
    EAL.save_loaded_asset(q)
    L("queue", q.get_path_name(), "jobs", len(q.get_jobs()))
