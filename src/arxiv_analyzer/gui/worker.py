# worker.py
import os
import traceback
from PyQt6.QtCore import QThread, pyqtSignal, QObject 

from arxiv_analyzer.core.main import run_full_workflow
from arxiv_analyzer.core.retry_failures import run_retry_workflow

### 新增：自定义一个异常，用于信令任务取消 ###
class TaskCancelledError(Exception):
    """当任务被用户取消时抛出此异常。"""
    pass

class Worker(QThread):
    """
    在后台执行耗时任务的工作线程。
    """
    progress_update = pyqtSignal(object)
    task_finished = pyqtSignal(str)

    def __init__(self, task_type, config):
        super().__init__()
        self.task_type = task_type
        self.config = config
        self._is_running = True

    def setup_env(self):
        """根据配置设置环境变量，如代理。"""
        if self.config.get('proxy_enabled') and self.config.get('proxy_host') and self.config.get('proxy_port'):
            proxy_url = f"http://{self.config['proxy_host']}:{self.config['proxy_port']}"
            os.environ['HTTP_PROXY'] = proxy_url
            os.environ['HTTPS_PROXY'] = proxy_url
            self.progress_update.emit(f"代理已设置 -> {proxy_url}")
        else:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)
            self.progress_update.emit("信息: 未配置代理或代理未启用。")

    ### 新增：回调包装器，用于在每次更新进度时检查是否需要停止 ###
    def _progress_callback_wrapper(self, data):
        """
        包装回调。现在data可以是字符串，也可以是字典。
        直接将其通过信号发送出去。
        """
        if not self._is_running:
            raise TaskCancelledError("任务被用户请求停止。")
        self.progress_update.emit(data)

    def run(self):
        """线程入口点。"""
        self.setup_env()
        # ### 核心修改：使用新的回调包装器 ###
        callback = self._progress_callback_wrapper
        
        try:
            # 检查启动前是否已被停止
            if not self._is_running:
                self.task_finished.emit("任务在开始前被停止。")
                return

            if self.task_type == "full":
                run_full_workflow(self.config, callback)
            elif self.task_type == "retry":
                run_retry_workflow(self.config, callback)
            
            # 只有当任务正常完成（未被停止）时，才发出成功信号
            if self._is_running:
                self.task_finished.emit("任务成功完成。")

        ### 核心修改：捕获我们自定义的取消异常 ###
        except TaskCancelledError:
            # 这是预期的、优雅的停止流程
            self.task_finished.emit("任务被用户手动停止。")
        except Exception as e:
            # 这是意外的错误
            callback(f"!!! 后端逻辑发生严重错误: {e} !!!")
            callback(traceback.format_exc())
            self.task_finished.emit(f"任务因错误而终止。")

    def stop(self):
        """
        ### 核心修改：停止线程的逻辑改为设置标志位 ###
        不再使用危险的 terminate()。
        """
        if self._is_running:
            self.progress_update.emit(">>> 正在请求停止任务，请稍候...")
            self._is_running = False