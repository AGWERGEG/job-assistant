# v0.4 工程增量与交接

> 当前版本为 **0.5.0 陪伴闭环内测版**。先读 [v0.5 使用与工程交接](V05_HANDOFF.md)。下方0.4及更早说明为历史记录；界面、脱敏、接入与验收范围以v0.5为准。

## 已实现

- MV3 扩展包：service worker 负责本地通信；content script 负责可见 DOM 采集；sidePanel 负责交互。
- 本地一次性配对码、extension origin 绑定、会话令牌、撤销、限速与仅 bridge 路由的 CORS。
- 只允许 BOSS https 职位链接，岗位 ID 与 URL 必须一致；过滤追踪参数。
- browser_captures 新表；tasks 加 bridge_scope/cache_key/automatic/priority。启动时从旧库幂等升级，不删旧数据。
- 标题/公司/JD 不变时不增加岗位 revision；已完成结果按画像/岗位/提示版本复用。
- scope+seq 防旧请求；取消旧 queued 自动任务；显式任务优先。模型运行中不强制终止。
- 聊天选中文字只预览，提交回复任务时覆盖当前任务快照的 conversation，不改岗位持久聊天字段。

## 路由

本地工作台：POST `/api/extension-code`、`/api/extension-revoke`，仍要求 X-Local-Token 和本地来源。

扩展：POST `/bridge/pair`（code）；后续 `/bridge/status`、`/bridge/capture`、`/bridge/task`、`/bridge/result` 都要求 `Origin: chrome-extension://...` 与 `X-Bridge-Token`。不给扩展开放 profile、文件读取、原始任务快照或执行任意命令接口。服务重启令牌失效。

capture 参数：scope、seq、capture（title/company/jd/url/job_key/method）。capture=null 清除当前岗位并取消旧自动待办。

task 参数：scope、seq、kind、instruction、conversation、automatic。automatic 只允许 analyze_job。返回 task 摘要、seq、job_id、cached。

result 参数：scope、seq、task_id。验证当前岗位绑定，并返回 stale 标记。

## 当前限制与优先级

1. 本机没有 Chrome/Edge，真实扩展加载、localhost 请求 Origin 行为、本地网络权限提示和 BOSS 页面选择器未 E2E 验收。不要宣称“已实测支持所有 BOSS 页面”。
2. 首要工作是在真实已登录浏览器检查独立职位页与列表详情结构，修正 extractor.js，然后记录脱敏页面结构 fixture。当前仅合成 DOM 验证。
3. 无自动 HR 对话采集；首版选中文字 + 固定岗位 + 用户预览。后续增加 conversation ID 前不要自动读取联系人列表。
4. 没有快速模型或流式输出；继续使用现有完整判断。不要以侧栏 UI 的出现时间当作推理延迟。
5. token 为进程内；浏览器会话存储仅后台可见，服务重启需重新配对。生产版若要持久化需补轮换、撤销、来源绑定。
6. 原主工作台与三场景分析仍可用。既有用户可能将真实数据填进 data-demo，绝不可清空或打包它。

下一模型先读 AGENTS.md、本文件和 BROWSER_SIDEBAR.md。只在真实浏览器安装与用户允许的本地工具范围内测试，不创建招聘消息或申请。
