import os
import json
import shutil
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConfigManager:
    """负责所有GUI配置的加载和保存，使用JSON文件进行持久化。"""
    def __init__(self, root_dir):
        self.root_dir = os.path.abspath(root_dir)
        self.config_path = os.path.join(self.root_dir, 'config.json')
        self.backup_path = os.path.join(self.root_dir, 'config.json.bak')
        
        # 确保根目录存在
        os.makedirs(self.root_dir, exist_ok=True)

    def get_default_config(self):
        """返回一份包含所有默认值的配置字典。"""
        return {
            # 搜索配置
            "search_keywords": "Encrypted Traffic Classification",
            "search_years": ["2025", "2024"],
            # AI模型
            "api_key": "在此处输入您的API密钥",
            "model_name": "gemini-2.5-pro",
            "prompt": """作为资深领域专家，请基于以下框架对提供的研究论文进行深入分析，并提供详细的复现路线图。回答需结构清晰、逻辑严谨、以HTML格式输出，注意美观

一、论文核心解析
1.研究背景
	概述当前领域的主要问题和挑战。
	分析现有方法的局限性及不足。
	阐明论文的研究动机和目标。
2.创新方法
	总结论文提出的核心技术或方法。
	描述方法的整体流程，清晰呈现各阶段。
	突出创新点，说明与现有方法的差异及优势。
3.研究过程
	详细说明实验流程，包括数据准备、预处理、模型构建、训练和评估。
	描述使用的工具、算法和关键实现细节。
4.关键结论
	总结实验结果，量化性能提升（如与基线方法的对比）。
	说明方法的准确率、适用范围及具体效果（如可分类的流量类型）。
	提供论文中报告的定量或定性成果。
5.局限与拓展
	指出论文未解决的问题或方法的局限性。
	提出潜在的改进方向或未来研究建议。
	
二、复现路线图
提供从数据准备到结果复现的详细步骤，确保流程逻辑连贯、操作性强。每一步需包含以下内容：

具体操作：明确描述该步骤的执行内容和方法。
操作目的：解释该步骤的意义及其在整体复现中的作用。
原文依据：标注是否来自论文原文，引用原文内容并附中文翻译。
补充说明：若基于个人理解或扩展，标注“原文未提及”，并提供详细解释。

要求
1.复现流程需细致、具体，确保初学者可按步骤操作。
2.步骤间逻辑连贯，说明每步在整体流程中的定位。
3.回答格式美观，层次分明，使用清晰的段落和编号。
4.若论文未提供，基于上下文合理推测，或请求用户补充论文信息。
5.设计对比类的，能用表格就表格表示，更加清晰
6.在复现过程中，给出一些中间数据的样例，帮助理解过程
7.原文中如果有给出任何源码，请一定要提及
8.以HTML格式输出，注意美观
""",
            # 邮件通知
            "email_sender": "example@qq.com",
            "email_password": "your_app_password",
            "email_receiver": "example@126.com",
            "smtp_server": "smtp.qq.com",
            "smtp_port": 465,
            # 高级设置
            "proxy_enabled": True,
            "proxy_host": "127.0.0.1",
            "proxy_port": 10809,
            "output_dir": os.path.join(self.root_dir, "downloaded_papers"),
            "request_timeout": 300,
            "max_retries": 2
        }

    def load_config(self):
        """加载配置文件，如果文件不存在或无效，则尝试加载备份或返回默认配置。"""
        logger.info(f"Attempting to load config from {self.config_path}")
        
        # 检查主文件是否存在且不为空
        if os.path.exists(self.config_path) and os.path.getsize(self.config_path) > 0:
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info("Config loaded successfully")
                
                # 补全缺失字段
                defaults = self.get_default_config()
                for key, value in defaults.items():
                    config.setdefault(key, value)
                return config
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load config: {e}")
                # 尝试加载备份文件
                if os.path.exists(self.backup_path) and os.path.getsize(self.backup_path) > 0:
                    logger.info(f"Attempting to load backup config from {self.backup_path}")
                    try:
                        with open(self.backup_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                        logger.info("Backup config loaded successfully")
                        # 补全缺失字段
                        defaults = self.get_default_config()
                        for key, value in defaults.items():
                            config.setdefault(key, value)
                        # 恢复主配置文件
                        self.save_config(config)
                        return config
                    except (json.JSONDecodeError, IOError) as e:
                        logger.error(f"Failed to load backup config: {e}")
                # 如果备份也失败，返回默认配置
                logger.warning("Returning default config due to load failure")
                return self.get_default_config()
        else:
            logger.warning(f"Config file {self.config_path} is missing or empty")
            # 尝试加载备份文件
            if os.path.exists(self.backup_path) and os.path.getsize(self.backup_path) > 0:
                logger.info(f"Attempting to load backup config from {self.backup_path}")
                try:
                    with open(self.backup_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    logger.info("Backup config loaded successfully")
                    defaults = self.get_default_config()
                    for key, value in defaults.items():
                        config.setdefault(key, value)
                    self.save_config(config)
                    return config
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Failed to load backup config: {e}")
            logger.warning("Returning default config")
            return self.get_default_config()

    def save_config(self, config):
        """将配置字典保存到JSON文件中，并创建备份。"""
        logger.info(f"Saving config to {self.config_path}")
        try:
            # 创建备份（如果主文件存在且不为空）
            if os.path.exists(self.config_path) and os.path.getsize(self.config_path) > 0:
                shutil.copy2(self.config_path, self.backup_path)
                logger.info(f"Backup created at {self.backup_path}")
            
            # 保存新配置到临时文件
            temp_path = self.config_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            # 验证临时文件是否有效
            with open(temp_path, 'r', encoding='utf-8') as f:
                json.load(f)  # 确保 JSON 有效
            
            # 替换主文件
            os.replace(temp_path, self.config_path)
            logger.info("Config saved successfully")
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to save config: {e}")
            # 如果保存失败，尝试恢复备份
            if os.path.exists(self.backup_path):
                logger.info(f"Restoring backup from {self.backup_path}")
                shutil.copy2(self.backup_path, self.config_path)
            raise IOError(f"Config save failed: {e}")