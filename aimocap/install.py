"""把编辑器插件以目录链接（junction）方式装进 UE 工程：仓库里改代码，工程里立即生效。"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from .util import ROOT, log

SRC = ROOT / "ue_plugin" / "AIMocap"


def install_ue_plugin(cfg):
    proj = Path(cfg["paths"]["ue_project"])
    link = proj.parent / "Plugins" / "AIMocap"
    link.parent.mkdir(exist_ok=True)
    if link.exists():
        if os.path.realpath(link) == os.path.realpath(SRC):
            log(f"插件已链接：{link} → {SRC}")
        else:
            raise SystemExit(f"{link} 已存在且不是指向本仓库的链接，请先手动处理")
    else:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(SRC)], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise SystemExit("创建目录链接失败：" + r.stdout.decode("gbk", errors="replace"))
        log(f"已链接：{link} → {SRC}")
    d = json.loads(proj.read_text(encoding="utf-8"))
    names = {p["Name"] for p in d.get("Plugins", [])}
    need = [n for n in ("AIMocap", "PythonScriptPlugin", "EditorScriptingUtilities") if n not in names]
    if need:
        bak = proj.with_suffix(".uproject.bak_aimocap")
        if not bak.exists():
            shutil.copy(proj, bak)
        d.setdefault("Plugins", []).extend({"Name": n, "Enabled": True} for n in need)
        proj.write_text(json.dumps(d, indent="\t", ensure_ascii=False), encoding="utf-8")
        log(f"已在 {proj.name} 里启用：{need}（备份 {bak.name}）")
    log("重新打开 UE 工程后，主菜单栏会出现「AI 动捕」")
