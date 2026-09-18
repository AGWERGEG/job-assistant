# Edge 实时岗位识别修复 0.4.2

用户提供 0.4.1 的安全诊断后，确认 2026 BOSS 双栏结构：

- `.job-detail-container > .job-detail-box`
- `.job-detail-box > .job-detail-header + .job-detail-body`
- `.job-detail-body > h3.title + ul.job-label-list + p.desc + ... + a.more-job-btn`

失败发生在“详情标题必须和岗位链接文字同步”的过严校验。修复：

- 直接读取 `.job-detail-body > p.desc`。
- 用 `.more-job-btn` 的岗位 ID 匹配左侧同 ID 当前岗位卡片，作为主要身份绑定。
- 标题仅在能从 `.job-detail-header` 明确读到时作辅助冲突检测；列表显示截断标题不再阻止采集。
- 最近点击 ID 的短暂切换保护从 15 秒缩为 5 秒；稳定岗位依旧以详情链接 ID 为准。
- 独立职位页正文多块时也按“职位描述”标题分区，不因公司介绍块存在而失败。

需要在 Edge 扩展页重新加载扩展并刷新 BOSS 页，侧栏顶部应显示 **0.4.2**。本轮无法替用户重新加载已安装的开发扩展，因此修复后真实 E2E 仍待用户验证。

JS 合成 DOM 回归测试 11 项通过，其中新增用诊断中的真实类名构建的 `.job-detail-body > p.desc` 场景。诊断正文没有进入测试 fixture。
