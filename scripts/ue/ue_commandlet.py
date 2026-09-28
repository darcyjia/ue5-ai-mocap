"""命令行入口：UnrealEditor-Cmd <uproject> -run=pythonscript -script=ue_commandlet.py，任务 JSON 在 AIMOCAP_JOB。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ue_pipeline  # noqa: E402

ue_pipeline.run_job(json.load(open(os.environ["AIMOCAP_JOB"], encoding="utf-8")))
