# main.py
import os
import json
import re
from datetime import datetime, timezone
import requests
import time
import hashlib
import math

from arxiv_analyzer.utils import arxiv_scrapers
from arxiv_analyzer.core import llm_interface
from arxiv_analyzer.utils import notifier

# --- 辅助函数 ---
def get_file_md5(file_path):
    """计算文件的MD5哈希值"""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except IOError:
        return None

def get_string_md5(text):
    """计算字符串的MD5哈希值"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def sanitize_filename(filename):
    """文件名无害化处理，保留大小写"""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', filename)
    return re.sub(r'_+', '_', sanitized).strip().strip('_')[:120]

def load_progress(progress_file):
    """加载进度文件，如果不存在或无效则返回空字典"""
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_progress(progress_file, progress_data):
    """保存进度到JSON文件，并处理datetime对象"""
    def dt_converter(o):
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress_data, f, indent=4, ensure_ascii=False, default=dt_converter)

def update_progress(uid, updates, progress_data):
    """使用新信息更新指定UID的条目"""
    if uid not in progress_data:
        progress_data[uid] = {}
    if updates.get('status') == 'analyzed' and progress_data[uid].get('status') != 'analyzed':
        updates['email_sent'] = False
        if 'first_success_timestamp' not in progress_data[uid]:
            updates['first_success_timestamp'] = datetime.now(timezone.utc).isoformat()
    progress_data[uid].update(updates)

def download_paper(session, paper_info, base_dir, progress_callback):
    """下载论文并保存，健壮地处理日期类型"""
    try:
        title = paper_info.get('title', 'untitled')
        filename = f"{sanitize_filename(title)}.pdf"
        submit_date_value = paper_info.get('submit_date')
        year_str = "Unknown_Year"
        if isinstance(submit_date_value, datetime):
            year_str = str(submit_date_value.year)
        elif isinstance(submit_date_value, str):
            try:
                dt_obj = datetime.fromisoformat(submit_date_value)
                year_str = str(dt_obj.year)
            except (ValueError, TypeError):
                pass
        target_dir = os.path.join(base_dir, year_str)
        os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, filename)
        if os.path.exists(filepath):
            progress_callback(f"  文件已存在，跳过下载: {filename}")
            return filepath
        response = session.get(paper_info['pdf_url'], stream=True, timeout=60)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        progress_callback(f"  下载成功: {filename}")
        return filepath
    except requests.RequestException as e:
        progress_callback(f"  错误: 下载 '{title}' 时出错: {e}")
        return None
    except Exception as e:
        progress_callback(f"  错误: 保存文件 '{title}' 时出错: {e}")
        return None

# --- 工作流的阶段性函数 ---

def _discover_arxiv(progress_data, config, session, progress_callback, progress_file_path):
    progress_callback("--- 阶段 1/4: 发现 ArXiv 新论文 ---")
    arxiv_scrapers.ARXIV_CONFIG['target_years'] = config['search_years']
    newly_discovered_count = 0
    for keyword in config.get('search_keyword_list', []):
        progress_callback(f"\n正在为关键词 '{keyword}' 搜索...")
        arxiv_scrapers.ARXIV_CONFIG['search_url'] = f"https://arxiv.org/search/?query={keyword.replace(' ', '+')}&searchtype=all&source=header"
        online_papers = arxiv_scrapers.fetch_papers(session, progress_callback)
        for paper in online_papers:
            if paper['uid'] not in progress_data:
                paper.update({'status': 'discovered', 'url_md5': get_string_md5(paper['pdf_url']), 'source_keyword': keyword})
                update_progress(paper['uid'], paper, progress_data)
                progress_callback(f"  发现新论文: {paper['title']}")
                newly_discovered_count += 1
    if newly_discovered_count > 0:
        progress_callback(f"发现 {newly_discovered_count} 篇新论文，正在保存进度...")
        save_progress(progress_file_path, progress_data)

def _download_discovered(progress_data, config, session, progress_callback, progress_file_path):
    progress_callback("--- 阶段 2/4: 下载新发现的论文 ---")
    papers_to_download = [p for p in progress_data.values() if p.get('status') == 'discovered']
    if not papers_to_download:
        progress_callback("没有需要下载的论文。")
        return
    progress_callback(f"准备下载 {len(papers_to_download)} 篇论文...")
    for paper in papers_to_download:
        keyword_folder = sanitize_filename(paper.get('source_keyword', 'default'))
        # ---【使用新的ArXiv输出目录配置】---
        pdf_base_dir = os.path.join(config['arxiv_output_dir'], "download_papers", keyword_folder)
        pdf_path = download_paper(session, paper, pdf_base_dir, progress_callback)
        updates = {}
        if pdf_path:
            pdf_md5 = get_file_md5(pdf_path)
            updates = {'status': 'downloaded', 'local_path': pdf_path, 'pdf_md5': pdf_md5}
        else:
            updates = {'status': 'failed', 'failure_reason': 'Download Failed'}
        update_progress(paper['uid'], updates, progress_data)
        save_progress(progress_file_path, progress_data)
    progress_callback("下载阶段完成。")

def _sync_existing_reports(progress_data, config, progress_callback, progress_file_path):
    progress_callback("--- 同步阶段: 检查已存在的HTML报告 ---")
    papers_to_check = [p for p in progress_data.values() if p.get('status') in ['discovered', 'downloaded']]
    synced_count = 0
    for paper in papers_to_check:
        keyword_folder = sanitize_filename(paper.get('source_keyword', 'default_topic'))
        year_str = "Unknown_Year"
        submit_date_value = paper.get('submit_date')
        if isinstance(submit_date_value, datetime): year_str = str(submit_date_value.year)
        elif isinstance(submit_date_value, str):
            try: year_str = str(datetime.fromisoformat(submit_date_value).year)
            except (ValueError, TypeError): pass
        # ---【使用新的ArXiv输出目录配置】---
        html_dir = os.path.join(config['arxiv_output_dir'], "html_reports", keyword_folder, year_str)
        report_filename = f"{sanitize_filename(paper['title'])}_report.html"
        expected_report_path = os.path.join(html_dir, report_filename)
        if os.path.exists(expected_report_path):
            html_md5 = get_file_md5(expected_report_path)
            updates = {'status': 'analyzed', 'analysis_path': expected_report_path, 'html_md5': html_md5}
            update_progress(paper['uid'], updates, progress_data)
            synced_count += 1
            progress_callback(f"  发现并同步已存在的报告: {paper['title']}")
    if synced_count > 0:
        progress_callback(f"同步了 {synced_count} 个已存在的报告，正在保存进度...")
        save_progress(progress_file_path, progress_data)
    else:
        progress_callback("没有发现可同步的旧报告。")

def _analyze_downloaded(progress_data, config, progress_callback, progress_file_path):
    progress_callback("--- 阶段 3/4: 分析已下载的论文 ---")
    if not llm_interface.configure_llm(config, progress_callback):
        return
    papers_to_analyze = [p for p in progress_data.values() if p.get('local_path') and p.get('status') in ['downloaded', 'failed']]
    if not papers_to_analyze:
        progress_callback("没有需要分析的论文。")
        return
    progress_callback(f"准备分析 {len(papers_to_analyze)} 篇论文...")
    for i, paper in enumerate(papers_to_analyze):
        html_report = llm_interface.analyze_paper_by_uploading(paper['local_path'], paper, progress_callback, {'current': i + 1, 'total': len(papers_to_analyze)})
        updates = {}
        if html_report:
            keyword_folder = sanitize_filename(paper.get('source_keyword', 'default_topic'))
            year_str = "Unknown_Year"
            submit_date_value = paper.get('submit_date')
            if isinstance(submit_date_value, datetime): year_str = str(submit_date_value.year)
            elif isinstance(submit_date_value, str):
                try: year_str = str(datetime.fromisoformat(submit_date_value).year)
                except (ValueError, TypeError): pass
            # ---【使用新的ArXiv输出目录配置】---
            html_dir = os.path.join(config['arxiv_output_dir'], "html_reports", keyword_folder, year_str)
            os.makedirs(html_dir, exist_ok=True)
            report_filename = f"{sanitize_filename(paper['title'])}_report.html"
            report_path = os.path.join(html_dir, report_filename)
            try:
                with open(report_path, 'w', encoding='utf-8') as f: f.write(html_report)
                html_md5 = get_file_md5(report_path)
                updates = {'status': 'analyzed', 'analysis_path': report_path, 'html_md5': html_md5}
            except Exception as e:
                updates = {'status': 'failed', 'failure_reason': f'Report Save Failed: {e}'}
        else:
            updates = {'status': 'failed', 'failure_reason': 'LLM Analysis Failed'}
        update_progress(paper['uid'], updates, progress_data)
        save_progress(progress_file_path, progress_data)
    progress_callback("分析阶段完成。")

def _send_reports(progress_data, config, progress_callback, progress_file_path):
    progress_callback("--- 阶段 4/4: 检查并发送邮件报告 ---")
    notifier.EMAIL_CONFIG.update({
        "sender": config['email_sender'], "password": config['email_password'], 
        "receiver": config['email_receiver'], "smtp_server": config['smtp_server'], 
        "smtp_port": config['smtp_port']
    })
    reports_to_send = [p for p in progress_data.values() if p.get('status') == 'analyzed' and not p.get('email_sent')]
    if not reports_to_send:
        progress_callback("没有新的分析报告需要发送。")
        notifier.send_no_update_notice()
        return
    ieee_reports, other_arxiv_reports, local_reports = [], [], []
    for paper in reports_to_send:
        source = paper.get('source', 'Unknown')
        if source == 'arXiv':
            if 'ieee' in paper.get('abstract', '').lower(): ieee_reports.append(paper)
            else: other_arxiv_reports.append(paper)
        elif source == 'Local Folder': local_reports.append(paper)
    _process_and_send_group(ieee_reports, "ArXiv - IEEE", progress_data, progress_callback, progress_file_path)
    _process_and_send_group(other_arxiv_reports, "ArXiv - Other", progress_data, progress_callback, progress_file_path)
    _process_and_send_group(local_reports, "Local Folder", progress_data, progress_callback, progress_file_path)

def _process_and_send_group(report_group, group_name, progress_data, progress_callback, progress_file_path):
    if not report_group:
        progress_callback(f"分组 [{group_name}] 中没有需要发送的报告。")
        return True
    batch_size = 20
    total_batches = math.ceil(len(report_group) / batch_size)
    progress_callback(f"\n发现 {len(report_group)} 份 [{group_name}] 报告，将分 {total_batches} 批发次发送。")
    for i in range(total_batches):
        current_batch = report_group[i*batch_size:(i+1)*batch_size]
        batch_num = i + 1
        progress_callback(f"--- 正在处理分组 [{group_name}] 的批次 {batch_num}/{total_batches} ---")
        success = notifier.send_aggregated_report(current_batch, group_name, batch_num, total_batches)
        if success:
            progress_callback(f"批次 {batch_num} 发送成功，更新进度...")
            for paper in current_batch:
                update_progress(paper['uid'], {'status': 'emailed', 'email_sent': True}, progress_data)
            save_progress(progress_file_path, progress_data)
        else:
            progress_callback(f"批次 {batch_num} 发送失败，中止 [{group_name}] 分组的邮件发送。")
            return False
    return True

# --- 主工作流入口 ---

def run_full_workflow(config, progress_callback):
    """完整工作流(ArXiv)：发现->下载->同步->分析->发送"""
    progress_callback("--- 开始执行完整工作流 (ArXiv) ---")
    PROGRESS_FILE = os.path.join(config['root_dir'], 'analysis_progress.json')
    progress_data = load_progress(PROGRESS_FILE)
    req_session = requests.Session()
    if config.get('proxy_enabled'):
        proxy_url = f"http://{config['proxy_host']}:{config['proxy_port']}"
        req_session.proxies = {"http": proxy_url, "https": proxy_url}

    _discover_arxiv(progress_data, config, req_session, progress_callback, PROGRESS_FILE)
    _download_discovered(progress_data, config, req_session, progress_callback, PROGRESS_FILE)
    _sync_existing_reports(progress_data, config, progress_callback, PROGRESS_FILE)
    _analyze_downloaded(progress_data, config, progress_callback, PROGRESS_FILE)
    _send_reports(progress_data, config, progress_callback, PROGRESS_FILE)

    progress_callback("--- ArXiv工作流执行完毕 ---")


def run_local_analysis_workflow(config, progress_callback):
    """本地文件夹分析工作流：发现->分析->发送"""
    progress_callback("--- 开始执行本地文件夹分析工作流 ---")
    PROGRESS_FILE = os.path.join(config['root_dir'], 'analysis_progress.json')
    # ---【使用新的本地扫描目录配置】---
    target_folder = config.get('local_scan_dir')
    progress_data = load_progress(PROGRESS_FILE)
    
    if not target_folder or not os.path.isdir(target_folder):
        progress_callback(f"错误：配置中指定的扫描路径无效: {target_folder}")
        return

    # 1. 发现本地文件并检查状态
    progress_callback(f"--- 阶段 1/3: 扫描文件夹 {target_folder} ---")
    papers_to_process = []
    for root, _, files in os.walk(target_folder):
        for filename in files:
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(root, filename)
                pdf_md5 = get_file_md5(file_path)
                if not pdf_md5: continue
                uid = f"local_{pdf_md5}"
                paper_entry = progress_data.get(uid)
                if paper_entry and paper_entry.get('status') in ['analyzed', 'emailed']:
                    progress_callback(f"  已跳过 (已分析): {filename}")
                    continue
                updates = {'uid': uid, 'title': os.path.splitext(filename)[0], 'local_path': file_path, 'pdf_md5': pdf_md5, 'status': 'downloaded', 'source': 'Local Folder'}
                update_progress(uid, updates, progress_data)
                papers_to_process.append(progress_data[uid])
                progress_callback(f"  已加入任务队列: {filename}")
    save_progress(PROGRESS_FILE, progress_data)

    if not papers_to_process:
        progress_callback("扫描完成，没有需要分析的新文件。")
    else:
        # 2. 分析新发现的本地文件
        progress_callback(f"--- 阶段 2/3: 分析 {len(papers_to_process)} 个本地文件 ---")
        if not llm_interface.configure_llm(config, progress_callback):
            return
        for i, paper in enumerate(papers_to_process):
            html_report = llm_interface.analyze_paper_by_uploading(paper['local_path'], paper, progress_callback, {'current': i + 1, 'total': len(papers_to_process)})
            updates = {}
            if html_report:
                pdf_dir = os.path.dirname(paper['local_path'])
                report_filename = f"{os.path.splitext(os.path.basename(paper['local_path']))[0]}_report.html"
                report_path = os.path.join(pdf_dir, report_filename)
                try:
                    with open(report_path, 'w', encoding='utf-8') as f: f.write(html_report)
                    html_md5 = get_file_md5(report_path)
                    updates = {'status': 'analyzed', 'analysis_path': report_path, 'html_md5': html_md5}
                except Exception as e:
                    updates = {'status': 'failed', 'failure_reason': f'Report Save Failed: {e}'}
            else:
                updates = {'status': 'failed', 'failure_reason': 'LLM Analysis Failed'}
            update_progress(paper['uid'], updates, progress_data)
            save_progress(PROGRESS_FILE, progress_data)

    # 3. 发送邮件 (无论有无新分析，都检查是否有待发送)
    progress_callback("--- 阶段 3/3: 检查并发送邮件报告 ---")
    _send_reports(progress_data, config, progress_callback, PROGRESS_FILE)
    
    progress_callback("--- 本地文件夹分析工作流执行完毕 ---")