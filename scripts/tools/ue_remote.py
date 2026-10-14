"""从外部给正在运行的 UE 编辑器发 Python（UE Python 插件的 Remote Execution，工程里要开 bRemoteExecution）。

    python ue_remote.py --project AIMocap_Demo nodes
    python ue_remote.py --project AIMocap_Demo exec "print(unreal.SystemLibrary.get_engine_version())"
    python ue_remote.py --project AIMocap_Demo file path/to/script.py [参数...]

命令在编辑器的游戏线程里同步执行，长任务期间编辑器界面会停住；输出较多时请脚本自己写日志文件。"""
import argparse
import json
import re
import sys
import time

def engine_py():
    """UE 自带的 remote_execution.py 所在目录：按 aimocap 配置里的 ue_cmd 找引擎，或用环境变量 UE_ENGINE_DIR。"""
    import os
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    eng = os.environ.get("UE_ENGINE_DIR")
    if not eng:
        for name in ("config.toml", "config.local.toml"):
            f = root / name
            if f.exists():
                eng = (tomllib.loads(f.read_text(encoding="utf-8")).get("paths") or {}).get("ue_cmd") or eng
        eng = str(Path(eng).parents[2]) if eng else None          # …/Engine/Binaries/Win64/UnrealEditor-Cmd.exe → …/Engine
    if not eng:
        raise SystemExit("找不到 UE 引擎：先运行 python -m aimocap setup --write，或设环境变量 UE_ENGINE_DIR=<…/Engine>")
    return str(Path(eng) / "Plugins/Experimental/PythonScriptPlugin/Content/Python")


ENGINE_PY = engine_py()
sys.path.insert(0, ENGINE_PY)
import remote_execution as rx  # noqa: E402


def free_port():
    """命令通道由这边监听。默认 6776 常被 WSL/Hyper-V 的保留端口段占掉（WinError 10013），挑一个能绑定的。"""
    import socket
    for port in (6776, 16776, 26776, 36776, 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("找不到可用端口")


def find_node(r, project, wait):
    t0 = time.time()
    while time.time() - t0 < wait:
        nodes = [n for n in r.remote_nodes if not project or n.get("project_name") == project]
        if nodes:
            return nodes[0]
        time.sleep(0.5)
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="", help="只连这个工程名的编辑器")
    ap.add_argument("--wait", type=float, default=15, help="等编辑器出现的秒数")
    ap.add_argument("cmd", choices=["nodes", "exec", "file"])
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()

    cfg = rx.RemoteExecutionConfig()
    cfg.command_endpoint = ("127.0.0.1", free_port())
    r = rx.RemoteExecution(cfg)
    r.start()
    try:
        if a.cmd == "nodes":
            time.sleep(min(a.wait, 3))
            print(json.dumps(r.remote_nodes, ensure_ascii=False, indent=1))
            return 0
        node = find_node(r, a.project, a.wait)
        if not node:
            print(f"没有找到运行中的 UE 编辑器（工程 {a.project or '任意'}）：编辑器开着吗？工程里开了 Remote Execution 吗？")
            return 2
        r.open_command_connection(node["node_id"])
        if a.cmd == "exec":
            command = " ".join(a.rest)
        else:
            # Git Bash 会把 /Game/... 这类参数改写成 <Git 安装目录>/Game/...，这里改回去
            rest = [re.sub(r"^[A-Za-z]:/Program Files/Git(?=/(Game|Engine|Script)/)", "", x) for x in a.rest]
            command = " ".join(f'"{x}"' if " " in x else x for x in rest)
        res = r.run_command(command, unattended=True, exec_mode=rx.MODE_EXEC_FILE)
        for o in res.get("output", []):
            print(o.get("output", "").rstrip("\n"))
        if not res.get("success"):
            print("[失败]", res.get("result", ""))
            return 1
        return 0
    finally:
        r.stop()


if __name__ == "__main__":
    sys.exit(main())
