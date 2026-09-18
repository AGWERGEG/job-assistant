# GitHub 简历分析与优化调研

调研日期 2026-09-16。此文档记录 v0.3 工作流设计来源，不代表这些项目经过独立效果验证，也不复制其代码。

## 参考流程

- [Proficiently work history interview](https://github.com/proficientlyjobs/proficiently-claude-skills/blob/main/skills/setup/scripts/conduct-interview.md)：先读简历，再针对公司背景、个人职责、动作、结果、工具与困难追问，建立比简历更完整的经历画像。
- [Proficiently resume tailoring](https://github.com/proficientlyjobs/proficiently-claude-skills/blob/main/skills/tailor-resume/SKILL.md)：先做要求映射和候选人叙事，再前置相关经历、改摘要与技能顺序，最终逐句消除 AI 化表达。
- [career-ops job evaluation](https://github.com/career-ops-hq/career-ops/blob/main/modes/oferta.md)：用两遍分析避免迎合候选人；第一遍只依据 JD 判断要求重要性，第二遍再看简历证据。
- [ai-job-search drafter and reviewer](https://github.com/MadsLorentzen/ai-job-search/blob/master/.claude/commands/apply.md)：起草后由独立 reviewer 做招聘方视角审阅，用户确认的新事实及时写回长期画像。
- [LLMInternSkill resume polish](https://github.com/wanyichen06/LLMInternSkill/blob/main/skill-references/resume-polish.md)：按动作、对象、责任、结果、证据和面试风险拆解简历表述，并提供不同力度的改写。
- [ResumeSkills resume tailor](https://github.com/Paramchoudhary/ResumeSkills/blob/main/skills/resume-tailor/SKILL.md)：维护完整母版，根据岗位重新排序技能和经历，记录岗位版本。

## 采用的设计

1. 岗位分析先识别实际工作和门槛，再看候选人，给明确投入建议。
2. 每个岗位形成一条共享策略：候选人定位、主打证据、关键差距和行动顺序。
3. 简历优化继承岗位策略，按招聘方阅读顺序重组，不做机械逐句同义替换。
4. 沟通建议继承同一卖点，先判断沟通目的，只给一条可直接使用的回复。
5. 每轮最多追问两个会改变结论或成稿的问题。用户答案通过补充信息进入下一轮。
6. 用户可见的核心结果与内部依据分开呈现。

## 没有采用的规则

- 不使用简单的必选/优选加权百分比预测录用机会。
- 不把“每条简历必须有数字”当硬规则，也不估算或保守猜测数字。
- 不依据几个招聘文案词汇直接判断公司文化有毒。
- 不要求一次把所有经历信息补齐后才输出草稿。
- 不把技术岗位的证据形式直接套到销售、运营和职能岗位。
