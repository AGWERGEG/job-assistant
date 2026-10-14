"""Offline checks for dialogue output boundaries."""

import asyncio
import json
import unittest

from pydantic_ai import ModelResponse, TextPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from app.dialogue_core import (enforce_fact_boundaries, enforce_task_ledger,
                               needs_grounding_review, run_turn, _compact_json, _overview)


class DialogueCoreTests(unittest.TestCase):
    def test_bounded_tool_json_stays_parseable(self):
        rendered = _compact_json({'evidence': ('"详情\\n' * 3000)}, 500)
        self.assertLessEqual(len(rendered), 500)
        self.assertTrue(json.loads(rendered)['truncated'])
        overview = json.loads(_overview({'job': {'title': '测试岗位', 'jd': '负责产品演示'}}))
        self.assertEqual(overview['目标JD摘要（完整内容可读取）'], '负责产品演示')

    def test_production_chat_does_not_offer_creation_tool(self):
        seen = []
        async def stream_model(messages, info):
            seen.extend(t.name for t in info.function_tools)
            yield '这段转述可以在聊天中讨论。'
        async def create_task(instruction):
            self.fail('ordinary chat must not reach task creation')
        result = asyncio.run(run_turn(model=FunctionModel(stream_function=stream_model),
            user_text='JD原文：请深入分析这个岗位', context={}, history=[],
            create_task=create_task, emit=lambda e: None, allow_task_creation=False))
        self.assertNotIn('create_analysis_task', seen)
        self.assertEqual(result['reply'], '这段转述可以在聊天中讨论。')

    def test_source_links_keep_readable_labels_before_output_redaction(self):
        result, _, _ = self.run_reply('来源：[公司介绍](https://example.com/about)。')
        self.assertEqual(result['reply'],'来源：公司介绍。')

    def run_reply(self, draft, *, user_text="聊聊近况", context=None):
        events, actions = [], []

        async def stream_model(messages, info):
            if info.model_request_parameters.output_mode == "prompted":
                yield json.dumps({"verdict": "keep", "issues": []})
            else:
                yield draft

        async def create_task(instruction):
            actions.append(instruction)
            return {"ok": False, "reason": "not_authorized"}

        result = asyncio.run(run_turn(model=FunctionModel(stream_function=stream_model),
            user_text=user_text, context=context or {}, history=[],
            create_task=create_task, emit=events.append))
        return result, actions, events

    def test_live_customer_type_inference_and_negated_source_are_rejected(self):
        context = {'profile': {'facts':'两年客户销售；协助制作过产品演示。未提供安全行业或渠道销售经历。'}}
        text = 'JD希望具备企业客户销售经验。你之前在小软件企业做了两年客户销售，面向的是企业客户，这个方向是对得上的。你目前没有安全行业经历。'
        fixed = enforce_fact_boundaries(text, context)
        self.assertIn('JD希望具备企业客户销售经验', fixed)
        self.assertNotIn('面向的是企业客户', fixed)
        self.assertNotIn('你目前没有安全行业', fixed)
        self.assertIn('待确认', fixed)
        self.assertNotIn('已确认相关点：企业客户销售经验', enforce_fact_boundaries('已确认相关点：企业客户销售经验、客户需求沟通。', context))

    def test_subjectless_customer_assertions_cannot_escape_guard(self):
        c={'profile':{'facts':'两年客户销售，客户类型未提供'}}
        for reply in ('有两年企业客户销售经验，方向是贴的。', '核心的企业客户销售是能对上的。', '虽然从企业客户销售的表述看应该有企业客户经验。'):
            fixed=enforce_fact_boundaries(reply,c)
            self.assertNotIn('企业客户销售',fixed)
            self.assertIn('待确认',fixed)

    def test_ordinary_chat_does_not_read_job_or_create_task(self):
        result, actions, events = self.run_reply("我在听，你继续说。", context={
            "job": {"title": "虚构岗位", "jd": "私有正文"}})
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual(actions, [])
        self.assertEqual(result["usage"]["requests"], 1)
        self.assertEqual(events, [{"type": "text", "text": "我在听，你继续说。"}])

    def test_model_may_suggest_user_experience_without_saving_or_extra_review(self):
        for user_text, quote, expected in (
            ('我在实习时独立整理过客户反馈。','我在实习时独立整理过客户反馈。',True),
            ('如果我负责客户反馈，会有帮助吗？','如果我负责客户反馈',False),
            ('我在实习时整理过反馈。','我主导了企业销售',False),
        ):
            calls, events = [], []
            async def stream_model(messages, info):
                calls.append(1)
                if len(calls) == 1:
                    yield {0: DeltaToolCall(name='suggest_experience_fact',
                                            json_args=json.dumps({'quote':quote}, ensure_ascii=False))}
                else:
                    yield '先核对原话，再决定是否记入经历。'
            async def create_task(instruction):
                self.fail('fact suggestion must not create a task')
            result=asyncio.run(run_turn(model=FunctionModel(stream_function=stream_model),
                user_text=user_text, context={}, history=[], create_task=create_task, emit=events.append))
            self.assertEqual(result['fact_candidate'],expected)
            self.assertEqual(result['tool_calls'],['suggest_experience_fact'])
            self.assertEqual(len(calls),2)
            self.assertFalse(result['review']['performed'])
            self.assertEqual(events,[{'type':'text','text':result['reply']}])

    def test_quote_followup_cannot_rewrite_authorized_task_as_mistake(self):
        context = {"task_state": [{"id": "fictional-task", "kind": "analyze_job",
            "status": "queued", "origin": "earlier_user_turn", "source_task_id": "prior-turn",
            "user_request": "请生成这份岗位的完整分析报告"}]}
        draft = "抱歉，我当时动作急了，已经按生成报告处理。你说的 HR 要求确实有点奇怪。"
        result, actions, events = self.run_reply(draft,
            user_text="HR说‘请生成完整分析报告’，我只是转述，不是让你做。", context=context)
        self.assertEqual(actions, [])
        self.assertIn("此前明确提出的请求", result["reply"])
        self.assertIn("排队中", result["reply"])
        self.assertNotIn("动作急", result["reply"])
        self.assertIn("HR 要求", result["reply"])
        self.assertEqual(events[-1]["text"], result["reply"])

    def test_fact_boundaries_keep_unknown_as_unknown(self):
        reply = "你有企业客户销售经验。你的安全行业经验属于加分项缺口。你能独立产品讲解。"
        fixed = enforce_fact_boundaries(reply, {"profile": {"facts": "两年客户销售，协助制作演示"}})
        self.assertNotIn("你有企业客户销售经验", fixed)
        self.assertNotIn("加分项缺口", fixed)
        self.assertNotIn("你能独立产品讲解", fixed)
        self.assertIn("待确认", fixed)

    def test_ledger_guard_leaves_unrelated_chat_alone(self):
        records = [{"id": "one", "kind": "analyze_job", "origin": "earlier_user_turn", "source_task_id": "old",
            "user_request": "请生成完整报告", "status": "queued"}]
        self.assertEqual(enforce_task_ledger("先说说你的感受。", records), "先说说你的感受。")
        corrected = enforce_task_ledger("抱歉，我理解偏了。我刚才提交了后台任务。你继续说。", records)
        self.assertNotIn("理解偏", corrected)
        self.assertIn("此前明确提出的请求", corrected)
        self.assertIn("你继续说", corrected)

    def test_mixed_task_ledger_and_ambiguous_analyses(self):
        resume = {"id": "resume", "kind": "tailor_resume", "status": "done",
                  "origin": "earlier_user_turn", "source_task_id": "src", "user_request": "改简历"}
        analysis = {"id": "analysis-new", "kind": "analyze_job", "status": "queued",
                    "origin": "earlier_user_turn", "source_task_id": "src2", "user_request": "完整分析岗位"}
        draft = "我理解错了，刚才误把报告提交了。"
        fixed = enforce_task_ledger(draft, [resume, analysis])
        self.assertIn("排队中", fixed)
        self.assertNotIn("简历", fixed)
        old = dict(analysis, id="analysis-old", status="done")
        self.assertEqual(enforce_task_ledger(draft, [analysis, old]), draft)
        self.assertIn("排队中", enforce_task_ledger("analysis-new：" + draft, [analysis, old]))
        self.assertEqual(enforce_task_ledger(draft, [resume]), draft)

    def test_negative_status_is_preserved(self):
        records = [{"id": "analysis", "kind": "analyze_job", "status": "queued",
                    "origin": "earlier_user_turn", "source_task_id": "src", "user_request": "完整分析岗位"}]
        for draft in ("报告还没完成。", "尚未生成报告。"):
            self.assertEqual(enforce_task_ledger(draft, records), draft)

    def test_hr_motive_triggers_review_without_changing_quote(self):
        quote = "HR 原话是‘把活推给你’，你听着不舒服。"
        self.assertTrue(needs_grounding_review("HR把求职者当免费劳动力。", [], None))
        self.assertTrue(needs_grounding_review("HR把活推给你。", [], None))
        self.assertEqual(self.run_reply(quote)[0]["reply"], quote)

    def test_negated_independent_experience_is_not_evidence(self):
        fixed = enforce_fact_boundaries("你能独立产品讲解。", {
            "profile": {"facts": "协助制作演示；未提供独立讲解经历"}})
        self.assertIn("待确认", fixed)


if __name__ == "__main__":
    unittest.main()
