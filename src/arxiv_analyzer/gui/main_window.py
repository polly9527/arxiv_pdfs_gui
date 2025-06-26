# main_window.py
import os
import sys
import time
import logging
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QProgressBar, QTextEdit, QTabWidget, QLabel, QLineEdit,
    QComboBox, QSpinBox, QCheckBox, QGroupBox, QFileDialog, QMessageBox,
    QTimeEdit
)
from PyQt6.QtCore import QCoreApplication, QTimer, Qt, QTime
from PyQt6.QtGui import QCloseEvent

from arxiv_analyzer.utils.config_manager import ConfigManager
from arxiv_analyzer.gui.worker import Worker
try:
    from arxiv_analyzer.cli.scheduler_manager import SchedulerManager
except ImportError:
    SchedulerManager = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, root_dir=None):
        super().__init__()
        
        # --- 基本初始化 ---
        if getattr(sys, 'frozen', False):
            self.root_dir = os.path.dirname(sys.executable)
        else:
            self.root_dir = root_dir or os.path.dirname(os.path.abspath(__file__))
        
        logger.info(f"Root directory: {self.root_dir}")
        
        self.config_manager = ConfigManager(self.root_dir)
        self.config = self.config_manager.load_config()
        self.worker = None
        self.is_initializing = True
        self.chunk_count = 0
        self.total_chunks = 0
        self.last_save_request = 0
        self.save_pending = False

        # --- 初始化调度器管理器 ---
        if SchedulerManager:
            self.task_name = "ArXivDailyAnalyzerTask"
            task_executable_path = "" # 初始化为空

            if getattr(sys, 'frozen', False):
                # 如果是打包后的程序, sys.executable 就是当前运行的exe的绝对路径
                task_executable_path = sys.executable
                logger.info(f"Packaged mode detected. Task executable path: {task_executable_path}")
            else:
                # 在开发模式下，我们无法知道最终打包的exe路径，因此禁用调度器功能
                logger.warning("Development mode detected. Scheduler feature will be disabled.")
                # 可以在这里给用户一个提示，或者在UI上禁用相关按钮

            # 仅当成功获取到可执行文件路径时，才初始化调度器
            if task_executable_path:
                try:
                    self.scheduler = SchedulerManager(self.task_name, task_executable_path)
                except (ValueError, FileNotFoundError) as e:
                    logger.error(f"SchedulerManager initialization failed: {e}")
                    self.scheduler = None
            else:
                self.scheduler = None
        else:
            self.scheduler = None

        # --- UI 初始化 ---
        self.setWindowTitle("ArXiv AI 分析器")
        self.setGeometry(100, 100, 900, 700)
        self._init_ui()
        self._load_settings_to_ui()
        
        self.is_initializing = False
        self._update_schedule_status_display()

    def _init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        control_layout = QHBoxLayout()
        self.btn_run_full = QPushButton("🚀 完整工作流")
        self.btn_run_retry = QPushButton("🔁 仅重试失败")
        self.btn_stop = QPushButton("🛑 停止任务")
        self.btn_stop.setEnabled(False)
        control_layout.addWidget(self.btn_run_full)
        control_layout.addWidget(self.btn_run_retry)
        control_layout.addWidget(self.btn_stop)
        main_layout.addLayout(control_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.progress_bar)

        self.tabs = QTabWidget()
        self._create_search_tab()
        self._create_ai_tab()
        self._create_email_tab()
        self._create_advanced_tab()
        self._create_scheduler_tab()
        main_layout.addWidget(self.tabs)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(self.log_output)
        
        self.btn_run_full.clicked.connect(lambda: self.start_task("full"))
        self.btn_run_retry.clicked.connect(lambda: self.start_task("retry"))
        self.btn_stop.clicked.connect(self.stop_task)

        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self._save_settings_to_file)

    # --- 以下是您原始的、用于创建各设置标签页的完整函数 ---
    def _create_search_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.addWidget(QLabel("关键词:"), 0, 0)
        self.search_keywords = QLineEdit()
        layout.addWidget(self.search_keywords, 0, 1)
        
        year_group = QGroupBox("目标年份")
        year_layout = QHBoxLayout()
        self.year_checkboxes = {}
        for year in ["2025", "2024", "2023", "2022"]:
            cb = QCheckBox(year)
            self.year_checkboxes[year] = cb
            year_layout.addWidget(cb)
        year_group.setLayout(year_layout)
        layout.addWidget(year_group, 1, 0, 1, 2)
        
        self.tabs.addTab(tab, "搜索配置")

        self.search_keywords.editingFinished.connect(lambda: self._schedule_save(1000))
        for cb in self.year_checkboxes.values():
            cb.toggled.connect(lambda: self._schedule_save(1000))

    def _create_ai_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        grid = QGridLayout()
        grid.addWidget(QLabel("Gemini API Key:"), 0, 0)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(self.api_key, 0, 1)
        grid.addWidget(QLabel("AI 模型:"), 1, 0)
        self.model_name = QComboBox()
        self.model_name.addItems(["gemini-2.5-pro", "gemini-2.5-flash"]) # 您可以按需修改模型列表
        grid.addWidget(self.model_name, 1, 1)
        
        layout.addLayout(grid)
        layout.addWidget(QLabel("分析指令模板 (Prompt):"))
        self.prompt = QTextEdit()
        self.prompt.setAcceptRichText(False)
        layout.addWidget(self.prompt)
        
        self.tabs.addTab(tab, "AI 模型")

        self.api_key.editingFinished.connect(lambda: self._schedule_save(1000))
        self.model_name.currentTextChanged.connect(lambda: self._schedule_save(1000))
        self.prompt.textChanged.connect(lambda: self._schedule_save(1000))

    def _create_email_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.addWidget(QLabel("发件人邮箱:"), 0, 0)
        self.email_sender = QLineEdit()
        layout.addWidget(self.email_sender, 0, 1)
        layout.addWidget(QLabel("授权码/密码:"), 1, 0)
        self.email_password = QLineEdit()
        self.email_password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.email_password, 1, 1)
        layout.addWidget(QLabel("收件人邮箱:"), 2, 0)
        self.email_receiver = QLineEdit()
        layout.addWidget(self.email_receiver, 2, 1)
        layout.addWidget(QLabel("SMTP 服务器:"), 3, 0)
        self.smtp_server = QLineEdit()
        layout.addWidget(self.smtp_server, 3, 1)
        layout.addWidget(QLabel("SMTP 端口:"), 4, 0)
        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(1, 65535)
        layout.addWidget(self.smtp_port, 4, 1)

        self.tabs.addTab(tab, "邮件通知")

        self.email_sender.editingFinished.connect(lambda: self._schedule_save(1000))
        self.email_password.editingFinished.connect(lambda: self._schedule_save(1000))
        self.email_receiver.editingFinished.connect(lambda: self._schedule_save(1000))
        self.smtp_server.editingFinished.connect(lambda: self._schedule_save(1000))
        self.smtp_port.valueChanged.connect(lambda: self._schedule_save(1000))

    def _create_advanced_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        proxy_group = QGroupBox("网络代理")
        proxy_layout = QGridLayout()
        self.proxy_enabled = QCheckBox("启用代理")
        proxy_layout.addWidget(self.proxy_enabled, 0, 0, 1, 2)
        proxy_layout.addWidget(QLabel("代理服务器地址:"), 1, 0)
        self.proxy_host = QLineEdit()
        proxy_layout.addWidget(self.proxy_host, 1, 1)
        proxy_layout.addWidget(QLabel("代理端口:"), 2, 0)
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        proxy_layout.addWidget(self.proxy_port, 2, 1)
        proxy_group.setLayout(proxy_layout)
        layout.addWidget(proxy_group)
        
        path_group = QGroupBox("文件路径")
        path_layout = QGridLayout()
        path_layout.addWidget(QLabel("输出根目录:"), 0, 0)
        self.output_dir = QLineEdit()
        path_layout.addWidget(self.output_dir, 0, 1)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._select_output_dir)
        path_layout.addWidget(btn_browse, 0, 2)
        path_group.setLayout(path_layout)
        layout.addWidget(path_group)
        
        other_group = QGroupBox("超时与重试")
        other_layout = QGridLayout()
        other_layout.addWidget(QLabel("请求超时(秒):"), 0, 0)
        self.request_timeout = QSpinBox()
        self.request_timeout.setRange(10, 1000)
        other_layout.addWidget(self.request_timeout, 0, 1)
        other_layout.addWidget(QLabel("API最大重试次数:"), 1, 0)
        self.max_retries = QSpinBox()
        self.max_retries.setRange(0, 10)
        other_layout.addWidget(self.max_retries, 1, 1)
        other_group.setLayout(other_layout)
        layout.addWidget(other_group)
        
        self.tabs.addTab(tab, "高级设置")

        self.proxy_enabled.toggled.connect(lambda: self._schedule_save(1000))
        self.proxy_host.editingFinished.connect(lambda: self._schedule_save(1000))
        self.proxy_port.valueChanged.connect(lambda: self._schedule_save(1000))
        self.output_dir.editingFinished.connect(lambda: self._schedule_save(1000))
        self.request_timeout.valueChanged.connect(lambda: self._schedule_save(1000))
        self.max_retries.valueChanged.connect(lambda: self._schedule_save(1000))

    # --- 以下是新增的“自动任务”标签页及其逻辑 ---
    def _create_scheduler_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        group = QGroupBox("定时任务设置 (仅支持Windows)")
        grid = QGridLayout(group)
        
        self.cb_enable_schedule = QCheckBox("启用自动执行")
        
        grid.addWidget(QLabel("执行频率:"), 1, 0)
        self.combo_frequency = QComboBox()
        self.combo_frequency.addItems(["DAILY", "WEEKLY"])
        grid.addWidget(self.combo_frequency, 1, 1)

        grid.addWidget(QLabel("执行时间:"), 2, 0)
        self.time_edit_schedule = QTimeEdit()
        self.time_edit_schedule.setDisplayFormat("HH:mm")
        grid.addWidget(self.time_edit_schedule, 2, 1)
        
        self.btn_save_schedule = QPushButton("保存 / 更新计划")
        self.btn_delete_schedule = QPushButton("删除计划")
        
        status_group = QGroupBox("当前计划状态")
        status_layout = QVBoxLayout(status_group)
        self.lbl_schedule_status = QLabel("状态：正在查询...")
        self.lbl_schedule_status.setWordWrap(True)
        status_layout.addWidget(self.lbl_schedule_status)
        
        self.btn_save_schedule.clicked.connect(self._on_save_schedule)
        self.btn_delete_schedule.clicked.connect(self._on_delete_schedule)
        
        layout.addWidget(self.cb_enable_schedule)
        layout.addWidget(group)
        layout.addWidget(self.btn_save_schedule)
        layout.addWidget(self.btn_delete_schedule)
        layout.addWidget(status_group)
        layout.addStretch()
        
        self.tabs.addTab(tab, "自动任务")

    def _on_save_schedule(self):
        if not self.scheduler:
            QMessageBox.critical(self, "错误", "调度器未成功初始化，无法设置任务。")
            return
            
        if not self.cb_enable_schedule.isChecked():
            QMessageBox.warning(self, "提示", "请先勾选“启用自动执行”后再保存。\n如果想删除任务，请使用“删除计划”按钮。")
            return

        frequency = self.combo_frequency.currentText()
        time_str = self.time_edit_schedule.time().toString("HH:mm")

        reply = QMessageBox.question(self, "确认操作", f"您确定要在系统任务计划程序中创建或更新一个名为 '{self.task_name}' 的任务吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        # 调用管理器创建任务，并传入后台运行参数
        success, message = self.scheduler.create_or_update_task(frequency, time_str, arguments="--run-task")

        if success:
            QMessageBox.information(self, "成功", "定时任务已成功创建/更新！")
            self.config['schedule_enabled'] = True
            self.config['schedule_frequency'] = frequency
            self.config['schedule_time'] = time_str
            self.config_manager.save_config(self.config)
        else:
            QMessageBox.critical(self, "失败", f"创建/更新定时任务失败！\n\n错误详情:\n{message}")
        
        self._update_schedule_status_display()

    def _on_delete_schedule(self):
        if not self.scheduler:
            QMessageBox.critical(self, "错误", "调度器未成功初始化，无法删除任务。")
            return

        reply = QMessageBox.question(self, "确认操作", f"您确定要从系统任务计划程序中永久删除名为 '{self.task_name}' 的任务吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return
            
        success, message = self.scheduler.delete_task()
        if success or "找不到" in message:
            QMessageBox.information(self, "成功", "定时任务已成功删除。")
            self.config['schedule_enabled'] = False
            self.config_manager.save_config(self.config)
            self.cb_enable_schedule.setChecked(False)
        else:
            QMessageBox.critical(self, "失败", f"删除定时任务失败！\n\n错误详情:\n{message}")

        self._update_schedule_status_display()

    def _update_schedule_status_display(self):
        if self.scheduler:
            status_text = self.scheduler.check_task_status()
            self.lbl_schedule_status.setText(status_text)
        else:
            self.lbl_schedule_status.setText("状态：调度器不可用 (可能未找到后台任务exe)。")

    # --- 以下是其他核心方法 ---
    def _select_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出根目录", self.output_dir.text())
        if directory:
            self.output_dir.setText(directory)
            self._schedule_save(1000)

    def _schedule_save(self, delay_ms):
        if not self.is_initializing:
            self.save_pending = True
            self.save_timer.start(delay_ms)

    def _save_settings_to_file(self):
        if not hasattr(self, 'config_manager') or not self.save_pending:
            return
        self._gather_config_from_ui()
        try:
            self.config_manager.save_config(self.config)
            save_time = time.strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Config saved at {save_time}")
            self.log_output.append(f"配置已于 {save_time} 自动保存")
            self.save_pending = False
            self.save_timer.stop()
        except IOError as e:
            logger.error(f"Failed to save config: {e}")
            self.log_output.append(f"配置保存失败: {e}")

    def _load_settings_to_ui(self):
        logger.info("Loading config to UI")
        # --- 省略了 blockSignals(True/False) 的重复代码，但原理不变 ---
        self.search_keywords.setText(self.config.get('search_keywords', ''))
        loaded_years = self.config.get('search_years', [])
        for year, cb in self.year_checkboxes.items():
            cb.setChecked(year in loaded_years)
        self.api_key.setText(self.config.get('api_key', ''))
        self.model_name.setCurrentText(self.config.get('model_name', 'gemini-1.5-pro-latest'))
        self.prompt.setPlainText(self.config.get('prompt', ''))
        self.email_sender.setText(self.config.get('email_sender', ''))
        self.email_password.setText(self.config.get('email_password', ''))
        self.email_receiver.setText(self.config.get('email_receiver', ''))
        self.smtp_server.setText(self.config.get('smtp_server', ''))
        self.smtp_port.setValue(self.config.get('smtp_port', 465))
        self.proxy_enabled.setChecked(self.config.get('proxy_enabled', False))
        self.proxy_host.setText(self.config.get('proxy_host', ''))
        self.proxy_port.setValue(self.config.get('proxy_port', 10809))
        self.output_dir.setText(self.config.get('output_dir', ''))
        self.request_timeout.setValue(self.config.get('request_timeout', 300))
        self.max_retries.setValue(self.config.get('max_retries', 2))
        
        # 加载定时任务设置
        self.cb_enable_schedule.setChecked(self.config.get("schedule_enabled", False))
        saved_freq = self.config.get("schedule_frequency", "DAILY")
        if self.combo_frequency.findText(saved_freq) != -1:
            self.combo_frequency.setCurrentText(saved_freq)
        saved_time_str = self.config.get("schedule_time", "22:30")
        self.time_edit_schedule.setTime(QTime.fromString(saved_time_str, "HH:mm"))

    def _gather_config_from_ui(self):
        logger.info("Gathering config from UI")
        self.config['search_keywords'] = self.search_keywords.text()
        self.config['search_years'] = [year for year, cb in self.year_checkboxes.items() if cb.isChecked()]
        self.config['api_key'] = self.api_key.text()
        self.config['model_name'] = self.model_name.currentText()
        self.config['prompt'] = self.prompt.toPlainText()
        self.config['email_sender'] = self.email_sender.text()
        self.config['email_password'] = self.email_password.text()
        self.config['email_receiver'] = self.email_receiver.text()
        self.config['smtp_server'] = self.smtp_server.text()
        self.config['smtp_port'] = self.smtp_port.value()
        self.config['proxy_enabled'] = self.proxy_enabled.isChecked()
        self.config['proxy_host'] = self.proxy_host.text()
        self.config['proxy_port'] = self.proxy_port.value()
        self.config['output_dir'] = self.output_dir.text()
        self.config['request_timeout'] = self.request_timeout.value()
        self.config['max_retries'] = self.max_retries.value()
        self.config['root_dir'] = self.root_dir

        # 收集定时任务设置
        self.config['schedule_enabled'] = self.cb_enable_schedule.isChecked()
        self.config['schedule_frequency'] = self.combo_frequency.currentText()
        self.config['schedule_time'] = self.time_edit_schedule.time().toString("HH:mm")

    def start_task(self, task_type):
        self.log_output.clear()
        self.log_output.append(f"准备开始任务: {task_type}")
        self._gather_config_from_ui()
        
        self.btn_run_full.setEnabled(False)
        self.btn_run_retry.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        
        self.worker = Worker(task_type, self.config)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.start()

    def update_progress(self, data):
        if isinstance(data, str):
            self.log_output.append(data)
            self.log_output.ensureCursorVisible()
        elif isinstance(data, dict):
            event_type = data.get('type')
            if event_type == 'stream_start':
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setFormat("正在接收AI分析结果...")
            elif event_type == 'stream_end':
                current = data.get('current_task', 0)
                total = data.get('total_tasks', 0)
                self.log_output.append(f"  -> 接收完成: 共 {data.get('total_chars', 0):,} 字符，耗时 {data.get('elapsed_time', 0):.2f} 秒。")
                self.progress_bar.setRange(0, 1)
                self.progress_bar.setValue(1)
                self.progress_bar.setFormat(f"分析完成 ({current}/{total})")

    def stop_task(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log_output.append("\n--- 任务已被用户强制停止 ---")

    def on_task_finished(self, message):
        self.log_output.append(f"\n--- {message} ---")
        self.btn_run_full.setEnabled(True)
        self.btn_run_retry.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("所有任务已完成")
        QMessageBox.information(self, "任务结束", message)

    def closeEvent(self, event: QCloseEvent):
        self._save_settings_to_file()
        event.accept()