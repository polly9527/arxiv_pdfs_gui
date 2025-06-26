# run_headless.py
import os
import sys
import time
from config_manager import ConfigManager
from main import run_full_workflow

# 控制台日志记录器
def console_logger(message):
    """一个简单的回调函数，用于在控制台打印带时间戳的日志。"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    # 过滤掉字典类型的进度更新，只打印字符串日志
    if isinstance(message, str):
        print(f"[{timestamp}] {message}")

if __name__ == '__main__':
    print("--- Headless Runner for ArXiv AI Analyzer ---")
    
    # 确定根目录
    if getattr(sys, 'frozen', False):
        root_dir = os.path.dirname(sys.executable)
    else:
        root_dir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"Root directory set to: {root_dir}")

    # 加载配置
    try:
        config_manager = ConfigManager(root_dir)
        config = config_manager.load_config()
        print("Configuration loaded successfully.")
    except Exception as e:
        console_logger(f"FATAL: Failed to load configuration. Error: {e}")
        sys.exit(1)

    # 运行核心工作流
    try:
        # 核心逻辑的入口点，传入 console_logger 作为回调
        run_full_workflow(config, console_logger)
        print("--- Workflow finished ---")
    except Exception as e:
        console_logger(f"FATAL: An uncaught exception occurred during workflow execution. Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)