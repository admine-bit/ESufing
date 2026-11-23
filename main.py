import sys

if __name__ == '__main__':
    if len(sys.argv) == 1:
        if sys.platform.startswith("linux"):
            from esurfingpy.campus import run
            sys.exit(run())
        from esurfingpy import log
        log.warning("无参数运行，即将打开图形界面……")
        try:
            from esurfingpy.gui import Gui
            Gui().run()
        except ImportError as e:
            log.error(f"无法启动图形界面，可能是因为缺少 GUI 依赖库或运行在无图形环境中: {e}")
            log.info("请使用命令行参数运行程序，例如: python main.py login")
            sys.exit(1)
    else:
        from esurfingpy.cli import cli
        cli()
