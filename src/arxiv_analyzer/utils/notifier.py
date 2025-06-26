# notifier.py
import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# --- 邮件配置 ---
# 将所有邮件相关配置集中在此模块
EMAIL_CONFIG = {
    "sender": "1477981949@qq.com",          #
    "password": "mopqxqdhfgmqibbg",      #
    "receiver": "hongbin015@126.com",     #
    "smtp_server": "smtp.qq.com",          #
    "smtp_port": 465                       #
}

def _send_email(subject, body, attachments=None):
    """
    私有辅助函数，负责邮件的实际发送过程。
    """
    # 检查配置是否完整
    if not all([EMAIL_CONFIG["sender"], EMAIL_CONFIG["password"], EMAIL_CONFIG["receiver"], EMAIL_CONFIG["smtp_server"]]):
        print("邮件配置不完整，无法发送邮件。")
        return False

    msg = MIMEMultipart()
    msg['From'] = EMAIL_CONFIG["sender"]
    msg['To'] = EMAIL_CONFIG["receiver"]
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    # 处理附件
    if attachments:
        print(f"准备附加 {len(attachments)} 个文件到邮件中...")
        for path in attachments:
            if not os.path.exists(path):
                print(f"  警告: 找不到附件文件 {path}，已跳过。")
                continue
            try:
                with open(path, "rb") as f:
                    # 使用MIMEApplication来处理二进制文件
                    part = MIMEApplication(f.read(), Name=os.path.basename(path))
                # 添加Content-Disposition头，让邮件客户端知道这是一个附件
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
                msg.attach(part)
                print(f"  已附加: {os.path.basename(path)}")
            except Exception as e:
                print(f"附加文件 {path} 失败: {e}")
    
    # 连接SMTP服务器并发送
    server = None
    try:
        print(f"正在连接SMTP服务器 {EMAIL_CONFIG['smtp_server']}...")
        server = smtplib.SMTP_SSL(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"], timeout=20)
        server.login(EMAIL_CONFIG["sender"], EMAIL_CONFIG["password"])
        server.sendmail(EMAIL_CONFIG["sender"], EMAIL_CONFIG["receiver"], msg.as_string())
        print(f"邮件已成功发送到 {EMAIL_CONFIG['receiver']}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("发送邮件失败：SMTP认证失败。请检查您的发件人邮箱和密码/授权码。")
    except Exception as e:
        print(f"发送邮件失败: {e}")
    finally:
        if server:
            server.quit()
    return False

def send_report(total_new, successful_papers, failed_papers):
    """
    发送包含详细分析报告和附件的邮件。
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    subject = f"arXiv每日报告 - {total_new}篇更新 (成功{len(successful_papers)}, 失败{len(failed_papers)}) - {timestamp}"

    # --- 格式化邮件正文 ---
    body_parts = []
    body_parts.append(f"今日共发现 {total_new} 篇新论文。")
    body_parts.append(f"成功分析 {len(successful_papers)} 篇，失败 {len(failed_papers)} 篇。")
    body_parts.append("\n" + "="*30 + "\n")

    if successful_papers:
        body_parts.append("--- ✅ 新增论文分析成功列表 ---\n")
        for paper in successful_papers:
            body_parts.append(f"- {paper.get('title', 'N/A')}\n")

    if failed_papers:
        body_parts.append("\n--- ❌ 新增论文分析失败列表 ---\n")
        for paper in failed_papers:
            body_parts.append(f"- {paper.get('title', 'N/A')}\n")

    body_parts.append("\n--- 📖 所有新论文详情 ---\n")
    all_papers = successful_papers + failed_papers
    for i, paper in enumerate(all_papers, 1):
        body_parts.append(f"\n{i}. 标题: {paper.get('title', 'N/A')}")
        body_parts.append(f"   作者: {paper.get('authors', 'N/A')}")
        body_parts.append(f"   摘要: {paper.get('abstract', 'N/A')}")

    body = "\n".join(body_parts)

    # --- 准备附件列表 ---
    attachments = []
    # 1. 添加所有新论文的原文PDF
    for paper in all_papers:
        if paper.get('local_path'):
            attachments.append(paper['local_path'])
    # 2. 添加所有分析成功的报告HTML
    for paper in successful_papers:
        if paper.get('analysis_path'):
            attachments.append(paper['analysis_path'])
            
    _send_email(subject, body, attachments)

def send_no_update_notice():
    """
    发送一封无更新的通知邮件。
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    subject = f"arXiv每日简报 - 无新文献更新 - {timestamp}"
    body = "系统已于北京时间 " + timestamp + " 完成检查，今日无新文献更新。"
    
    _send_email(subject, body)

# --- 新增的函数 ---
def send_failure_fix_report(fixed_papers):
    """
    当之前失败的论文被成功分析后，发送专门的通知邮件。
    """
    if not fixed_papers:
        return

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    subject = f"分析成功通知 - {len(fixed_papers)}篇先前失败的论文已处理完成 - {timestamp}"

    body_parts = []
    body_parts.append(f"好消息！系统在 {timestamp} 的运行中，已成功分析了 {len(fixed_papers)} 篇先前失败的论文。")
    body_parts.append("详细的分析报告和论文原文见附件。\n")
    body_parts.append("--- ✅ 已修复的论文列表 ---\n")

    for paper in fixed_papers:
        body_parts.append(f"- 标题: {paper.get('title', 'N/A')}")
        body_parts.append(f"  作者: {paper.get('authors', 'N/A')}\n")
    
    body = "\n".join(body_parts)

    # --- 准备附件 (原文PDF + 新的分析报告HTML) ---
    attachments = []
    for paper in fixed_papers:
        if paper.get('local_path'):
            attachments.append(paper['local_path'])
        if paper.get('analysis_path'):
            attachments.append(paper['analysis_path'])

    _send_email(subject, body, attachments)

def send_retry_attempt_report(fixed_papers, still_failing_papers):
    """
    发送关于重试失败任务尝试结果的邮件报告。
    """
    total_attempted = len(fixed_papers) + len(still_failing_papers)
    if total_attempted == 0:
        print("没有需要报告的重试任务。")
        return

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    subject = f"重试任务报告 - 成功修复 {len(fixed_papers)} 篇, 仍失败 {len(still_failing_papers)} 篇 - {timestamp}"

    body_parts = []
    body_parts.append(f"系统于 {timestamp} 完成了一次失败任务重试。")
    body_parts.append(f"共尝试处理 {total_attempted} 篇论文，详情如下：")
    body_parts.append("\n" + "="*30 + "\n")

    # 1. 成功修复的列表
    body_parts.append(f"--- ✅ 成功修复列表 ({len(fixed_papers)}篇) ---")
    if fixed_papers:
        for paper in fixed_papers:
            body_parts.append(f"- {paper.get('title', 'N/A')}")
    else:
        body_parts.append("无")
    
    body_parts.append("\n")

    # 2. 仍旧失败的列表
    body_parts.append(f"--- ❌ 仍失败列表 ({len(still_failing_papers)}篇) ---")
    if still_failing_papers:
        for paper in still_failing_papers:
            body_parts.append(f"- {paper.get('title', 'N/A')}")
    else:
        body_parts.append("无")

    body = "\n".join(body_parts)

    # --- 准备附件 ---
    attachments = []
    # 为成功修复的论文附上PDF和新的分析报告
    for paper in fixed_papers:
        if paper.get('local_path'):
            attachments.append(paper['local_path'])
        if paper.get('analysis_path'):
            attachments.append(paper['analysis_path'])
    
    # 为仍失败的论文附上原文PDF，供手动检查
    for paper in still_failing_papers:
        if paper.get('local_path'):
            attachments.append(paper['local_path'])
            
    _send_email(subject, body, attachments)

    
# --- 用于独立测试本模块的功能 ---
if __name__ == '__main__':
    print("--- notifier.py 模块独立测试 ---")
    
    # 测试3: 测试失败修复的邮件
    print("\n测试3: 发送失败修复通知邮件...")
    fixed_paper_1 = {'title': '已修复的论文A', 'authors': '作者X', 'local_path': 'path/to/dummy_fixed.pdf', 'analysis_path': 'path/to/report_fixed.html'}
    # send_failure_fix_report([fixed_paper_1]) # 取消注释以测试
    
    print("\n测试完成。")