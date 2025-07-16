# worker.py
import os
import traceback
from PyQt6.QtCore import QThread, pyqtSignal

# --- 【修改点 1】 ---
# 导入新的 run_local_analysis_workflow 函数
from arxiv_analyzer.core.main import run_full_workflow, run_local_analysis_workflow

class TaskCancelledError(Exception):
    """当任务被用户取消时抛出此异常。"""
    pass

class Worker(QThread):
    progress_update = pyqtSignal(object)
    task_finished = pyqtSignal(str)

    def __init__(self, task_type, config):
        super().__init__()
        self.task_type = task_type
        self.config = config
        self._is_running = True

    def setup_env(self):
        if self.config.get('proxy_enabled') and self.config.get('proxy_host') and self.config.get('proxy_port'):
            proxy_url = f"http://{self.config['proxy_host']}:{self.config['proxy_port']}"
            os.environ['HTTP_PROXY'] = proxy_url
            os.environ['HTTPS_PROXY'] = proxy_url
            self.progress_update.emit(f"代理已设置 -> {proxy_url}")
        else:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)
            self.progress_update.emit("信息: 未配置代理或代理未启用。")

    def _progress_callback_wrapper(self, data):
        if not self._is_running:
            raise TaskCancelledError("任务被用户请求停止。")
        self.progress_update.emit(data)

    def run(self):
        self.setup_env()
        callback = self._progress_callback_wrapper
        
        try:
            if not self._is_running:
                self.task_finished.emit("任务在开始前被停止。")
                return

            if self.task_type == "full":
                run_full_workflow(self.config, callback)
            # --- 【修改点 2】 ---
            # 调用新的本地文件夹分析工作流
            elif self.task_type == "local_folder":
                run_local_analysis_workflow(self.config, callback)
            
            if self._is_running:
                self.task_finished.emit("任务成功完成。")

        except TaskCancelledError:
            self.task_finished.emit("任务被用户手动停止。")
        except Exception as e:
            callback(f"!!! 后端逻辑发生严重错误: {e} !!!")
            callback(traceback.format_exc())
            self.task_finished.emit(f"任务因错误而终止。")

    def stop(self):
        if self._is_running:
            self.progress_update.emit(">>> 正在请求停止任务，请稍候...")
            self._is_running = False