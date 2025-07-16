# main.py
import os
import json
import re
from datetime import datetime, timezone
import requests
import time
import hashlib
import math
from tqdm import tqdm

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
        pdf_base_dir = os.path.join(config['arxiv_output_dir'], keyword_folder)
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

def _analyze_papers(progress_data, config, progress_callback, progress_file_path, papers_to_process):
    """统一的分析函数，包含智能跳过和即时保存逻辑"""
    if not papers_to_process:
        progress_callback("没有需要分析的论文。")
        return

    progress_callback(f"--- 阶段 3/4: 分析 {len(papers_to_process)} 篇论文 ---")
    if not llm_interface.configure_llm(config, progress_callback):
        return

    for i, paper in enumerate(papers_to_process):
        pdf_path = paper.get('local_path')
        if not pdf_path or not os.path.exists(pdf_path):
            progress_callback(f"  跳过 (PDF文件不存在): {paper.get('title', '未知标题')}")
            continue

        report_filename = f"{os.path.splitext(os.path.basename(pdf_path))[0]}_report.html"
        report_path = os.path.join(os.path.dirname(pdf_path), report_filename)

        # ---【关键修改点】---
        # 修正了这里的同步逻辑
        if os.path.exists(report_path):
            current_status = paper.get('status')
            # 只有当状态不是 'emailed' 时，才进行同步更新
            if current_status != 'emailed':
                progress_callback(f"  发现已存在的报告，正在同步状态: {paper.get('title', '未知标题')}")
                html_md5 = get_file_md5(report_path)
                updates = {'status': 'analyzed', 'analysis_path': report_path, 'html_md5': html_md5}
                update_progress(paper['uid'], updates, progress_data)
                save_progress(progress_file_path, progress_data)
            else:
                 progress_callback(f"  跳过 (报告已存在且已发送邮件): {paper.get('title', '未知标题')}")
            continue # 无论如何都跳过分析

        # 如果报告不存在，则执行分析
        html_report = llm_interface.analyze_paper_by_uploading(pdf_path, paper, progress_callback, {'current': i + 1, 'total': len(papers_to_process)})
        
        updates = {}
        if html_report:
            try:
                with open(report_path, 'w', encoding='utf-8') as f:
                    f.write(html_report)
                html_md5 = get_file_md5(report_path)
                updates = {'status': 'analyzed', 'analysis_path': report_path, 'html_md5': html_md5}
                progress_callback(f"  分析成功: {paper.get('title', '未知标题')}")
            except Exception as e:
                updates = {'status': 'failed', 'failure_reason': f'Report Save Failed: {e}'}
                progress_callback(f"  错误 (保存报告失败): {paper.get('title', '未知标题')}")
        else:
            updates = {'status': 'failed', 'failure_reason': 'LLM Analysis Failed'}
            progress_callback(f"  错误 (AI分析失败): {paper.get('title', '未知标题')}")
        
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
    """完整工作流(ArXiv)：发现->下载->分析->发送"""
    progress_callback("--- 开始执行完整工作流 (ArXiv) ---")
    PROGRESS_FILE = os.path.join(config['root_dir'], 'analysis_progress.json')
    progress_data = load_progress(PROGRESS_FILE)
    
    req_session = requests.Session()
    if config.get('proxy_enabled'):
        proxy_url = f"http://{config['proxy_host']}:{config['proxy_port']}"
        req_session.proxies = {"http": proxy_url, "https": proxy_url}

    _discover_arxiv(progress_data, config, req_session, progress_callback, PROGRESS_FILE)
    _download_discovered(progress_data, config, req_session, progress_callback, PROGRESS_FILE)
    
    papers_to_process = [p for p in progress_data.values() if p.get('source') == 'arXiv' and p.get('status') in ['downloaded', 'failed']]
    _analyze_papers(progress_data, config, progress_callback, PROGRESS_FILE, papers_to_process)
    
    _send_reports(progress_data, config, progress_callback, PROGRESS_FILE)
    progress_callback("--- ArXiv工作流执行完毕 ---")

def run_local_analysis_workflow(config, progress_callback):
    """本地文件夹分析工作流：发现->分析->发送"""
    progress_callback("--- 开始执行本地文件夹分析工作流 ---")
    PROGRESS_FILE = os.path.join(config['root_dir'], 'analysis_progress.json')
    target_folder = config.get('local_scan_dir')
    progress_data = load_progress(PROGRESS_FILE)
    
    if not target_folder or not os.path.isdir(target_folder):
        progress_callback(f"错误：配置中指定的扫描路径无效: {target_folder}")
        return

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
                if not paper_entry or paper_entry.get('status') not in ['analyzed', 'emailed']:
                    updates = {'uid': uid, 'title': os.path.splitext(filename)[0], 'local_path': file_path, 'pdf_md5': pdf_md5, 'status': 'downloaded', 'source': 'Local Folder'}
                    update_progress(uid, updates, progress_data)
                    papers_to_process.append(progress_data[uid])
                    progress_callback(f"  已加入任务队列: {filename}")
                else:
                    progress_callback(f"  已跳过 (已分析过): {filename}")
    
    save_progress(PROGRESS_FILE, progress_data)
    
    _analyze_papers(progress_data, config, progress_callback, PROGRESS_FILE, papers_to_process)
    _send_reports(progress_data, config, progress_callback, PROGRESS_FILE)
    
    progress_callback("--- 本地文件夹分析工作流执行完毕 ---")