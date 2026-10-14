"""即梦（Seedance）账号：找 CLI、查登录状态、OAuth 设备码登录、退出。

即梦 CLI 的登录是 OAuth Device Flow：`dreamina login --headless` 打印授权链接、用户码、设备码后退出，
`dreamina login checklogin --device_code=… --poll=N` 等用户在网页上用抖音扫码确认。
令牌存在 Windows 凭据库，**谁启动的登录，谁的凭据库里才有**——Claude 桌面应用（MSIX）里登录的令牌，
UE 和普通终端看不到；所以 UE 插件要自己发起登录（插件菜单「即梦账号 / 连接…」）。

    python -m aimocap dreamina status            # JSON：装没装、登没登录、余额
    python -m aimocap dreamina login             # 终端里交互登录：打开授权页，等扫码
    python -m aimocap dreamina login --json      # 只发起登录，打印授权信息（插件用）
    python -m aimocap dreamina check --device-code X [--poll 300]
    python -m aimocap dreamina logout
"""
import json
import os
import re
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path

from .util import extract_json

INSTALL_HINT = ("没找到即梦命令行工具 dreamina。安装：在 Git Bash 里运行\n"
                "    curl -fsSL https://jimeng.jianying.com/cli | bash\n"
                "（Windows 会装成 %USERPROFILE%\\bin\\dreamina.exe），或者在 config.toml 的 [paths] dreamina 填它的完整路径。")
NOT_LOGGED_IN = "未检测到有效登录态"


def exe(cfg):
    """按顺序找：config 里写的路径 → PATH → ~/bin/dreamina(.exe)。找不到返回 None。"""
    cands = [cfg.get("paths", {}).get("dreamina"), shutil.which("dreamina"),
             str(Path.home() / "bin" / "dreamina.exe"), str(Path.home() / "bin" / "dreamina")]
    for c in cands:
        if c and Path(c).is_file():
            return str(Path(c))
    return None


def _run(cfg, args, timeout=60):
    path = exe(cfg)
    if path is None:
        raise FileNotFoundError(INSTALL_HINT)
    p = subprocess.run([path, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = p.stdout.decode("utf-8", errors="replace")
    return p.returncode, out


def _field(out, *names):
    """从 JSON 或「key: value / key=value」行里取字段。"""
    j = extract_json(out)
    if isinstance(j, dict):
        for n in names:
            for d in (j, j.get("data") or {}):
                if isinstance(d, dict) and d.get(n) not in (None, ""):
                    return str(d[n])
    for n in names:
        m = re.search(rf'"?{n}"?\s*[:=]\s*"?([^\s",]+)', out)
        if m:
            return m.group(1)
    return None


def status(cfg, tries=2, wait=3):
    """{installed, path, logged_in, credit, vip_level, message}。读不到时短暂重试（令牌刷新时偶发）。"""
    path = exe(cfg)
    if path is None:
        return {"installed": False, "path": None, "logged_in": False, "credit": None, "vip_level": None,
                "message": INSTALL_HINT}
    out = ""
    for i in range(tries):
        _, out = _run(cfg, ["user_credit"])
        j = extract_json(out) or {}
        if j.get("total_credit") is not None:
            return {"installed": True, "path": path, "logged_in": True, "credit": j["total_credit"],
                    "vip_level": j.get("vip_level"), "message": ""}
        if i < tries - 1:
            time.sleep(wait)
    return {"installed": True, "path": path, "logged_in": False, "credit": None, "vip_level": None,
            "message": out.strip()[-300:]}


def start_login(cfg):
    """发起设备码登录，返回 {already, verification_uri, user_code, device_code, expires_in}。
    已经登录时 already=True、其余为空。"""
    st = status(cfg, tries=1)
    if st["logged_in"]:
        return {"already": True, "credit": st["credit"], "vip_level": st["vip_level"]}
    _, out = _run(cfg, ["login", "--headless"])
    info = {"already": False,
            "verification_uri": _field(out, "verification_uri_complete", "verification_uri"),
            "user_code": _field(out, "user_code"),
            "device_code": _field(out, "device_code"),
            "expires_in": _field(out, "expires_in")}
    if not info["device_code"] or not info["verification_uri"]:
        raise RuntimeError("即梦没有返回授权信息：\n" + out[-800:])
    return info


def check_login(cfg, device_code, poll=300):
    """等用户扫码授权（最多 poll 秒），成功后返回 status()。"""
    code, out = _run(cfg, ["login", "checklogin", f"--device_code={device_code}", f"--poll={int(poll)}"],
                     timeout=int(poll) + 60)
    st = status(cfg)
    if not st["logged_in"]:
        st["message"] = (out.strip()[-400:] or f"退出码 {code}")
    return st


def logout(cfg):
    _, out = _run(cfg, ["logout"])
    return {"ok": True, "message": out.strip()[-200:]}


def cmd(cfg, a):
    """命令行入口（cli.py 的 dreamina 子命令）。"""
    if a.action == "status":
        print(json.dumps(status(cfg), ensure_ascii=False))
    elif a.action == "logout":
        print(json.dumps(logout(cfg), ensure_ascii=False))
    elif a.action == "check":
        print(json.dumps(check_login(cfg, a.device_code, a.poll), ensure_ascii=False))
    elif a.action == "login":
        info = start_login(cfg)
        if a.json:
            print(json.dumps(info, ensure_ascii=False))
            return
        if info["already"]:
            print(f"已经登录即梦：余额 {info['credit']} 积分（会员 {info['vip_level']}）")
            return
        print(f"在浏览器里打开下面的链接，用抖音扫码确认授权：\n    {info['verification_uri']}")
        if info.get("user_code"):
            print(f"页面要求输入授权码时填：{info['user_code']}")
        try:
            webbrowser.open(info["verification_uri"])
        except Exception:
            pass
        print(f"等待授权（最多 {a.poll} 秒）……")
        st = check_login(cfg, info["device_code"], a.poll)
        if st["logged_in"]:
            print(f"登录成功：余额 {st['credit']} 积分（会员 {st['vip_level']}）")
        else:
            raise SystemExit("没有完成授权：" + st["message"])
