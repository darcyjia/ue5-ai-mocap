"""在关卡编辑器主菜单栏注册「AI 动捕」。"""
import unreal

ITEMS = [
    ("Run", "new", "新建动捕…", "选视频（或提示词+构图板）和两个 MetaHuman，后台解算，完成后自动建关卡和序列", "new_job()"),
    ("Run", "plates", "出构图板候选（免费）…", "用即梦文生图出几张构图板候选，挑一张用于生成", "plates()"),
    ("Run", "redo", "换角色 / 重做重定向…", "给已解算好的素材换 MetaHuman，只重做 UE 部分", "redo()"),
    ("Info", "status", "任务状态", "查看后台任务的进度和最近输出", "status()"),
    ("Info", "report", "打开质检报告…", "打开某个素材的 qc/report.html", "open_report()"),
    ("Info", "work", "打开工作目录", "打开 aimocap_work", "open_work()"),
    ("Info", "config", "打开配置文件", "打开 aimocap 的 config.toml", "open_config()"),
]


def register():
    menus = unreal.ToolMenus.get()
    main = menus.find_menu("LevelEditor.MainMenu")
    if main is None:
        return False
    sub = main.add_sub_menu(main.get_name(), "AIMocapSection", "AIMocap", "AI 动捕", "AI 视频 → 双人动捕 → MetaHuman")
    sub.add_section("Run", "处理")
    sub.add_section("Info", "查看")
    for section, name, label, tip, call in ITEMS:
        e = unreal.ToolMenuEntry(name=name, type=unreal.MultiBlockType.MENU_ENTRY)
        e.set_label(label)
        e.set_tool_tip(tip)
        e.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "",
                             f"from aimocap_ue import actions; actions.{call}")
        sub.add_menu_entry(section, e)
    menus.refresh_all_widgets()
    return True
