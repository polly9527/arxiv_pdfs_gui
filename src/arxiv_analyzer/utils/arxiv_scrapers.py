# arxiv_scrapers.py
import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

ARXIV_CONFIG = {
    "search_url": "https://arxiv.org/search/?query=Encrypted+Traffic+Classification&searchtype=all&source=header",
    "target_years": ["2025", "2024"]
}

def _extract_submit_date(date_text):
    if not date_text: return None
    pattern = r'Submitted\s+(\d+\s+\w+(?:,\s+|\s+)\d{4})'
    match = re.search(pattern, date_text, re.IGNORECASE)
    if match:
        try:
            date_str = match.group(1).replace(',', '')
            for fmt in ('%d %b %Y', '%d %B %Y'):
                try: return datetime.strptime(date_str, fmt)
                except ValueError: continue
        except Exception: pass
    return None

def fetch_papers(session, progress_callback=None):
    config = ARXIV_CONFIG
    papers_found = []
    page = 1
    
    def log(message):
        if progress_callback: progress_callback(message)
        else: print(message)

    log(f"--- 开始执行 arXiv 爬虫 (URL: {config['search_url']}) ---")

    while True:
        current_url = f"{config['search_url']}&start={(page - 1) * 50}"
        log(f"正在抓取第 {page} 页...")
        try:
            # *** 核心改动：使用传入的 session 对象来发起请求 ***
            response = session.get(current_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            log(f"  错误: 获取第 {page} 页时网络请求失败: {e}")
            break

        soup = BeautifulSoup(response.text, 'html.parser')
        entries = soup.find_all('li', class_='arxiv-result')
        if not entries:
            log("未找到更多论文条目，抓取结束。")
            break

        for entry in entries:
            title_elem = entry.find('p', class_='title is-5 mathjax')
            title = title_elem.text.strip() if title_elem else 'Untitled'

            pdf_elem = entry.find('a', href=True, string='pdf')
            if not pdf_elem:
                log(f"警告: 论文 '{title}' 未找到PDF链接，已跳过。")
                continue

            pdf_url = pdf_elem['href']
            if not pdf_url.startswith('http'): pdf_url = 'https://arxiv.org' + pdf_url

            authors_elem = entry.find('p', class_='authors')
            authors = authors_elem.text.replace('Authors:', '').strip() if authors_elem else 'Unknown'
            comments_elem = entry.find('p', class_='comments')
            comments = comments_elem.text.replace('Comments:', '').strip() if comments_elem else ''
            date_elem = entry.find('p', class_='is-size-7')
            submit_date = _extract_submit_date(date_elem.text if date_elem else '')
            journal_ref = ''
            if date_elem:
                journal_match = re.search(r'Journal ref:\s*([^\n]+)', date_elem.text)
                if journal_match: journal_ref = journal_match.group(1).strip()
            
            abstract_link = entry.find('a', title='Abstract')
            uid = f"arxiv_{abstract_link['href'].split('/')[-1]}" if abstract_link else f"arxiv_{title.lower()[:20]}"

            year = str(submit_date.year) if submit_date else "Unknown_Year"
            if year in config['target_years']:
                papers_found.append({
                    "uid": uid, "title": title, "authors": authors, "abstract": comments,
                    "pdf_url": pdf_url, "submit_date": submit_date, "journal_ref": journal_ref,
                    "source": "arXiv"
                })
        page += 1
        time.sleep(0.5)

    log(f"--- arXiv 爬虫执行完毕，共找到 {len(papers_found)} 篇符合条件的论文 ---")
    return papers_found