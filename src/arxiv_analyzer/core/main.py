# main.py
import os
import json
import re
from datetime import datetime
import requests
import time

from arxiv_analyzer.utils import arxiv_scrapers
from arxiv_analyzer.core import llm_interface
from arxiv_analyzer.utils import notifier
# -------------------------------------------------------------------
# 辅助函数
# -------------------------------------------------------------------

def sanitize_filename(filename):
    """文件名无害化处理，保留大小写。"""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', filename)
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized.strip().strip('_')[:120]

def build_report_index(html_reports_dir):
    """扫描HTML报告目录，为已成功生成的报告建立索引。返回一个字典 {key: path}。"""
    index = {}
    if not os.path.exists(html_reports_dir):
        os.makedirs(html_reports_dir)
        return index
    for filename in os.listdir(html_reports_dir):
        if filename.endswith('_report.html'):
            report_key = filename[:-len('_report.html')]
            index[report_key] = os.path.join(html_reports_dir, filename)
    return index

def download_paper(session, paper_info, base_dir, progress_callback):
    """下载论文并保存。"""
    try:
        title = paper_info.get('title', 'untitled')
        filename = f"{sanitize_filename(title)}.pdf"
        submit_date = paper_info.get('submit_date')
        year_str = str(submit_date.year) if submit_date and isinstance(submit_date, datetime) else "Unknown_Year"
        target_dir = os.path.join(base_dir, year_str)
        os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, filename)

        response = session.get(paper_info['pdf_url'], stream=True, timeout=60)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filepath
    except requests.RequestException as e:
        progress_callback(f"  错误: 下载 '{title}' 时出错: {e}")
        return None
    except Exception as e:
        progress_callback(f"  错误: 保存文件 '{title}' 时出错: {e}")
        return None

def log_failures(failure_log_file, failed_papers, progress_callback):
    """记录分析失败的论文。"""
    if not failed_papers:
        if os.path.exists(failure_log_file):
             open(failure_log_file, 'w').close()
        progress_callback("所有分析均成功，失败日志已清空。")
        return
    progress_callback(f"正在将 {len(failed_papers)} 条失败记录写入 {failure_log_file}...")
    with open(failure_log_file, 'w', encoding='utf-8') as f:
        failures_to_log = []
        for p in failed_papers:
            p_copy = p.copy()
            if 'submit_date' in p_copy and isinstance(p_copy['submit_date'], datetime):
                p_copy['submit_date'] = p_copy['submit_date'].isoformat()
            failures_to_log.append(p_copy)
        json.dump(failures_to_log, f, indent=4, ensure_ascii=False)

def load_emailed_log(emailed_log_file):
    """加载已发送邮件的论文key集合。"""
    if not os.path.exists(emailed_log_file):
        return set()
    try:
        with open(emailed_log_file, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return set()
            return set(json.loads(content))
    except (json.JSONDecodeError, IOError):
        return set()

def update_emailed_log(emailed_log_file, new_keys_to_add):
    """将新发送的论文key添加到日志中。"""
    existing_keys = load_emailed_log(emailed_log_file)
    updated_keys = existing_keys.union(new_keys_to_add)
    with open(emailed_log_file, 'w', encoding='utf-8') as f:
        json.dump(list(updated_keys), f, indent=4, ensure_ascii=False)

# -------------------------------------------------------------------
# 核心工作流函数
# -------------------------------------------------------------------
def run_full_workflow(config, progress_callback):
    progress_callback("--- 开始执行完整工作流 (V2 - 带状态管理) ---")
    
    # --- 1. 路径和配置初始化 ---
    ROOT_DIR, OUTPUT_DIR = config['root_dir'], config['output_dir']
    search_keywords = config.get('search_keywords', 'default_topic')
    keyword_folder_name = sanitize_filename(search_keywords)
    
    PDF_BASE_DIR = os.path.join(OUTPUT_DIR, "download_papers", keyword_folder_name)
    HTML_REPORTS_DIR = os.path.join(OUTPUT_DIR, "html_reports", keyword_folder_name)
    FAILURE_LOG_FILE = os.path.join(ROOT_DIR, 'analysis_failures.json')
    EMAILED_LOG_FILE = os.path.join(ROOT_DIR, 'emailed_log.json') # 状态文件

    os.makedirs(PDF_BASE_DIR, exist_ok=True)
    os.makedirs(HTML_REPORTS_DIR, exist_ok=True)
    
    # 配置网络和LLM
    req_session = requests.Session()
    if config.get('proxy_enabled'):
        proxy_url = f"http://{config['proxy_host']}:{config['proxy_port']}"
        req_session.proxies = {"http": proxy_url, "https": proxy_url}
    llm_interface.configure_llm(config, progress_callback)
    notifier.EMAIL_CONFIG.update({
        "sender": config['email_sender'], 
        "password": config['email_password'], 
        "receiver": config['email_receiver'], 
        "smtp_server": config['smtp_server'], 
        "smtp_port": config['smtp_port']
    })

    # --- 2. 状态恢复与任务识别 ---
    progress_callback("步骤1/5: 检查状态与识别任务...")
    
    all_on_disk_reports = build_report_index(HTML_REPORTS_DIR)
    emailed_report_keys = load_emailed_log(EMAILED_LOG_FILE)
    
    unreported_keys = set(all_on_disk_reports.keys()) - emailed_report_keys
    if unreported_keys:
        progress_callback(f"发现 {len(unreported_keys)} 篇上次成功分析但未发送邮件的论文，将加入本次报告。")

    # 获取在线论文
    arxiv_scrapers.ARXIV_CONFIG['search_url'] = f"https://arxiv.org/search/?query={search_keywords.replace(' ', '+')}&searchtype=all&source=header"
    arxiv_scrapers.ARXIV_CONFIG['target_years'] = config['search_years']
    online_papers = arxiv_scrapers.fetch_papers(req_session, progress_callback)
    
    # 识别全新的、需要分析的论文
    papers_to_analyze = []
    online_papers_map = {sanitize_filename(p['title']): p for p in online_papers}
    
    for key, paper_info in online_papers_map.items():
        if key not in all_on_disk_reports:
             papers_to_analyze.append(paper_info)
    
    progress_callback(f"识别到 {len(papers_to_analyze)} 篇全新论文需要分析。")

    # --- 3. 执行下载和分析 ---
    if not papers_to_analyze:
        progress_callback("步骤2/5: 没有需要分析的新论文，跳过此步骤。")
        newly_successful_analyses, newly_failed_analyses = [], []
    else:
        progress_callback(f"步骤2/5: 开始处理 {len(papers_to_analyze)} 篇新论文...")
        newly_successful_analyses, newly_failed_analyses = [], []
        num_total = len(papers_to_analyze)
        for i, paper in enumerate(papers_to_analyze):
            title = paper.get('title', '未知标题')
            key = sanitize_filename(title)
            
            submit_date = paper.get('submit_date')
            year_str = str(submit_date.year) if submit_date else "Unknown_Year"
            expected_pdf_path = os.path.join(PDF_BASE_DIR, year_str, f"{key}.pdf")
            if os.path.exists(expected_pdf_path):
                 paper['local_path'] = expected_pdf_path
            else:
                pdf_path = download_paper(req_session, paper, PDF_BASE_DIR, progress_callback)
                if pdf_path: paper['local_path'] = pdf_path
                else: continue
            
            task_info = {'current': i + 1, 'total': num_total}
            progress_callback(f"分析中 ({task_info['current']}/{task_info['total']}): {title}")
            html_report = llm_interface.analyze_paper_by_uploading(paper['local_path'], paper, progress_callback, task_info)
            if html_report:
                report_path = os.path.join(HTML_REPORTS_DIR, f"{key}_report.html")
                with open(report_path, 'w', encoding='utf-8') as f: f.write(html_report)
                paper['analysis_path'] = report_path
                newly_successful_analyses.append(paper)
            else:
                newly_failed_analyses.append(paper)

    # --- 4. 整合报告内容并发送邮件 ---
    progress_callback("步骤3/5: 整合报告内容...")
    
    unreported_papers_from_disk = []
    for key in unreported_keys:
        if key in online_papers_map:
            paper_info = online_papers_map[key]
            paper_info['analysis_path'] = all_on_disk_reports[key]
            unreported_papers_from_disk.append(paper_info)
        else:
            unreported_papers_from_disk.append({'title': key.replace('_', ' '), 'analysis_path': all_on_disk_reports[key]})
            
    all_successful_for_email = unreported_papers_from_disk + newly_successful_analyses
    
    if not all_successful_for_email and not newly_failed_analyses:
        progress_callback("步骤4/5: 无任何成功或失败的论文可供报告。")
        try:
            progress_callback("正在发送“无更新”通知邮件...")
            notifier.send_no_update_notice()
            progress_callback("邮件已发送。")
        except Exception as e:
            progress_callback(f"错误: 发送“无更新”邮件时失败: {e}")
    else:
        progress_callback(f"步骤4/5: 准备发送包含 {len(all_successful_for_email)} 篇成功和 {len(newly_failed_analyses)} 篇失败论文的邮件...")
        try:
            notifier.send_report(len(all_successful_for_email), all_successful_for_email, newly_failed_analyses)
            progress_callback("邮件已发送。")

            # --- 5. 更新状态 ---
            progress_callback("步骤5/5: 更新已发送邮件日志...")
            keys_to_log_as_emailed = {sanitize_filename(p['title']) for p in all_successful_for_email}
            update_emailed_log(EMAILED_LOG_FILE, keys_to_log_as_emailed)
            progress_callback("状态更新完成。")

        except Exception as e:
            progress_callback(f"错误：发送邮件或更新日志失败: {e}")
            progress_callback("警告：由于发送失败，本次成功的论文将在下次被重新报告。")

    # 记录本次运行中新产生的失败
    log_failures(FAILURE_LOG_FILE, newly_failed_analyses, progress_callback)
    progress_callback("--- 完整工作流执行完毕 ---")