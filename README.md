ArXiv AI 分析器 (ArXiv AI Analyzer)
一个功能强大且带有图形用户界面（GUI）的自动化工具，旨在帮助科研人员和开发者追踪、分析和总结特定领域的最新 arXiv 论文，或批量处理本地PDF文件。本工具深度集成了 Google Gemini 模型，能够将复杂的学术论文转化为结构清晰、内容详尽的 HTML 分析报告，并通过邮件自动推送给您。

📸 项目截图
docs/images/screenshot.png

✨ 主要功能
🚀 双模工作流:

ArXiv工作流: 根据您设定的关键词和年份，自动从 arXiv 网站抓取最新的论文列表进行处理。

分析本地文件夹: 递归扫描您指定的本地文件夹，对其中所有的PDF文件进行批量分析。

🧠 Gemini 驱动的深度分析: 利用 Google Gemini 的强大能力，对每篇论文进行深度剖析，生成包含核心解析和复现路线图的详细 HTML 报告。

🖥️ 友好的图形用户界面: 基于 PyQt6 构建了现代化且易于操作的用户界面，让您可以轻松配置所有参数，包括搜索、AI 模型、邮件、代理和定时任务。

📧 智能邮件通知:

自动将新生成的分析报告（HTML）和论文原文（PDF）打包，通过邮件发送。

支持分类发送：可将摘要中含 "IEEE" 的论文与其它论文分开发送。

支持分批发送：当报告数量过多时，会自动切割成每20份报告一封邮件，避免附件过大。

⏰ Windows 定时任务: 可直接在 GUI 中创建、管理和删除 Windows 系统级别的定时任务，实现无人值守的自动化运行。

💪 极其健壮的执行流程:

统一状态管理: 使用单一的 analysis_progress.json 文件，精确追踪每一篇论文从“被发现”到“已邮件报告”的完整生命周期。

基于MD5的防重机制: 通过计算PDF文件的MD5哈希值作为唯一标识，彻底避免了因文件名、来源不同而导致的重复分析。

断点续传与即时保存: 所有进度都即时保存，即使程序意外中断，下次运行时也能从断点处继续，不会丢失已完成的工作。

支持通过 HTTP/HTTPS 代理进行网络访问。

📂 项目结构
本项目采用了清晰的模块化结构，便于维护和二次开发。

/arxiv_ai_analyzer/
├── src/
│   └── arxiv_analyzer/
│       ├── __init__.py
│       ├── gui/            # GUI 相关模块 (main_window.py, worker.py)
│       ├── core/           # 核心工作流模块 (main.py)
│       ├── utils/          # 工具类模块 (config_manager.py, notifier.py, arxiv_scrapers.py)
│       └── cli/            # 命令行/后台任务模块 (scheduler_manager.py)
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt
└── gui_main.py             # 主程序入口

🚀 快速开始
请遵循以下步骤在您的本地环境中运行本项目。

1. 克隆项目
git clone https://github.com/YOUR_USERNAME/arxiv_ai_analyzer.git
cd arxiv_ai_analyzer

2. 安装依赖
建议在 Python 虚拟环境中安装项目所需的依赖。

pip install -r requirements.txt

(注: 如果 requirements.txt 文件不存在，您可以通过 pip freeze > requirements.txt 命令在您的环境中生成。)

3. 运行并配置
本应用的所有配置都通过图形界面完成，无需手动编辑JSON文件。

首次启动程序:

python gui_main.py

程序将在项目根目录自动创建一个 config.json 文件。

关键配置:

输入API Key: 打开应用后，进入 "AI 模型" 标签页，在 "Gemini API Key" 输入框中填入您的 Google Gemini API 密钥。

设置邮箱: 进入 "邮件通知" 标签页，填入您的发件人邮箱、授权码（注意：不是邮箱登录密码）和收件人邮箱。

指定路径: 进入 "高级设置 & 路径" 标签页，为“完整工作流”和“分析本地文件夹”两个功能分别指定目录。

完成！ 现在您可以开始使用各项功能了。所有设置都会在修改后自动保存。

🛠️ 使用说明
图形界面模式 (GUI)
直接运行 gui_main.py 即可打开主窗口。您可以在不同的标签页中完成所有配置，然后点击 "完整工作流 (ArXiv)" 或 "分析本地文件夹" 按钮来启动相应的任务。所有日志将实时显示在下方的文本框中。

无界面后台模式 (Headless)
如果您希望通过脚本或定时任务在后台运行 ArXiv完整工作流，可以使用 --run-task 参数。这在服务器上部署时尤其有用。

python gui_main.py --run-task

此命令将直接执行一次“完整工作流”，并将所有日志打印到控制台。

⚙️ 配置说明
所有配置项都可以在图形界面中设置。本节内容仅供参考，或用于手动编辑 config.json 文件。

search_keyword_list: (搜索配置) 您关心的研究领域关键词列表。

search_years: (搜索配置) 希望抓取的论文发表年份列表。

api_key: (AI 模型) Gemini API 密钥。

model_name: (AI 模型) 使用的 Gemini 模型，例如 gemini-2.5-pro。

prompt: (AI 模型) 对 AI下达的核心指令，您可以根据需求进行微调。

email_*: (邮件通知) 邮件通知相关配置。

proxy_*: (高级设置) 网络代理配置。

arxiv_output_dir: (高级设置) “完整工作流”下载的论文和报告的存放路径。

local_scan_dir: (高级设置) “分析本地文件夹”功能要扫描的源文件夹路径。

schedule_*: (自动任务) Windows 定时任务相关配置。

📝 待办事项 (To-Do)
[ ] 支持除 arXiv 外更多学术论文来源。

[ ] 为 Linux/macOS 添加定时任务支持 (使用 cron)。

[x] 已考虑使用 PyInstaller 或 Nuitka 打包为单个可执行文件 (项目已支持打包后路径检测)。

[ ] 增加更详细的错误分类和用户提示。

[ ] 允许为“本地文件夹分析”工作流设置独立的邮件报告分组。