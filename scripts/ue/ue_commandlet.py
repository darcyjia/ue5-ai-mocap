"""命令行入口：UnrealEditor-Cmd <uproject> -run=pythonscript -script=ue_commandlet.py，任务 JSON 在 AIMOCAP_JOB。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ue_pipeline  # noqa: E402

job = json.load(open(os.environ["AIMOCAP_JOB"], encoding="utf-8"))
job["headless"] = True          # 命令行没有 Slate：面部控制板轨道加不了（会崩），只在编辑器插件里加
ue_pipeline.run_job(job)
