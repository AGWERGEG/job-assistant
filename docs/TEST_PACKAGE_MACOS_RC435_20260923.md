# RC4.3.5 macOS Apple 芯片便携测试包

本包由用户提供的 `JobAssistant_v1.0_RC4.3.5_Windows便携免安装版.zip` 中的源码和扩展生成；原 ZIP SHA-256：`38d15c19eb40b6a05f4de3bf6009c21b5fbba60c072b63d5378597855440488b`。Windows 内置 Python、Word/PDF 依赖和 `.bat` 启动入口改为 arm64 Python 3.12.14、相同文档依赖及 `.command` 启动入口。Windows UTF-8 子进程修复保留在 `app/api_transport.py` 和 `app/providers.py` 中，且仍有跨平台回归。仍是 RC 测试版，不是正式 v1。

本包保留了“使用空白模板”及空白档案岗位优先分析、工作台“继续聊”的可搜索岗位切换、岗位详情和 HR 聊天链接记录、侧栏手动切换岗位和返回岗位详情入口。链接记录随本机资料导出，并在用户明确确认删除资料时清除。独立测试覆盖空白档案的任务边界、链接保存/跨岗位校验，以及链接导出与清除。

## macOS 实测

- 主机：Apple Silicon arm64，macOS 26.6.2；Python 二进制的最低系统版本标记为 macOS 11.0。macOS 11–25、Intel Mac 尚未实机验证。
- 使用内置 Python 3.12.14 运行 `python -m unittest discover -s tests -q`：111 项通过。
- 运行 `NODE_PATH=<本机 Node 测试依赖目录> node --test tests/*.cjs`：95 项通过。
- 新 ZIP 完整性检查通过，无 `data/`、`data-demo/`、SQLite、密钥文件或依赖缓存；内置 `docx`、`pypdf`、`reportlab` 导入成功。
- 全新临时目录解压后，通过 `启动求职搭子.command` 及内置 Python 以隔离数据启动；`/api/health` 返回 `1.0.0-rc.4.3.5`，`/api/session` 指向该临时数据目录，空档案 `/api/companion` 未标记为就绪。服务随测试结束而停止。

实机 Edge 中的同版扩展与服务配对、BOSS/智联/58 页面读取、真实模型调用、已有个人数据升级以及 Word/PDF 的实际中文排版，尚未用此 macOS 包验收。历史 RC4.3.5 提取脚本在智联网页读取 2 张公司岗位卡片的记录，不能替代本包的完整 Edge 联动验收。

## 使用

将 ZIP 完整解压到一个新目录，双击 `启动求职搭子.command`。首次双击被 macOS 拦截时，在 Finder 中按住 Control 点击该文件并选择“打开”。Edge 的 `edge://extensions` 开启开发人员模式，停用旧版测试扩展，加载新目录内的 `extension/`，刷新招聘网页后重新配对。工作台默认地址为 `http://127.0.0.1:8421`。

包内无个人数据；默认数据写入解压目录的 `data/`。升级旧目录前先备份用户数据，等待旧任务结束并停止旧服务。若要复用旧数据，请通过命令行向 `启动求职搭子.command` 传入 `--data-dir /原数据目录`，不要将新目录覆盖旧目录。`data-demo/` 也可能含个人数据，不要覆盖或打包。

可复测命令：`python3 scripts/smoke_macos_portable.py /path/to/JobAssistant_v1.0_RC4.3.5_macOS_Apple芯片便携免安装版.zip`。该脚本只创建并清理自己的临时数据目录。
