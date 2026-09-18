# 求职搭子 · v1.0 RC1

这是正式发布前的候选测试版。侧栏陪你浏览 BOSS，提供岗位分析、简历优化、HR 回复和面试准备；所有投递与发送由你完成。

## 安装

需要 Python 3.10+、Edge 或 Chrome。完整文档能力需要安装 requirements.txt；Codex 或兼容 API 二选一。纯 API 模式无需安装 Codex。

macOS / Linux：
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python launch.py
```

Windows：
```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe launch.py
```

安装好后，macOS / Windows 可双击“启动求职搭子”脚本；两端优先使用项目 .venv。终端窗口需保持开启。启动时会显示实际 Python 路径和缺失文档依赖。

## 首次使用

1. 在 edge://extensions 或 chrome://extensions 打开开发者模式，加载本项目 extension 文件夹。
2. 打开扩展侧栏，点击“打开工作台，获取配对码”，将端口和配对码填回侧栏。
3. 在工作台选择接入：本机 Codex（先自行登录 CLI），或 Chat Completions 兼容 API（填写地址、模型、密钥）。
4. 选搭子，上传或填写简历，在本机核对脱敏预览。引导支持上一步与跳过；跳过不代表已完成隐私审核。
5. 回 BOSS 打开岗位，确认目标后聊天。简历等后台结果从“任务与成果”进入工作台核对。
6. 保存简历版本后，本机回填姓名和联系方式；确认后导出 DOCX / PDF / TXT。

Codex 模式使用独立 CLI。接入检查只验证登录凭据存在，模型权限、网络和额度仍需实际任务验证。API 连接测试只发固定测试文字，可能消耗少量服务商额度。

## 日常使用与升级

默认工作台：http://127.0.0.1:8421 。默认个人资料目录是项目 data/。演示使用 data-demo/，它同样可能已含你上传的真实资料。

升级前等待任务结束，停止旧服务，并备份原数据目录。把新版本解压到独立目录，用新版本显式继续原目录：
```bash
.venv/bin/python launch.py --data-dir "/你的原数据目录" --port 8421
```
Windows 将解释器替换为 .venv\Scripts\python.exe。不要用空 data/ 覆盖旧目录。更新扩展加载路径/重载扩展、刷新网页，再重新配对。当前包不附带个人数据或密钥。

工作台改过岗位后，侧栏出现“同步已保存岗位”时点击同步；该动作读取工作台修改，不重新抓网页覆盖它。
取消 API 请求会停止本机请求进程并释放通道；远端是否已停止推理或计费由服务商决定。

## 支持范围与已知限制

- BOSS 页面结构会变化，独立详情页仍有识别失败场景。可用侧栏“岗位读取帮助”或工作台手动补充 JD。
- PDF 仅支持可提取文本的文件，最多 30 页；扫描件需先转文字，未内置 OCR。
- PDF 导出需要可嵌入中文字体。默认检查常见系统字体；失败时设置 JOB_ASSISTANT_CJK_FONT 或先导出 Word。
- 脱敏采用本地规则和用户核对，不保证自由文本完全匿名。原件与 API 密钥存于本机；本机数据库不是加密保险箱。
- 对话上下文有长度范围；生成内容是建议，不是事实，简历和面试内容需自行核对。
- 普通聊天与长任务分通道；网络异常可能导致失败，任务记录会保留。重启后运行中任务依原租约恢复，最迟需等待原 15 分钟租约到期。
- Windows 启动脚本已调整，但本轮未进行原生 Windows 浏览器/中文字体验收。不是“一键安装的桌面 App”，也未上架扩展商店。

[RC 修复与验收记录](docs/RELEASE_100_RC1.md)。历史更新留在 docs/，以本 README 和当前 RC 文档为准。
