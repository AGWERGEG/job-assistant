# v0.5.0 求职搭子：当前工程事实与后续交接

2026-09-17 增量：扩展0.5.1改为岗位ID驱动的确认保留，详见 RELEASE_051.md。同ID正文变化不再撤销确认；短暂身份未知保留资料和对话、仅暂停发送。下文0.5.0的“内容变化撤销确认”已由此规则替代。后端保持0.5.0。

日期：2026-09-17。本文件优先于 v0.4 及更早的架构、UI 和接入说明。目标是“能安全记住我、围绕一个岗位持续聊天，并把简历任务交到工作台”。

## 已实现

- 初次认识：温柔 / 直球两张固定角色卡、搭子称呼、用户昵称、求职阶段，本地持久化。
- 简历本地导入与填写模板；保存原始档案，脱敏预览确认后才允许模型处理。
- 本地规则覆盖姓名字段、已知姓名、手机号、邮箱、证件号、长号码、标注地址、URL、常见密钥和自定义敏感词。职业事实保留。职业阶段纳入上下文。
- 所有 worker 调用在 prompt_for 内再次脱敏，涵盖旧快照、历史结果、聊天与验收稿；API 与 Codex 使用同一入口。CLI show/claim 输出脱敏上下文，complete 不回显原始快照。
- 自由对话与快捷岗位分析生成短文本；深度分析、定向简历和 HR 招呼保留专业任务。简历指令中的重复全文输出已在最终输出约束中取消。
- messages 表把用户消息与任务绑定；同一岗位有未完成消息时拒绝并发新消息，请求 ID 幂等。历史按岗位隔离，重启后保留；日常聊天使用空 job_id。
- 同一资料版本下继承最近8轮已完成对话与每类最新策略；验收简历只在原始资料与岗位版本仍有效时进入新上下文。
- 三个快捷键：分析该岗位、优化简历、HR招呼；明确的“帮我优化简历”等文字请求可直接路由，其他文字仍作为对话。
- 侧栏先读取，再显式确认岗位建档。确认前不能发起对话；切页或内容变化后撤销当前确认。无自动跟随模型调用。
- 侧栏消息结果常驻；专业任务返回工作台任务定位链接。工作台可编辑简历草稿、保存多个验收版本并复制，不覆盖原档案。
- Codex CLI / 兼容 Chat Completions API 两种后端。工作台配置地址、模型与密钥；更换地址清除旧密钥，拒绝携带凭据的 URL，禁止 HTTP 重定向转发认证头。
- API 密钥保存在本地权限为600的 SQLite 文件，不是系统钥匙串加密；不交给扩展、不回显明文、不放入 prompt。
- 排队、模型调用与总耗时记录在 metrics_json；错误分类不落盘原始 stderr/HTTP错误正文。

## 文件分工

- app/privacy.py：纯本地脱敏、审核指纹。
- app/companion.py：角色、设置、建档审核、聊天历史与简历验收。
- app/providers.py：Chat Completions 非流式接口、固定文本连接测试。
- app/worker.py：两种调用共享提示与出站脱敏；短对话不要求结构化 JSON。
- app/store.py：schema 5 幂等迁移，旧表和数据保留。
- app/bridge.py：新增 confirm/history/talk；必须先配对，再校验 scope+seq+岗位revision+确认状态。旧 bridge 路由保留兼容。
- web/：新的引导、对话、工作台交付界面。
- extension/：精简为岗位确认 + 三快捷键 + 聊天；提取器未改动，诊断版本仍为0.4.6。

## API

本机 POST 仍必须 X-Local-Token，扩展 Origin 不能访问本机 /api 接口。

GET /api/companion：公开设置（只有 has_api_key，不包含密钥和审核指纹）。

POST /api/companion：更新角色与模型设置；api_key留空保留（更换地址除外），clear_api_key删除保存值。

POST /api/privacy-preview 与 /api/privacy-approve：审核当前档案、敏感词、昵称、职业阶段。更改相关数据后指纹不匹配，需要重新预览。

POST /api/talk：job_id、kind、text、request_id；返回任务。kind支持 companion_chat、quick_analysis、analyze_job、tailor_resume、suggest_reply。

POST /api/history：job_id；返回近60条脱敏消息及任务状态。模型只继承近8轮有效历史。

POST /api/resume-accept：task_id、content；只验收已完成且资料未过期的简历任务。

POST /api/resume-versions：job_id；读取本地验收稿，不开放给扩展。

POST /api/task-preview：task_id；根据当前脱敏设置重建待发送提示，不是历史出站请求的逐字审计副本。

POST /api/connection-test：API模式只发送固定“OK”测试，不发送简历；Codex模式检查本地可执行文件，不能证明登录/额度可用。

扩展新增 POST /bridge/confirm、/bridge/history、/bridge/talk，只作用于当前 scope 已绑定且确认的岗位。

## 数据与升级

新表：companion_settings、messages、resume_versions；tasks新增 metrics_json。原画像、岗位、文件、任务都保留。

数据目录可能含真实个人资料和密钥，不打包。data-demo同样可能为真实资料。升级前停止旧服务，用 SQLite backup API 保存一致性备份，或在服务停止后备份完整数据目录；不要用旧 ZIP 覆盖或清空数据目录。

旧运行目录不等于默认 data。用 launch.py --data-dir /原数据目录 显式继续使用。第一次升级到0.5需完成角色设置与脱敏审核。旧任务可能因资料版本/审核指纹变化而失败，需新建任务；不要不断重试旧快照。

## 测试与本机实测

测试命令：Python3.10+运行 python3 -m unittest discover -s tests -v；扩展测试需要独立 jsdom：NODE_PATH=<scratch>/node_modules node --test tests/test_extension.cjs。

已验证：两种出站适配器的敏感字段不泄露（模拟 Codex 进程和本机 HTTP 兼容接口），密钥隔离、并发消息幂等、历史隔离、重新审核、验收版本与过期拒绝、扩展鉴权与切岗防串。

本轮回归：Python 3.12 下36项后端测试通过，15项JS扩展测试通过；后者包含10项旧采集器/脱敏诊断测试和5项新侧栏/权限测试。

实际浏览器（隔离虚构数据）：完成称呼保存、档案编辑、脱敏预览确认、自由对话入队；用明确标注“非模型生成”的占位稿完成简历编辑与版本验收。实际 UI 测试不等于建议质量验收。

真实 Codex：CLI 0.154.0-alpha.6.2 显示 ChatGPT 已登录，测试调用经历多次请求超时后返回使用额度耗尽。虚构对话未成功生成，不宣称恢复真实模型闭环或证明提速。未配置/调用第三方真实 API 密钥。

## 尚未完成及限制

- 独立精确页采集仍未解决，按用户要求暂缓；当前0.5侧栏需真实 Edge 重载后验收。
- 自动脱敏不等于匿名保证：未标注人名、自由叙述的地址、独特经历可能遗漏，需补自定义敏感词。不要宣传“任何个人信息绝不上传”。
- 用户原始资料和历史快照仍存在本地。未做全文删除、加密存储、OCR、事实ID拆分、完整简历模板排版、PDF/DOCX导出。
- 聊天只取有限有效历史，不是无限记忆；用户纠正不会自动写入永久画像。
- 尚无流式返回、首token计时、常驻模型会话、运行中取消。API/Codex都等最终响应，model_seconds是整个调用耗时。
- 无独立面试事件卡、求职事件统计、祝福彩蛋、求职成功总结或作者寄语；聊天提示仅允许收到面试邀请时给简短准备建议。
- 尚未实现投递和发送动作，也不能把生成次数统计成实际发送/投递次数。
- Codex只读沙箱与提示限制保留；未增加专门的工具禁用代理。不要将宿主权限等同完全隔离容器。

## 下一轮建议

先在额度恢复或用户配置API后，用虚构档案完成三类任务与多轮对话实测并记录耗时/内容质量；再做真实Edge侧栏验收。随后补事件记录与面试卡、祝福彩蛋、成功总结。不要为内容质量问题先扩多人账号或自动投递。

接口依据：https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create 。只保证约定的Chat Completions格式，不保证所有“兼容”服务支持相同参数。
