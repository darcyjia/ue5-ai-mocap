"""阶段 generate：用 Seedance 生成双人对拆视频（已有 input/video.mp4 则跳过）。
积分按实测单价估算，超过 [generate].max_credits 拒绝执行。"""
import time
import urllib.request
from pathlib import Path

from ..util import extract_json, file_sig, load_json, log, run as sh

# 实测单价（积分/秒，seedance2.5）：480p 15s=180，1080p 15s=960。720p 未实测，按中间值估。
COST_PER_SEC = {"480p": 12, "720p": 32, "1080p": 64}


def gen_cfg(c, cfg):
    """单段素材可在 input/generate.json 里覆盖分辨率、时长等（插件表单写这个文件）。"""
    return {**cfg["generate"], **(load_json(c.input / "generate.json", {}) or {})}


def estimate(cfg, resolution=None, duration=None):
    g = cfg["generate"]
    return COST_PER_SEC[resolution or g["resolution"]] * int(duration or g["duration"])


def params(c, cfg):
    return {"video": file_sig(c.video), "prompt": file_sig(c.prompt),
            "plate": file_sig(c.plate()) if c.plate() else None, **gen_cfg(c, cfg)}


def outputs(c, cfg):
    return [c.video]


def _cli(cfg, args, logfile=None):
    _, out = sh([cfg["paths"]["dreamina"], *args], logfile, check=False)
    return extract_json(out) or {}, out


NOT_LOGGED_IN = "未检测到有效登录态"


def credits(cfg, tries=4, wait=5):
    """查余额。读不到登录状态时等几秒重试：另一个进程（比如 OpenMontage）同时刷新 OAuth 令牌时，
    会偶发读到失效状态（2026-09-28 实测：从 UE 启动时失败，一分钟后同样环境正常）。"""
    for i in range(tries):
        j, out = _cli(cfg, ["user_credit"])
        if j.get("total_credit") is not None:
            return j["total_credit"]
        if i < tries - 1:
            log(f"读不到即梦登录状态，{wait}s 后重试（{i + 1}/{tries - 1}）：{out.strip()[:60]}")
            time.sleep(wait)
    return None


def _poll(cfg, sid, logdir, timeout=1800):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j, out = _cli(cfg, ["query_result", f"--submit_id={sid}"], logdir / f"query_{sid[:8]}.log")
        s = j.get("gen_status")
        if s == "success":
            return j
        if s == "fail":
            raise RuntimeError(f"生成失败：{j.get('fail_reason')}")
        time.sleep(20)
    raise TimeoutError(f"等待生成超时：{sid}")


def _download(url, dst):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dst)


def run_(c, cfg, args):
    g = gen_cfg(c, cfg)
    plate = c.plate()
    if not c.prompt.exists() or plate is None:
        raise SystemExit(f"没有 {c.video}，也缺少生成所需的 input/prompt.txt 或 input/plate.*")
    est = estimate(cfg, g["resolution"], g["duration"])
    if est > g["max_credits"]:
        raise SystemExit(f"预估 {est} 积分，超过 max_credits={g['max_credits']}，未执行")
    if not getattr(args, "allow_spend", False):
        raise SystemExit(f"生成视频要花约 {est} 积分（余额 {credits(cfg)}）。确认后加 --allow-spend 重跑")
    before = credits(cfg)
    if before is None:
        raise SystemExit("反复读不到即梦的登录状态，未提交任何任务（没有扣费）。稍后重试；"
                         "仍然不行就在终端运行 dreamina login 重新登录")
    log(f"生成视频：{g['model']} {g['resolution']} {g['duration']}s，预估 {est} 积分，当前余额 {before}")
    prompt = c.prompt.read_text(encoding="utf-8").strip()
    last = None
    for attempt in range(1 + g["retries"]):
        j, out = _cli(cfg, ["image2video", f"--image={plate}", f"--prompt={prompt}",
                            f"--model_version={g['model']}", f"--duration={g['duration']}",
                            f"--video_resolution={g['resolution']}", "--poll=0"], c.logs / "generate_submit.log")
        sid = j.get("submit_id")
        if not sid:
            raise RuntimeError("提交失败：\n" + out[-2000:])
        log(f"已提交 {sid}（第 {attempt + 1} 次）")
        try:
            r = _poll(cfg, sid, c.logs)
            url = r["result_json"]["videos"][0]["video_url"]
            _download(url, c.video)
            after = credits(cfg)
            log(f"已下载 {c.video}，余额 {before} → {after}")
            return {"submit_id": sid, "credits_before": before, "credits_after": after}
        except RuntimeError as ex:
            last = ex
            log(f"失败：{ex}")
    raise RuntimeError(f"生成失败（共 {1 + g['retries']} 次）：{last}")


def run(c, cfg, args):
    if c.video.exists() and not getattr(args, "regen", False):
        log(f"已有 {c.video.name}，不生成")
        return {"source": "existing"}
    return run_(c, cfg, args)


def make_plates(c, cfg, prompt_file, n=4, ratio="4:3"):
    """text2image 出构图板候选（maestro 会员 0 积分），存到 input/plates/，由你挑一张作为 plate。"""
    c.mk()
    d = c.input / "plates"
    d.mkdir(exist_ok=True)
    prompt = Path(prompt_file).read_text(encoding="utf-8").strip()
    j, out = _cli(cfg, ["text2image", f"--prompt={prompt}", "--model_version=5.0", f"--ratio={ratio}",
                        "--resolution_type=2k", f"--generate_num={n}", "--poll=180"], c.logs / "plates.log")
    imgs = (j.get("result_json") or {}).get("images") or []
    if not imgs:
        raise RuntimeError("没有拿到图片：\n" + out[-1500:])
    stamp = time.strftime("%H%M%S")
    for i, im in enumerate(imgs):
        _download(im["image_url"], d / f"plate_{stamp}_{i + 1}.jpg")
    log(f"{len(imgs)} 张候选在 {d}。挑一张后：python -m aimocap new {c.name} --plate <那张图>")
