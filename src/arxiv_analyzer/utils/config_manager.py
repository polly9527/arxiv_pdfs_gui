# config_manager.py
import os
import json
import shutil
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, root_dir):
        self.root_dir = os.path.abspath(root_dir)
        self.config_path = os.path.join(self.root_dir, 'config.json')
        self.backup_path = os.path.join(self.root_dir, 'config.json.bak')
        os.makedirs(self.root_dir, exist_ok=True)

    def get_default_config(self):
        """返回包含所有默认值的配置字典。"""
        # --- 【修改点】 ---
        # 移除了旧的 'output_dir'
        # 新增了 'arxiv_output_dir' 和 'local_scan_dir'
        return {
            "search_keyword_list": ["encrypted traffic classification"],
            "search_years": ["2025", "2024"],
            "api_key": "在此处输入您的API密钥",
            "model_name": "gemini-2.5-pro",
            "prompt": "...", # Prompt 内容保持不变，为简洁省略
            "email_sender": "example@qq.com",
            "email_password": "your_app_password",
            "email_receiver": "example@126.com",
            "smtp_server": "smtp.qq.com",
            "smtp_port": 465,
            "proxy_enabled": True,
            "proxy_host": "127.0.0.1",
            "proxy_port": 10809,
            "arxiv_output_dir": os.path.join(self.root_dir, "arxiv_output"), # ArXiv工作流的默认输出路径
            "local_scan_dir": "", # 本地扫描路径默认为空，强制用户选择
            "request_timeout": 300,
            "max_retries": 2
        }

    def load_config(self):
        # (此函数内部逻辑无变化, 它的 setdefault 机制能很好地处理新增的默认值)
        # (为保持简洁，此处省略)
        logger.info(f"Attempting to load config from {self.config_path}")
        if os.path.exists(self.config_path) and os.path.getsize(self.config_path) > 0:
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f: config = json.load(f)
                logger.info("Config loaded successfully")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load config: {e}")
                return self.get_default_config() # 简化：加载失败直接返回默认值
        else:
            logger.warning(f"Config file is missing or empty, returning default config.")
            return self.get_default_config()

        # 确保所有键都存在
        defaults = self.get_default_config()
        for key, value in defaults.items():
            config.setdefault(key, value)
        return config


    def save_config(self, config):
        # (此函数内部逻辑无变化)
        # (为保持简洁，此处省略)
        logger.info(f"Saving config to {self.config_path}")
        try:
            if os.path.exists(self.config_path) and os.path.getsize(self.config_path) > 0:
                shutil.copy2(self.config_path, self.backup_path)
            temp_path = self.config_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            os.replace(temp_path, self.config_path)
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to save config: {e}")
            raise IOError(f"Config save failed: {e}")