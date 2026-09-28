# UE 启动时自动执行（插件 Content/Python 下的 init_unreal.py）：注册「AI 动捕」菜单。
import unreal

try:
    from aimocap_ue import menus
    if menus.register():
        unreal.log("[AI 动捕] 菜单已加载")
except Exception as ex:  # 命令行模式没有菜单系统，失败不影响其它功能
    unreal.log_warning(f"[AI 动捕] 菜单未加载：{ex}")
