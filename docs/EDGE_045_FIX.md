# Edge 独立职位页精确修复 0.4.5

0.4.4 诊断给出了充分结构信息：

- 正文：`.job-detail-section > .job-sec-text`，705 字。
- 薪资：`.detail-section-item.salary-info > .job-sec-text`。
- 公司介绍：`.detail-section-item.company-info-box > .job-sec-text.fold-text`。
- 页面上“职位描述”不是采集器可识别的 heading DOM，因此按标题寻找无法工作。

0.4.5 对独立页优先直接选择 `.job-detail .job-detail-section > .job-sec-text`，排除薪资和公司介绍。公司名优先在 `.company-info-box` 内的公司链接获取，岗位 ID 继续来自当前 URL。

根据诊断 class 一比一构建的合成 DOM 测试通过。扩展测试共 14 项通过。需要在 `edge://extensions` 重新加载，并刷新 BOSS 标签；侧栏应显示 0.4.5。

修复后真实 Edge 端到端仍需重新加载后的页面确认。
