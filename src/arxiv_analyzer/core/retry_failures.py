# retry_failures.py
import os
import json
import re
import time
from datetime import datetime

from arxiv_analyzer.core import llm_interface
from arxiv_analyzer.utils import notifier
# -------------------------------------------------------------------
# 辅助函数
# -------------------------------------------------------------------
def sanitize_filename(filename):
    """文件名无害化处理。"""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', filename)
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized.strip().strip('_').lower()[:120]

def load_failures_to_retry(failure_file, progress_callback):
    """从JSON文件加载失败的论文列表以供重试。"""
    if not os.path.exists(failure_file):
        progress_callback(f"错误: 失败日志文件 {failure_file} 不存在。")
        return []
    try:
        with open(failure_file, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content: return []
            failed_papers = json.loads(content)
        
        valid_failures = []
        for paper in failed_papers:
            if paper.get('local_path') and os.path.exists(paper['local_path']):
                if 'submit_date' in paper and isinstance(paper['submit_date'], str):
                    try: paper['submit_date'] = datetime.fromisoformat(paper['submit_date'])
                    except (ValueError, TypeError): paper['submit_date'] = None
                valid_failures.append(paper)
            else:
                progress_callback(f"警告: 失败记录中的文件路径已失效，将跳过: {paper.get('title')}")
        return valid_failures
    except (json.JSONDecodeError, IOError) as e:
        progress_callback(f"读取或解析失败记录文件 {failure_file} 时出错: {e}")
        return []

def update_failure_log(failure_log_file, failed_papers, progress_callback):
    """用仍然失败的论文列表更新日志文件。"""
    if not failed_papers:
        if os.path.exists(failure_log_file): open(failure_log_file, 'w').close()
        progress_callback(f"所有任务均已成功修复，失败日志 {failure_log_file} 已清空。")
        return
    
    progress_callback(f"正在将 {len(failed_papers)} 条仍然失败的记录更新回 {failure_log_file}...")
    with open(failure_log_file, 'w', encoding='utf-8') as f:
        failures_to_log = []
        for p in failed_papers:
            p_copy = p.copy()
            if 'submit_date' in p_copy and isinstance(p_copy['submit_date'], datetime):
                p_copy['submit_date'] = p_copy['submit_date'].isoformat()
            failures_to_log.append(p_copy)
        json.dump(failures_to_log, f, indent=4, ensure_ascii=False)

# -------------------------------------------------------------------
# 核心工作流函数
# -------------------------------------------------------------------
def run_retry_workflow(config, progress_callback):
    progress_callback("--- 开始执行“仅重试失败”任务 ---")
    
    # --- 1. 初始化和配置 ---
    ROOT_DIR = config['root_dir']
    OUTPUT_DIR = config.get('output_dir', os.path.join(ROOT_DIR, "downloaded_papers"))
    FAILURE_LOG_FILE = os.path.join(ROOT_DIR, 'analysis_failures.json')

    # 配置LLM接口
    if not llm_interface.configure_llm(config, progress_callback):
        progress_callback("LLM接口配置失败，中止任务。")
        return
        
    # 配置邮件通知器
    notifier.EMAIL_CONFIG.update({
        "sender": config['email_sender'], 
        "password": config['email_password'], 
        "receiver": config['email_receiver'], 
        "smtp_server": config['smtp_server'], 
        "smtp_port": config['smtp_port']
    })

    # --- 2. 加载待办任务 ---
    papers_to_retry = load_failures_to_retry(FAILURE_LOG_FILE, progress_callback)
    if not papers_to_retry:
        progress_callback("成功：失败日志中没有需要重试的任务。")
        # 即使没有任务，也发送一封通知邮件
        notifier.send_retry_attempt_report([], [])
        return
        
    progress_callback(f"信息：从失败日志中加载了 {len(papers_to_retry)} 篇论文准备重试。")
    
    # 根据关键词动态创建HTML报告目录
    search_keywords = config.get('search_keywords', 'default_topic')
    keyword_folder_name = sanitize_filename(search_keywords)
    HTML_REPORTS_DIR = os.path.join(config.get('output_dir', ROOT_DIR), "html_reports", keyword_folder_name)
    os.makedirs(HTML_REPORTS_DIR, exist_ok=True)
    
    if not config['api_key'] or "YOUR_API_KEY" in config['api_key']:
        progress_callback("错误：未配置有效的API密钥，无法执行分析。")
        return

    # --- 3. 执行重试分析 ---
    fixed_analyses, still_failing_analyses = [], []
    num_total = len(papers_to_retry)
    for i, paper in enumerate(papers_to_retry):
        title = paper.get('title', '未知标题')
        task_info = {'current': i + 1, 'total': num_total}
        progress_callback(f"重试中 ({task_info['current']}/{task_info['total']}): {title}")
        
        html_report = llm_interface.analyze_paper_by_uploading(paper['local_path'], paper, progress_callback, task_info)
        
        if html_report:
            report_path = os.path.join(HTML_REPORTS_DIR, f"{sanitize_filename(title)}_report.html")
            try:
                with open(report_path, 'w', encoding='utf-8') as f:
                    f.write(html_report)
                paper['analysis_path'] = report_path
                fixed_analyses.append(paper)
                progress_callback(f"  -> 修复成功！报告已保存。")
            except Exception as e:
                progress_callback(f"  -> 错误: 保存HTML报告失败: {e}")
                still_failing_analyses.append(paper)
        else:
            progress_callback(f"  -> 修复失败，将保留在失败日志中。")
            still_failing_analyses.append(paper)

    # --- 4. 更新失败日志并发送最终邮件通知 ---
    progress_callback("\n" + "="*40)
    progress_callback(f"--- 重试任务完成 ---")
    progress_callback(f"成功修复: {len(fixed_analyses)} 篇 | 仍有 {len(still_failing_analyses)} 篇失败")
    
    # 用仍然失败的论文列表更新日志文件
    update_failure_log(FAILURE_LOG_FILE, still_failing_analyses, progress_callback)
    
    # 发送最终的邮件报告
    progress_callback("正在准备并发送最终的邮件通知...")
    try:
        notifier.send_retry_attempt_report(fixed_analyses, still_failing_analyses)
        progress_callback("邮件通知已成功发送。")
    except Exception as e:
        progress_callback(f"错误: 发送邮件通知时发生异常: {e}")


if __name__ == '__main__':
    print("这是一个功能模块，请通过 gui_main.py 运行。")