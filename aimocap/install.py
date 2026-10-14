"""把编辑器插件以目录链接（junction）方式装进 UE 工程：仓库里改代码，工程里立即生效。"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from .util import ROOT, log
from .config import path as cpath

SRC = ROOT / "ue_plugin" / "AIMocap"


def install_ue_plugin(cfg, project=None):
    proj = Path(project or cpath(cfg, "ue_project"))
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
        if r.returncode == 0:
            log(f"已链接：{link} → {SRC}")
        else:                                       # 非 NTFS 盘（如 exFAT）建不了目录链接：改用工程的额外插件目录
            link = None
            log("建目录链接失败（" + r.stdout.decode("gbk", errors="replace").strip() + "），改用 AdditionalPluginDirectories")
    d = json.loads(proj.read_text(encoding="utf-8"))
    if link is None:
        extra = d.setdefault("AdditionalPluginDirectories", [])
        if str(SRC.parent).replace("\\", "/") not in [x.replace("\\", "/") for x in extra]:
            extra.append(str(SRC.parent).replace("\\", "/"))
        try:
            (proj.parent / "Plugins").rmdir()            # 刚才建的空目录
        except OSError:
            pass
    names = {p["Name"] for p in d.get("Plugins", [])}
    need = [n for n in ("AIMocap", "PythonScriptPlugin", "EditorScriptingUtilities") if n not in names]
    if need or link is None:
        bak = proj.with_suffix(".uproject.bak_aimocap")
        if not bak.exists():
            shutil.copy(proj, bak)
        d.setdefault("Plugins", []).extend({"Name": n, "Enabled": True} for n in need)
        proj.write_text(json.dumps(d, indent="\t", ensure_ascii=False), encoding="utf-8")
        log(f"已在 {proj.name} 里启用：{need}（备份 {bak.name}）" + ("；插件目录：" + str(SRC.parent) if link is None else ""))
    log("重新打开 UE 工程后，主菜单栏会出现「AI 动捕」")
