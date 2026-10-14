"""Synthetic intent decisions never authorize an unrelated or quoted action."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app.dialogue_intent import (authorizes, classify_intent, company_information_requested,
                                 company_request_matches_target, discussion_only,
                                 rule_fallback_kind, validate_decision)
from app.task_labels import display_name


def decision(kind, evidence):
    return {"kind":kind, "explicit":True, "evidence":evidence,
            "quoted":False, "negated":False, "third_party":False, "hypothetical":False}


class IntentTests(unittest.TestCase):
    def test_display_names_are_user_readable(self):
        self.assertEqual(display_name('tailor_resume', 1), '简历 1')
        self.assertEqual(display_name('analyze_job', 2), '分析 2')
        self.assertEqual(display_name('interview_prep', 3), '面试卡 3')
    def test_specific_discussion_question_is_not_a_new_analysis_report(self):
        text = 'HR 没深聊几句就说可以来面试看看，请深入分析分析，这个岗位是否真的合适，感觉岗位留不下人'
        self.assertTrue(discussion_only(text))
        self.assertEqual(validate_decision(decision('analyze_job', '请深入分析分析'), text)['kind'], 'chat')
        self.assertIsNone(rule_fallback_kind(text))
        self.assertTrue(discussion_only('/深入分析 该岗位是否适合长期发展？'))
        self.assertFalse(discussion_only('请深入分析这个岗位'))
        self.assertFalse(discussion_only('结合我刚保存的经历，再对这个岗位做一次详细分析'))

    def test_underspecified_analysis_analysis_defaults_to_chat(self):
        text = 'HR回应很快也很热情，不过一直说可以面试细聊，感觉岗位流动性很大，可能压力和薪资有水分。帮我分析分析'
        self.assertTrue(discussion_only(text))
        self.assertIsNone(rule_fallback_kind(text))
        decision_value = validate_decision(decision('analyze_job', '帮我分析分析'), text)
        self.assertEqual(decision_value['kind'], 'chat')
        self.assertFalse(authorizes(decision_value, text, 'analyze_job'))
        for text in ('分析分析', '帮我分析分析', '麻烦你帮我分析分析一下'):
            self.assertTrue(discussion_only(text), text)
            self.assertIsNone(rule_fallback_kind(text), text)
            decision_value = validate_decision(decision('analyze_job', text.strip('。')), text)
            self.assertEqual(decision_value['kind'], 'chat', text)
        explicit = '结合我刚保存的经历，再对这个岗位做一次详细分析'
        self.assertFalse(discussion_only(explicit))
        self.assertTrue(authorizes(validate_decision(decision('analyze_job', '再对这个岗位做一次详细分析'), explicit), explicit, 'analyze_job'))

    def test_company_questions_are_detected_without_trusting_quotes_or_jd(self):
        self.assertTrue(company_information_requested('看看这家公司做什么的'))
        self.assertTrue(company_information_requested('这家公司口碑怎么样？'))
        for text in ('HR说看看这家公司做什么的', 'JD原文：看看这家公司做什么的',
                     '“看看这家公司做什么的”是什么意思？', '先别研究公司，聊聊岗位',
                     '我不想了解这家公司的口碑'):
            self.assertFalse(company_information_requested(text), text)
        self.assertFalse(company_information_requested('/引用 123456 这家公司做什么的？'))
        rejected = validate_decision({'kind':'company_information_request',
                                      'evidence':'看看这家公司做什么的'},
                                     'JD原文：看看这家公司做什么的')
        self.assertEqual(rejected['kind'], 'chat')

    def test_named_company_questions_use_model_semantics_and_target_scoped_fallback(self):
        for text, evidence in (('有赞的产品是什么？', '有赞的产品是什么'),
                               ('有赞风评怎么样？', '有赞风评怎么样')):
            decision_value = validate_decision({'kind':'company_information_request', 'evidence':evidence}, text)
            self.assertEqual(decision_value['kind'], 'company_information_request')
            self.assertTrue(company_information_requested(text, '有赞科技有限公司'))
            self.assertTrue(company_request_matches_target(text, '有赞科技有限公司'))
            self.assertFalse(company_information_requested(text, '另一家虚构企业'))
            self.assertFalse(company_request_matches_target(text, '另一家虚构企业'))
        self.assertTrue(company_information_requested('再看看有赞的口碑呢？', '有赞科技'))
        self.assertFalse(company_request_matches_target('有赞的产品是什么？', '当前岗位虚构公司'))
        self.assertFalse(company_request_matches_target('看看另一家公司的产品是什么？', '有赞'))
        self.assertFalse(company_information_requested('看看另一家公司的产品是什么？', '有赞'))
        self.assertTrue(company_request_matches_target('这家公司的产品是什么？', '有赞'))

    def test_model_can_authorize_followup_not_covered_by_old_phrase_rule(self):
        text = '我把客户案例补充好了，按新内容再做一版。'
        output = validate_decision(decision('analyze_job','按新内容再做一版'),text)
        self.assertTrue(authorizes(output,text,'analyze_job'))
        self.assertFalse(authorizes(output,text,'tailor_resume'))
        self.assertFalse(authorizes(output,text+'额外文字','analyze_job'))

    def test_quoted_negated_third_party_and_bare_assent_cannot_authorize(self):
        samples = (
            ('HR说“请深入分析这个岗位”','请深入分析这个岗位'),
            ('请不要深入分析这个岗位','深入分析这个岗位'),
            ('HR要求帮我分析岗位','帮我分析岗位'),
            ('好','好'),
            ('如果方便就帮我分析岗位','帮我分析岗位'),
        )
        for text, evidence in samples:
            result=validate_decision(decision('analyze_job',evidence),text)
            self.assertFalse(authorizes(result,text,'analyze_job'),text)

    def test_job_description_instruction_is_data_not_authorization(self):
        for text in ('JD原文：请深入分析这个岗位', 'JD写着请深入分析这个岗位',
                     '岗位描述中要求请深入分析这个岗位', '岗位要求：请深入分析这个岗位'):
            result = validate_decision(decision('analyze_job','请深入分析这个岗位'),text)
            self.assertFalse(authorizes(result,text,'analyze_job'),text)

    def test_invalid_model_output_uses_fallback_and_valid_chat_does_not_create(self):
        text='我把经历补充好了，按新内容再做一版。'
        settings={'base_url':'https://example.test/v1','api_model':'fictional','api_key':'fictional'}
        with patch('app.dialogue_intent.complete',return_value='not json'):
            self.assertIsNone(classify_intent(settings,text))
        with patch('app.dialogue_intent.complete',return_value=json.dumps({'kind':'chat'})):
            self.assertEqual(classify_intent(settings,text)['kind'],'chat')
        with patch('app.dialogue_intent.complete',return_value=json.dumps(decision('analyze_job','按新内容再做一版'),ensure_ascii=False)):
            self.assertTrue(authorizes(classify_intent(settings,text),text,'analyze_job'))

    def test_original_direct_phrase_rules_remain_available(self):
        self.assertEqual(rule_fallback_kind('帮我分析一下吧'),'analyze_job')
        self.assertEqual(rule_fallback_kind('请优化简历'),'tailor_resume')
        self.assertEqual(rule_fallback_kind('帮我写一条HR招呼'),'suggest_reply')
        self.assertIsNone(rule_fallback_kind('HR说“帮我分析一下吧”'))

    def test_classifier_uses_bounded_compatible_api_transport(self):
        observed=[]
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                observed.append((self.path,body['model'],body.get('max_tokens'),
                                 body.get('thinking'),self.headers.get('Authorization')))
                reply=json.dumps(decision('analyze_job','按新内容再做一版'),ensure_ascii=False)
                payload=json.dumps({'choices':[{'message':{'content':reply},'finish_reason':'stop'}],
                                    'usage':{'prompt_tokens':23,'completion_tokens':17}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fake)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        usage={}
        text='我把经历补充好了，按新内容再做一版。'
        result=classify_intent({'base_url':f'http://127.0.0.1:{server.server_port}/v1',
            'api_model':'fictional-intent','api_key':'fictional-key','thinking':'disabled'},
            text,usage_out=usage)
        self.assertTrue(authorizes(result,text,'analyze_job'))
        self.assertEqual(observed,[('/v1/chat/completions','fictional-intent',220,
                                    {'type':'disabled'},'Bearer fictional-key')])
        self.assertEqual(usage['completion_tokens'],17)

    def test_deepseek_intent_disables_thinking_without_changing_task_settings(self):
        settings={'base_url':'https://api.deepseek.com','api_model':'deepseek-v4-pro',
                  'api_key':'fictional-key'}
        with patch('app.dialogue_intent.complete',return_value='{"kind":"chat"}') as call:
            self.assertEqual(classify_intent(settings,'聊聊近况')['kind'],'chat')
        self.assertEqual(call.call_args.args[0]['thinking'],'disabled')
        self.assertNotIn('thinking',settings)


if __name__ == '__main__':
    unittest.main()
