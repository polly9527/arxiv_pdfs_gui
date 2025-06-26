# llm_interface.py
import os
import time
import httpx
import google.generativeai as genai

API_KEY = ""
GEMINI_MODEL_NAME = ""
PROMPT_TEMPLATE = ""
MAX_RETRIES = 2
REQUEST_TIMEOUT = 300

def configure_llm(config, progress_callback):
    global API_KEY, GEMINI_MODEL_NAME, PROMPT_TEMPLATE, MAX_RETRIES, REQUEST_TIMEOUT
    API_KEY = config.get('api_key')
    GEMINI_MODEL_NAME = config.get('model_name', 'gemini-2.5-pro')
    PROMPT_TEMPLATE = config.get('prompt', '')
    MAX_RETRIES = config.get('max_retries', 2)
    REQUEST_TIMEOUT = config.get('request_timeout', 300)

    if not API_KEY or "YOUR_API_KEY" in API_KEY or "在此处输入您" in API_KEY:
        if progress_callback:
            progress_callback("LLM接口模块：错误 - 未在UI中配置有效的API密钥。")
        return False
    try:
        genai.configure(api_key=API_KEY)
        if progress_callback:
            progress_callback("LLM接口模块：Gemini AI 已成功配置 API Key。代理将通过环境变量自动应用。")
        return True
    except Exception as e:
        if progress_callback:
            progress_callback(f"LLM接口模块：Gemini AI 配置失败: {e}")
        return False


def analyze_paper_by_uploading(pdf_path, metadata, progress_callback=None, task_info=None):
    """
    上传指定的PDF文件，使用Gemini进行分析，并返回HTML格式的报告。
    该函数包含完整的重试、进度跟踪和清理逻辑。
    """
    def log(message):
        if progress_callback:
            progress_callback(message)
        else:
            print(message)

    title_for_display = metadata.get('title', os.path.basename(pdf_path))
    log(f"--- 准备上传和分析PDF: {title_for_display} ---")

    uploaded_file = None
    try:
        # ... (文件上传和模型创建逻辑保持不变, 此处省略以保持简洁) ...
        for attempt in range(MAX_RETRIES + 1):
            try:
                log(f"  正在上传文件: {os.path.basename(pdf_path)}... (尝试 {attempt + 1}/{MAX_RETRIES + 1})")
                uploaded_file = genai.upload_file(path=pdf_path, display_name=title_for_display)
                log(f"  文件上传成功。URI: {uploaded_file.uri}")
                break
            except Exception as e:
                log(f"  错误: 文件上传失败: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(3)
                else:
                    log(f"  文件上传已达到最大重试次数，分析失败。")
                    return None
        
        if not uploaded_file:
            return None

        try:
            model_name_for_api = f"models/{GEMINI_MODEL_NAME}"
            model = genai.GenerativeModel(model_name_for_api)
        except Exception as e:
            log(f"  创建Gemini模型 '{GEMINI_MODEL_NAME}' 失败: {e}")
            return None
        
        # --- 3. 调用API进行分析 (实现周期性日志) ---
        response_text = ""
        prompt_parts = [PROMPT_TEMPLATE, uploaded_file]
        for attempt in range(MAX_RETRIES + 1):
            try:
                log(f"  向 Gemini 发送流式分析请求 (尝试 {attempt + 1}/{MAX_RETRIES + 1})...")
                
                # ### 核心修改：移除 stream_progress 信号，改为周期性打印日志 ###
                # 通知UI进入“繁忙”模式
                if progress_callback:
                    progress_callback({"type": "stream_start"})

                response = model.generate_content(prompt_parts, request_options={"timeout": REQUEST_TIMEOUT}, stream=True)
                
                start_time = time.time()
                total_chars = 0
                
                last_log_time = start_time
                LOG_INTERVAL = 10  # 每10秒记录一次日志

                for chunk in response:
                    total_chars += len(chunk.text)
                    response_text += chunk.text
                    
                    current_time = time.time()
                    if current_time - last_log_time >= LOG_INTERVAL:
                        log(f"  [进度] 已接收 {total_chars:,} 字符...")
                        last_log_time = current_time

                # 在结束后，发送包含最终统计的 'stream_end' 信号
                final_elapsed_time = time.time() - start_time
                if progress_callback:
                    progress_callback({
                        "type": "stream_end",
                        "total_chars": total_chars,
                        "elapsed_time": final_elapsed_time,
                        "current_task": task_info.get('current', 1) if task_info else 1,
                        "total_tasks": task_info.get('total', 1) if task_info else 1
                    })

                response_text = response_text.strip().removeprefix("```html").removesuffix("```")
                return response_text

            except Exception as e:
                log(f"  调用 Gemini API 时出错: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(5)
                else:
                    log(f"  '{title_for_display}' 已达到最大重试次数，分析失败。")
                    return None
    finally:
        # --- 4. 清理云端文件 ---
        # 无论成功、失败或取消，只要文件已上传，就尝试删除
        if uploaded_file:
            log(f"  分析流程结束，正在从云端删除临时文件: {uploaded_file.display_name}...")
            try:
                genai.delete_file(uploaded_file.name)
                log(f"  临时文件删除成功。")
            except Exception as e:
                log(f"  警告：删除云端文件时发生错误: {e}")