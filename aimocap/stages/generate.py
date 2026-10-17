"""阶段 generate：用 Seedance 生成动捕源视频（已有 input/video.mp4 则跳过）。
有 input/music.*（舞蹈）时走全能参考 multimodal2video：构图板 + 配乐，动作跟着音乐；否则 image2video。
积分按实测单价估算，超过 [generate].max_credits 拒绝执行。"""
import time
import urllib.request
from pathlib import Path

from ..util import extract_json, file_sig, load_json, log, run as sh

# 实测单价（积分/秒，seedance2.5）：480p 15s=180，1080p 15s=960。720p 未实测，按中间值估。
COST_PER_SEC = {"480p": 12, "720p": 32, "1080p": 64}
# 全能参考（multimodal2video，seedance2.5）：480p 15s 图+配乐=100（10-15 dance_01）；带参考视频 480p 15s=270（09-24）；
# 720p 15s=300 / 25s=500（图片参考）。1080p 未实测。这里只用于图+配乐，按 7/s 估（略高于实测）。
COST_PER_SEC_MM = {"480p": 7, "720p": 20, "1080p": 64}
RATIOS = {"1:1": 1.0, "3:4": 0.75, "16:9": 16 / 9, "4:3": 4 / 3, "9:16": 9 / 16, "21:9": 21 / 9}
MUSIC_EXT = (".wav", ".mp3", ".flac", ".m4a")
# 带参考视频（动作迁移）480p 15s = 270（09-24 实测）
COST_PER_SEC_REF = {"480p": 18, "720p": 32, "1080p": 64}


def ref_video(c):
    """input/ref.mp4：动作参考视频（全能参考 @视频1，Seedance 把动作迁移到构图板的人身上）。"""
    for ext in (".mp4", ".mov", ".webm"):
        p = c.input / f"ref{ext}"
        if p.exists():
            return p
    return None


def music(c):
    for ext in MUSIC_EXT:
        p = c.input / f"music{ext}"
        if p.exists():
            return p
    return None


def plate_ratio(plate):
    """multimodal2video 不跟随首帧比例（默认 16:9），按构图板宽高比取最接近的一档。"""
    from PIL import Image
    with Image.open(plate) as im:
        a = im.width / im.height
    return min(RATIOS, key=lambda k: abs(RATIOS[k] - a))


def gen_cfg(c, cfg):
    """单段素材可在 input/generate.json 里覆盖分辨率、时长等（插件表单写这个文件）。"""
    return {**cfg["generate"], **(load_json(c.input / "generate.json", {}) or {})}


def estimate(cfg, resolution=None, duration=None, multimodal=False, ref=False):
    g = cfg["generate"]
    table = COST_PER_SEC_REF if ref else COST_PER_SEC_MM if multimodal else COST_PER_SEC
    return table[resolution or g["resolution"]] * int(duration or g["duration"])


def params(c, cfg):
    return {"video": file_sig(c.video), "prompt": file_sig(c.prompt),
            "plate": file_sig(c.plate()) if c.plate() else None,
            "music": file_sig(music(c)) if music(c) else None,
            "ref": file_sig(ref_video(c)) if ref_video(c) else None, **gen_cfg(c, cfg)}


def outputs(c, cfg):
    return [c.video]


def _cli(cfg, args, logfile=None):
    from ..dreamina import INSTALL_HINT, exe
    path = exe(cfg)
    if path is None:
        raise SystemExit(INSTALL_HINT)
    _, out = sh([path, *args], logfile, check=False)
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


def _download(url, dst, tries=4):
    """先下到 .part，大小和 Content-Length 一致才改名。2026-09-30 实测：下载中途断开，
    urlretrieve 抛错但留下 1MB 的残缺 video.mp4，下次运行会误以为视频已存在。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
                size = int(r.headers.get("Content-Length") or 0)
                f.write(r.read())
            if size and tmp.stat().st_size != size:
                raise IOError(f"只下载到 {tmp.stat().st_size}/{size} 字节")
            tmp.replace(dst)
            return
        except Exception as ex:
            last = ex
            log(f"下载失败（{i + 1}/{tries}）：{ex}")
            time.sleep(5)
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"下载失败：{last}")


def run_(c, cfg, args):
    g = gen_cfg(c, cfg)
    plate = c.plate()
    if not c.prompt.exists() or plate is None:
        raise SystemExit(f"没有 {c.video}，也缺少生成所需的 input/prompt.txt 或 input/plate.*")
    mus, ref = music(c), ref_video(c)
    est = estimate(cfg, g["resolution"], g["duration"], multimodal=bool(mus or ref), ref=ref is not None)
    if est > g["max_credits"]:
        raise SystemExit(f"预估 {est} 积分，超过 max_credits={g['max_credits']}，未执行")
    if not getattr(args, "allow_spend", False):
        raise SystemExit(f"生成视频要花约 {est} 积分（余额 {credits(cfg)}）。确认后加 --allow-spend 重跑")
    before = credits(cfg)
    if before is None:
        raise SystemExit("还没连接即梦（或登录已过期），未提交任何任务（没有扣费）。\n"
                         "解决：UE 菜单「AI 动捕 → 即梦账号 / 连接…」，或在普通终端运行 python -m aimocap dreamina login，"
                         "用抖音扫码授权。\n"
                         "注意：在 Claude 桌面应用（MSIX）里登录的令牌会被隔离，UE 和普通终端看不到。")
    log(f"生成视频：{g['model']} {g['resolution']} {g['duration']}s{'（配乐 ' + mus.name + '）' if mus else ''}，"
        f"预估 {est} 积分，当前余额 {before}")
    prompt = c.prompt.read_text(encoding="utf-8").strip()
    if mus or ref:
        cli_args = ["multimodal2video", f"--image={plate}", f"--prompt={prompt}", f"--ratio={g.get('ratio') or plate_ratio(plate)}"]
        cli_args += [f"--video={ref}"] if ref else []
        cli_args += [f"--audio={mus}"] if mus else []
    else:
        cli_args = ["image2video", f"--image={plate}", f"--prompt={prompt}"]
    # 两类失败不扣费，自动重试（最多 2 次，不占 retries）：
    #   提交前被拒「未检测到有效登录态」；图片上传到字节存储失败（2026-09-28 实测偶发，任务未生成、余额不变）。
    # retries 只管其它可能已扣费的失败。
    last, attempt, free_left, paid_left = None, 0, 2, g["retries"]
    while True:
        attempt += 1
        j, out = _cli(cfg, [*cli_args, f"--model_version={g['model']}", f"--duration={g['duration']}",
                            f"--video_resolution={g['resolution']}", "--poll=0"], c.logs / "generate_submit.log")
        sid = j.get("submit_id")
        if not sid:
            if NOT_LOGGED_IN in out and free_left > 0:
                free_left -= 1
                log("提交时读不到登录状态（未扣费），8 秒后重试")
                time.sleep(8)
                continue
            raise RuntimeError("提交失败：\n" + out[-2000:])
        log(f"已提交 {sid}（第 {attempt} 次）")
        try:
            r = _poll(cfg, sid, c.logs)
            url = r["result_json"]["videos"][0]["video_url"]
            try:
                _download(url, c.video)
            except RuntimeError as ex:                  # 已经扣费：不重试生成，告诉用户怎么免费重新下载
                raise SystemExit(f"视频已生成（已扣费）但下载失败：{ex}\n任务号 {sid}，"
                                 f"可用 dreamina query_result --submit_id={sid} 取地址重新下载到 {c.video}")
            after = credits(cfg)
            log(f"已下载 {c.video}，余额 {before} → {after}")
            return {"submit_id": sid, "credits_before": before, "credits_after": after, "attempts": attempt}
        except RuntimeError as ex:
            last = ex
            log(f"失败：{ex}")
            if "upload resource" in str(ex) and free_left > 0:
                free_left -= 1
                log("图片上传失败（任务没有生成，不扣费），30 秒后自动重试")
                time.sleep(30)
                continue
            if paid_left > 0:
                paid_left -= 1
                continue
            break
    raise RuntimeError(f"生成失败（共 {attempt} 次）：{last}")


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
