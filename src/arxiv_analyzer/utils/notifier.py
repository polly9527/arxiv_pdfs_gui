# notifier.py
import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

EMAIL_CONFIG = {} # 配置将由主逻辑动态注入

def _send_email(subject, body, attachments=None):
    if not all([EMAIL_CONFIG.get(k) for k in ["sender", "password", "receiver", "smtp_server"]]):
        print("邮件配置不完整，无法发送。")
        return False
    msg = MIMEMultipart()
    msg['From'] = EMAIL_CONFIG["sender"]
    msg['To'] = EMAIL_CONFIG["receiver"]
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    if attachments:
        for path in attachments:
            if not os.path.exists(path): continue
            try:
                with open(path, "rb") as f: part = MIMEApplication(f.read(), Name=os.path.basename(path))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
                msg.attach(part)
            except Exception as e: print(f"附加文件 {path} 失败: {e}")
    server = None
    try:
        server = smtplib.SMTP_SSL(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"], timeout=40)
        server.login(EMAIL_CONFIG["sender"], EMAIL_CONFIG["password"])
        server.sendmail(EMAIL_CONFIG["sender"], EMAIL_CONFIG["receiver"], msg.as_string())
        print(f"邮件已成功发送到 {EMAIL_CONFIG['receiver']}")
        return True
    except Exception as e:
        print(f"发送邮件失败: {e}")
        return False
    finally:
        if server: server.quit()

def send_aggregated_report(papers_to_send, group_name, batch_num=1, total_batches=1):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    batch_info = f" (批次 {batch_num}/{total_batches})" if total_batches > 1 else ""
    subject = f"[{group_name}] 新分析报告{batch_info} - {len(papers_to_send)} 篇更新 - {timestamp}"
    body_parts = [
        f"系统为您准备了 [{group_name}] 分组下的 {len(papers_to_send)} 篇新论文分析报告。",
        f"这是 {total_batches} 个批次中的第 {batch_num} 批。",
        "详细的分析报告HTML和论文原文PDF见附件。",
        "\n" + "="*30 + "\n",
        f"--- ✅ 本批次 [{group_name}] 报告列表 ---"
    ]
    for paper in papers_to_send:
        body_parts.append(f"\n- 标题: {paper.get('title', 'N/A')}")
    body = "\n".join(body_parts)
    attachments = []
    for paper in papers_to_send:
        if paper.get('local_path') and os.path.exists(paper['local_path']):
            attachments.append(paper['local_path'])
        if paper.get('analysis_path') and os.path.exists(paper['analysis_path']):
            attachments.append(paper['analysis_path'])
    return _send_email(subject, body, attachments)

def send_no_update_notice():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    subject = f"每日简报 - 无新分析报告 - {timestamp}"
    body = f"系统已于 {timestamp} 完成检查，目前没有新的分析报告需要发送。"
    _send_email(subject, body)