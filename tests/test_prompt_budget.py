import copy
import json
import unittest

from app.privacy import safe_context
from app.prompt_budget import PROMPT_BUDGETS, PROMPT_BUDGET_VERSION, compact_context
from app.store import Problem


KINDS = (
    "companion_chat",
    "quick_analysis",
    "suggest_reply",
    "analyze_job",
    "tailor_resume",
    "interview_prep",
    "interview_review",
    "rest_message",
    "closing_message",
)


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def synthetic_context():
    facts = [
        {
            "id": f"fact-{index:02d}",
            "category": "经历",
            "content": f"合成经历{index}：" + ("普通行政记录和日常整理，按流程完成信息核对与文件归档。" * 180),
            "source": "用户确认",
        }
        for index in range(45)
    ]
    facts[22]["content"] = "AI解决方案销售经历：企业客户开发、产品演示和方案跟进。" + ("销售相关补充。" * 250)
    copied_evidence = {
        "id": "evidence-repeat-0001",
        "kind": "company_page",
        "label": "企业自述",
        "title": "公司产品介绍",
        "text": "原文引用：我们为制造企业提供智能排产与供应链协同平台。",
    }
    context = {
        "profile": {
            "name": "合成用户",
            "preferences": "优先考虑企业服务和AI产品岗位",
            "facts": "\n\n".join(
                [f"普通经历 {i}：" + ("常规行政支持。" * 45) for i in range(18)]
                + ["AI产品销售：企业客户需求沟通、产品演示、方案整理与合同跟进。" * 6]
            ),
        },
        "job": {
            "title": "AI解决方案销售",
            "company": "合成科技",
            "jd": "岗位要求企业客户开发、产品演示、需求沟通和方案跟进。" * 1800,
            "conversation": "HR沟通历史 " * 1200,
        },
        "instruction": "请结合我的真实经历与岗位要求给出分析。",
        "confirmed_facts": facts,
        "company_background": {
            "name": "合成科技",
            "revision": 7,
            "evidence": [
                copied_evidence,
                copy.deepcopy(copied_evidence),
                {
                    "id": "evidence-platform-0002",
                    "kind": "company_page",
                    "label": "平台生成参考",
                    "title": "平台生成的业务摘要",
                    "text": "平台摘要：公司涉及工业软件与数据服务；此内容未经企业核实。",
                },
                {
                    "id": "evidence-job-0003",
                    "kind": "job_card",
                    "label": "招聘方表述",
                    "title": "其他在招岗位",
                    "jobs": [{"title": "客户成功顾问", "conditions": "服务制造业客户，跟进系统上云和使用培训。"}],
                },
                *[
                    {
                        "id": f"evidence-large-{index:02d}",
                        "kind": "job_card",
                        "label": "招聘方表述",
                        "title": f"合成岗位概况 {index}",
                        "text": "不同招聘材料。" * 200,
                    }
                    for index in range(16)
                ],
            ],
        },
        "dialogue": [
            {"user": f"第 {index} 轮用户消息 " + ("较早的对话。" * 90),
             "assistant": f"第 {index} 轮助手回复 " + ("历史回复内容。" * 110)}
            for index in range(10)
        ],
        "accepted_resume": "已验收简历合成内容：AI产品销售、企业客户沟通和方案跟进。\n\n" * 12000,
        "prior_results": [
            {"kind": "tailor_resume", "summary": "历史草稿摘要。" * 100, "strategy": "历史策略。" * 300,
             "primary_output": "上一版简历草稿。" * 500},
        ],
        "companion": True,
    }
    return context


class PromptBudgetTests(unittest.TestCase):
    def test_selected_result_survives_large_history_and_is_redacted_without_mutation(self):
        source=synthetic_context()
        source['reference']={'task_id':'selected-task','kind':'analyze_job','stale':True,
                             'profile_revision':1,'job_revision':2,
                             'result':{'summary':'所选分析独有结论：薪资和工作时间未说明。',
                                       'primary_output':'所选成果原文；电话13812345678；'+'所选内容。'*3000,
                                       'markdown':'所选依据。'*4000}}
        before=copy.deepcopy(source)
        compact=compact_context(safe_context(source,{}),'companion_chat')
        self.assertEqual(source,before)
        self.assertEqual(compact['reference']['task_id'],'selected-task')
        self.assertTrue(compact['reference']['stale'])
        self.assertIn('薪资和工作时间未说明',compact['reference']['result']['summary'])
        self.assertNotIn('13812345678',json.dumps(compact,ensure_ascii=False))
        self.assertLessEqual(encoded_size(compact),PROMPT_BUDGETS['companion_chat'])
        from app.worker import prompt_for
        prompt=prompt_for({'kind':'companion_chat','context':source})
        self.assertIn('所选分析独有结论',prompt)
        self.assertIn('不能用较近的聊天',prompt)

    def test_all_kinds_fit_the_final_compact_json_budget_with_exact_metadata(self):
        source = synthetic_context()
        settings = {"user_name": "合成用户", "private_terms": "合成隐私词", "stage": "求职中"}
        for kind in KINDS:
            with self.subTest(kind=kind):
                compact = compact_context(safe_context(source, settings), kind)
                size = encoded_size(compact)
                self.assertLessEqual(size, PROMPT_BUDGETS[kind])
                self.assertEqual(compact["_prompt_budget"]["estimated_context_chars"], size)
                self.assertEqual(compact["_prompt_budget"]["version"], PROMPT_BUDGET_VERSION)
                self.assertEqual(PROMPT_BUDGET_VERSION, "context-budget-2")

    def test_latest_instruction_up_to_5000_characters_is_preserved_completely(self):
        instruction = "最新用户要求：" + ("请按岗位职责逐项对照我的经历，并指出证据缺口。" * 190)
        self.assertGreater(len(instruction), 4000)
        self.assertLessEqual(len(instruction), 5000)
        compact = compact_context(safe_context({**synthetic_context(), "instruction": instruction}, {}), "analyze_job")
        self.assertEqual(compact["instruction"], instruction)

    def test_oversized_required_instruction_fails_locally_instead_of_being_sent(self):
        marker = "合成指令专属片段"
        context = {**synthetic_context(), "instruction": marker + ("必要的用户要求。" * 7000)}
        with self.assertRaises(Problem) as raised:
            compact_context(safe_context(context, {}), "analyze_job")
        message = str(raised.exception)
        self.assertTrue(any(word in message for word in ("本地", "指令", "提示")))
        self.assertNotIn(marker, message)

    def test_redaction_precedes_budget_compaction_and_inputs_are_not_mutated(self):
        source = synthetic_context()
        source["profile"]["name"] = "合成私密姓名"
        source["instruction"] = "电话：13812345678；邮箱：synthetic@example.test；" + source["instruction"]
        before = copy.deepcopy(source)
        safe = safe_context(source, {"user_name": "合成私密姓名", "private_terms": "", "stage": ""})
        safe_before = copy.deepcopy(safe)
        compact = compact_context(safe, "companion_chat")
        serialized = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(source, before)
        self.assertEqual(safe, safe_before)
        self.assertNotIn("合成私密姓名", serialized)
        self.assertNotIn("13812345678", serialized)
        self.assertNotIn("synthetic@example.test", serialized)
        self.assertIn("[本地隐去]", serialized)

    def test_relevance_and_company_source_quote_semantics_survive_compaction(self):
        compact = compact_context(safe_context(synthetic_context(), {}), "analyze_job")
        self.assertIn("AI产品销售", compact["profile"]["facts"])
        evidence = compact["company_background"]["evidence"]
        by_id = {item["id"]: item for item in evidence}
        self.assertIn("evidence-repeat-0001", by_id)
        self.assertIn("原文引用：我们为制造企业提供智能排产与供应链协同平台。", by_id["evidence-repeat-0001"]["text"])
        self.assertEqual(by_id["evidence-repeat-0001"]["label"], "企业自述")
        self.assertEqual(by_id["evidence-platform-0002"]["label"], "平台生成参考")
        self.assertIn("evidence-job-0003", by_id)
        self.assertEqual(len([item for item in evidence if item.get("id") == "evidence-repeat-0001"]), 1)

    def test_saved_and_public_company_materials_keep_separate_source_references(self):
        source = synthetic_context()
        source["company_background"]["evidence"][0].update({
            "source":"BOSS 公司介绍页", "source_url":"https://www.zhipin.com/gongsi/synthetic.html",
            "observed":1720000000,
        })
        source["company_background"]["evidence"].append({
            "id":"saved-public-research-1", "kind":"research", "label":"公开页面",
            "title":"公开产品说明", "source_url":"https://example.test/product?secret=discard",
            "source_type":"public_web_page", "confidence":"unverified", "observed":1720000100,
            "text":"已确认保存的公开页面材料。",
        })
        source["company_research"] = {
            "company_name":"合成科技", "question":"产品业务是什么",
            "sources":[{"id":"public-source-1", "url":"https://example.test/about",
                        "source_type":"public_search_excerpt", "confidence":"unverified",
                        "observed_at":1720000000, "excerpt":"公开页面称公司提供企业软件。"}],
            "facts":[{"text":"公司提供企业软件。", "source_ids":["public-source-1"],
                      "confidence":"unverified"}], "warnings":[], "preview_id":"preview-1",
        }
        compact = compact_context(safe_context(source, {}), "companion_chat")
        local = next(item for item in compact["company_background"]["evidence"]
                     if item["id"] == "evidence-repeat-0001")
        public = compact["company_research"]
        self.assertEqual(local["label"], "企业自述")
        self.assertEqual(local["source"], "BOSS 公司介绍页")
        self.assertEqual(local["source_url"], "[链接]")
        saved_research = next(item for item in compact["company_background"]["evidence"]
                              if item["id"] == "saved-public-research-1")
        self.assertEqual(saved_research["source_group"], "saved_public_research")
        self.assertEqual(saved_research["source_type"], "public_web_page")
        self.assertEqual(saved_research["confidence"], "unverified")
        self.assertEqual(saved_research["observed"], 1720000100)
        self.assertEqual(public["sources"][0]["id"], "public-source-1")
        self.assertEqual(public["sources"][0]["url"], "[链接]")
        self.assertEqual(public["facts"][0]["source_ids"], ["public-source-1"])
        self.assertNotIn("preview_id", public)

    def test_redacted_source_urls_do_not_merge_different_recruitment_evidence(self):
        duplicate = {
            "id": "same-material-1",
            "kind": "job_card",
            "label": "招聘方表述",
            "title": "在招岗位",
            "source_url": "https://example.test/jobs/one",
            "jobs": [{"title": "销售顾问", "conditions": "负责企业客户沟通"}],
            "categories": ["销售"],
            "filters": "全职",
        }
        evidence = [
            duplicate,
            {**copy.deepcopy(duplicate), "id": "same-material-2", "source_url": "https://example.test/jobs/two"},
            {**copy.deepcopy(duplicate), "id": "different-job", "source_url": "https://example.test/jobs/three",
             "jobs": [{"title": "客户成功", "conditions": "负责客户续约"}]},
            {**copy.deepcopy(duplicate), "id": "different-category", "source_url": "https://example.test/jobs/four",
             "categories": ["客户成功"]},
            {**copy.deepcopy(duplicate), "id": "different-filter", "source_url": "https://example.test/jobs/five",
             "filters": "实习"},
        ]
        context = {
            "profile": {"name": "", "preferences": "", "facts": ""},
            "job": {"title": "岗位", "company": "合成公司", "jd": "岗位要求"},
            "instruction": "分析招聘材料",
            "company_background": {"name": "合成公司", "revision": 1, "evidence": evidence},
        }
        safe = safe_context(context, {})
        self.assertEqual({item["source_url"] for item in safe["company_background"]["evidence"]}, {"[链接]"})
        compact = compact_context(safe, "analyze_job")
        compact_evidence = compact["company_background"]["evidence"]
        by_id = {item["id"]: item for item in compact_evidence}
        self.assertIn("same-material-1", by_id)
        self.assertNotIn("same-material-2", by_id)
        self.assertIn("different-job", by_id)
        self.assertIn("different-category", by_id)
        self.assertIn("different-filter", by_id)
        self.assertIsInstance(by_id["same-material-1"]["jobs"], list)
        self.assertIsInstance(by_id["same-material-1"]["jobs"][0], dict)
        self.assertIsInstance(by_id["same-material-1"]["categories"], list)
        self.assertIsInstance(by_id["same-material-1"]["filters"], str)


if __name__ == "__main__":
    unittest.main()
