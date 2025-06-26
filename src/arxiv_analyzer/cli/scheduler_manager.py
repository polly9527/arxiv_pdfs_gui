# scheduler_manager.py
import sys
import os
import subprocess
import re
import csv  # <-- 新增
import io   # <-- 新增


class SchedulerManager:
    """
    负责与操作系统任务计划程序交互的管理器。
    目前主要针对 Windows 的 schtasks.exe 实现。
    """
    def __init__(self, task_name, headless_exe_path):
        self.task_name = task_name
        self.headless_exe_path = headless_exe_path
        
        # 确保路径是绝对路径且用引号包裹，以处理空格等问题
        if not os.path.isabs(self.headless_exe_path):
            raise ValueError("Headless executable path must be absolute.")
        
        # 针对Windows的路径格式化
        self.formatted_exe_path = f'"{self.headless_exe_path}"'

    def _run_command(self, command):
        """执行一个系统命令并返回结果。"""
        try:
            # 使用 CREATE_NO_WINDOW 标志来避免在Windows上弹出命令行窗口
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='gbk', startupinfo=startupinfo)
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr
        except FileNotFoundError:
            return False, f"命令未找到，请确保您在支持的环境中运行（例如Windows）。"

    def create_or_update_task(self, frequency, time_str, arguments=""):
        """
        创建或更新一个定时任务。
        frequency: 'DAILY', 'WEEKLY'等
        time_str: 'HH:mm' 格式
        arguments: 要附加到可执行文件路径后的命令行参数
        """
        if sys.platform != 'win32':
            return False, "此功能目前仅支持Windows系统。"

        # 将exe路径和参数组合成一个完整的运行命令
        task_run_command = f'{self.formatted_exe_path} {arguments}'.strip()

        command = [
            'schtasks', '/Create',
            '/TN', self.task_name,
            '/TR', task_run_command,  # 使用包含参数的完整命令
            '/SC', frequency,
            '/ST', time_str,
            '/F'
        ]
        return self._run_command(command)

    def delete_task(self):
        """删除定时任务。"""
        if sys.platform != 'win32':
            return False, "此功能目前仅支持Windows系统。"
            
        command = [
            'schtasks', '/Delete',
            '/TN', self.task_name,
            '/F'
        ]
        return self._run_command(command)

    def check_task_status(self):
        """
        检查任务是否存在及其状态。
        新版使用CSV格式输出，以避免系统语言问题。
        """
        if sys.platform != 'win32':
            return "当前平台不支持任务状态检查。"

        # 使用 /FO CSV 请求标准化输出，/NH 表示无表头
        command = ['schtasks', '/Query', '/TN', self.task_name, '/FO', 'CSV', '/NH']
        success, output = self._run_command(command)
        
        if not success:
            if "找不到" in output or "not found" in output.lower():
                return "状态：当前无计划任务。"
            return f"状态：查询失败 - {output}"

        try:
            # 使用csv模块来安全地解析输出行
            # io.StringIO将字符串模拟成一个文件，供csv模块读取
            csv_reader = csv.reader(io.StringIO(output))
            task_info_list = next(csv_reader) # 获取解析后的列表

            # 根据schtasks的CSV输出格式，我们关心的是固定的列索引：
            # 索引 1: Next Run Time (下次运行时间)
            # 索引 2: Status (状态)
            next_run_time = task_info_list[1].strip()
            status = task_info_list[2].strip()

            # 对英文系统常见的状态做一些美化
            if status.lower() == "ready":
                status = "就绪"
            elif status.lower() == "running":
                status = "正在运行"
            elif status.lower() == "disabled":
                status = "已禁用"
            
            if next_run_time.lower() == "n/a" or next_run_time.lower() == "disabled":
                 next_run_time = "已禁用或无下次运行计划"
            
            return f"状态：任务已计划 | 状态: {status} | 下次运行: {next_run_time}"
            
        except (IndexError, StopIteration):
            # 如果输出格式意外地不正确，提供一个回退信息
            return "状态：解析任务信息失败，输出格式未知。"