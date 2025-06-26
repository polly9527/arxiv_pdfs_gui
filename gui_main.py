# gui_main.py
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from arxiv_analyzer.utils.config_manager import ConfigManager # 用于 headless 模式
from arxiv_analyzer.core.main import run_full_workflow        # 用于 headless 模式
import time


def run_headless_mode():
    """执行无界面的后台任务"""
    print("--- Running in Headless Mode ---")

    def console_logger(message):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(message, str):
            print(f"[{timestamp}] {message}")

    if getattr(sys, 'frozen', False):
        root_dir = os.path.dirname(sys.executable)
    else:
        root_dir = os.path.dirname(os.path.abspath(__file__))

    print(f"Root directory: {root_dir}")

    try:
        config_manager = ConfigManager(root_dir)
        config = config_manager.load_config()
        print("Config loaded.")
        run_full_workflow(config, console_logger)
        print("--- Headless workflow finished ---")
    except Exception as e:
        console_logger(f"FATAL: Headless execution failed. Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# --- 核心修改点：在启动时进行环境诊断 ---
try:
    import google.generativeai as genai
    print("--- 环境诊断信息 ---")
    print(f"Python解释器路径: {sys.executable}")
    print(f"google-generativeai 库版本: {genai.__version__}")
    print(f"google-generativeai 库位置: {genai.__file__}")
    print("--------------------")
except ImportError:
    print("错误：无法导入 'google.generativeai' 库。请确保已安装。")
    sys.exit(1)

from PyQt6.QtWidgets import QApplication
from arxiv_analyzer.gui.main_window import MainWindow

if __name__ == '__main__':
    # 检查命令行参数中是否包含我们约定的标志
    if '--run-task' in sys.argv:
        # 如果有 --run-task 参数，则执行无界面模式
        run_headless_mode()
    else:
        # 如果没有该参数，则正常启动GUI
        ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
        
        app = QApplication(sys.argv)
        window = MainWindow(root_dir=ROOT_DIR)
        window.show()
        
        sys.exit(app.exec())