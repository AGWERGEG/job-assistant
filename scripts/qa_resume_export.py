"""Generate fictitious output for visual QA in a caller-chosen scratch folder."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.store import Store
from app.resume_export import export_resume

output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
content='''虚构候选人 简历排版测试
求职意向
运营助理 杭州
个人简介
具备校园活动组织、信息整理和跨成员协作经历，重视任务推进与复盘。以下内容为虚构测试，不是用户简历。
教育经历
2022.09 - 2026.06 示例大学 工商管理 本科
工作经历
2025.07 - 2025.09 示例商贸公司 运营实习生
- 整理客户咨询与售后反馈，按问题类型分类并交给对应同事跟进。
- 协助维护商品资料和活动清单，核对信息一致性，减少重复沟通。
校园经历
2024.03 - 2025.05 校园社团 活动协调
- 协调5名同学开展校园活动，负责报名整理、通知撰写和现场衔接。
- 汇总参与者反馈，整理执行问题与下一次活动的改进建议。
技能与证书
熟悉Excel基础表格整理、文档写作和演示汇报。英语能够阅读一般业务材料。
'''
with tempfile.TemporaryDirectory() as tmp:
 s=Store(tmp)
 with s.connect() as db:db.execute('INSERT INTO resume_versions VALUES(?,?,?,?,?)',('qa','job','task',content,0))
 for kind in ('docx','pdf'):
  data,_=export_resume(s,'qa',kind);(output/('resume-qa.'+kind)).write_bytes(data)
 print(output)
