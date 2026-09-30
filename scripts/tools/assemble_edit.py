"""按剪辑表 edl.json 把预演渲染帧拼成视频，并按同样的剪辑把原声对上（定格段静音，重复剪辑的声音也重复）。
python assemble_edit.py --edl edl.json --frames DIR --audio 原视频.mp4 --out previz.mp4 [--ffmpeg PATH]"""
import argparse
import json
import subprocess

ap = argparse.ArgumentParser()
ap.add_argument("--edl", required=True)
ap.add_argument("--frames", required=True)
ap.add_argument("--audio", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--ffmpeg", default="ffmpeg")
a = ap.parse_args()
E = json.load(open(a.edl, encoding="utf-8"))
fps = E["fps"]
parts, n = [], 0
for i, s in enumerate(E["shots"]):
    d = s["frames"] / fps
    if s["hold"]:
        parts.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{d:.4f},aformat=sample_rates=44100:channel_layouts=stereo[s{i}]")
    else:
        t0 = (s["anim_frames"][0] - 1) / fps
        parts.append(f"[1:a]atrim=start={t0:.4f}:end={t0 + d:.4f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.01,afade=t=out:st={max(0, d - 0.01):.4f}:d=0.01,aformat=sample_rates=44100:channel_layouts=stereo[s{i}]")
    n += 1
fc = ";".join(parts) + ";" + "".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
cmd = [a.ffmpeg, "-v", "error", "-y", "-framerate", str(fps), "-i", f"{a.frames}/f_%05d.png", "-i", a.audio,
       "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "192k", "-shortest", a.out]
subprocess.run(cmd, check=True)
print("wrote", a.out, "frames", E["film_frames"], "=", round(E["film_frames"] / fps, 2), "s")
