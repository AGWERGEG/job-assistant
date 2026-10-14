"""Production dialogue adapter: redacted snapshots, bounded child and atomic actions."""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path
from .companion import Companion, explicit_deep_analysis_request, validate_url
from .privacy import fingerprint, redact, safe_context, terms_from
from .prompt_budget import compact_context
from .store import Problem
from .dialogue_intent import (ACTION_KINDS, classify_intent, company_information_requested,
                              company_request_matches_target, discussion_only,
                              rule_fallback_kind, source_hash)
ROOT = Path(__file__).resolve().parents[1]
MAX_EVENT = 256 * 1024


def _safe_source_url(value, private_values):
    """Return a public provenance URL without query data or private path values."""
    if not isinstance(value, str) or not value:
        return ""
    try:
        from .company import source_url as supported_company_url
        cleaned = supported_company_url(value)
    except (Problem, ValueError):
        try:
            from .company_research import public_url
            cleaned = public_url(value)
        except Problem:
            return ""
    parts = urlsplit(cleaned)
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    sensitive = redact(parts.netloc + parts.path, private_values, ())
    if any(marker in sensitive for marker in ("[本地隐去]", "[邮箱]", "[手机号]", "[电话]", "[证件号码]", "[长号码]")):
        return ""
    return cleaned


def _restore_opaque_ids(safe_context, original_context):
    """Preserve evidence IDs for citation lookup while leaving their text redacted."""
    original_company = original_context.get("company_background")
    safe_company = safe_context.get("company_background")
    original_research = original_context.get("company_research")
    safe_research = safe_context.get("company_research")
    pairs = (
        (original_company.get("evidence", []) if isinstance(original_company, dict) else [],
         safe_company.get("evidence", []) if isinstance(safe_company, dict) else [], "id"),
        (original_research.get("sources", []) if isinstance(original_research, dict) else [],
         safe_research.get("sources", []) if isinstance(safe_research, dict) else [], "id"),
        (original_research.get("facts", []) if isinstance(original_research, dict) else [],
         safe_research.get("facts", []) if isinstance(safe_research, dict) else [], "source_ids"),
    )
    for original_items, safe_items, key in pairs:
        if isinstance(original_items, list) and isinstance(safe_items, list):
            for original, safe in zip(original_items, safe_items):
                if isinstance(original, dict) and isinstance(safe, dict) and key in original:
                    safe[key] = original[key]


def _restore_compacted_source_urls(compact, original_context, private_values):
    """Restore only validated, query-free public URLs after context compaction."""
    original_company = original_context.get("company_background", {})
    original_research = original_context.get("company_research", {})
    original_evidence = {item.get("id"): item for item in original_company.get("evidence", [])
                         if isinstance(item, dict)} if isinstance(original_company, dict) else {}
    for item in (compact.get("company_background", {}).get("evidence", [])
                 if isinstance(compact.get("company_background"), dict) else []):
        original = original_evidence.get(item.get("id")) if isinstance(item, dict) else None
        if original and original.get("source_url"):
            url = _safe_source_url(original.get("source_url"), private_values)
            if url:
                item["source_url"] = url
    original_sources = {item.get("id"): item for item in original_research.get("sources", [])
                        if isinstance(item, dict)} if isinstance(original_research, dict) else {}
    for item in (compact.get("company_research", {}).get("sources", [])
                 if isinstance(compact.get("company_research"), dict) else []):
        original = original_sources.get(item.get("id")) if isinstance(item, dict) else None
        if original and original.get("url"):
            url = _safe_source_url(original.get("url"), private_values)
            if url:
                item["url"] = url


def _enforce_dialogue_snapshot_budget(snapshot):
    """Keep the final tool-visible snapshot within the companion context cap."""
    from .prompt_budget import PROMPT_BUDGETS
    budget = PROMPT_BUDGETS["companion_chat"]

    def size():
        return len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))

    if size() <= budget:
        return
    research = snapshot.get("company_research") if isinstance(snapshot.get("company_research"), dict) else {}
    company = snapshot.get("company_background") if isinstance(snapshot.get("company_background"), dict) else {}
    for item in research.get("sources", []):
        if isinstance(item, dict) and isinstance(item.get("excerpt"), str):
            item["excerpt"] = item["excerpt"][:700]
    for item in research.get("facts", []):
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            item["text"] = item["text"][:500]
    for item in company.get("evidence", []):
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            item["text"] = item["text"][:700]
    if size() <= budget:
        return
    urls = []
    urls.extend((item, "url") for item in research.get("sources", []) if isinstance(item, dict) and item.get("url"))
    urls.extend((item, "source_url") for item in company.get("evidence", []) if isinstance(item, dict) and item.get("source_url"))
    for item, key in sorted(urls, key=lambda pair: len(str(pair[0].get(pair[1], ""))), reverse=True):
        item.pop(key, None)
        if size() <= budget:
            return
    raise Problem("这次讨论的必要材料太长，请缩短补充内容后重试；本机资料未改变")


def _bound_selected_reference(reference, *, limit=8000):
    """Retain useful content from the one user-selected result within budget."""
    if not isinstance(reference, dict):
        return reference
    result = reference.get('result')
    if not isinstance(result, dict):
        return reference
    bounded = {}
    remaining = limit
    for key, cap in (('summary', 700), ('decision', 500), ('strategy', 1200),
                     ('primary_output', 3600), ('markdown', 3600)):
        value = result.get(key)
        if not isinstance(value, str) or remaining <= 0:
            continue
        value = value[:min(cap, remaining)]
        bounded[key] = value
        remaining -= len(value)
    reference['result'] = bounded
    return reference


def analysis_authorized(text):
    # Conservative side-effect guard, not a classifier for ordinary conversation.
    # Ambiguous requests can always use the existing explicit analysis button.
    if (discussion_only(text) or
            re.search(r'[“”「」『』"\']|(?:HR|hr|他|她|对方|招聘者).{0,8}(?:说|要求|让我)|(?:不|别|无需|取消|暂缓).{0,8}(?:分析|报告)|(?:转述|引用|如果|假如)', text)):
        return False
    if explicit_deep_analysis_request(text):
        return True
    # A direct imperative is authorization even without the adjective "完整".
    # Do not infer consent from an assistant offer, a bare "好", or old history.
    direct = re.fullmatch(
        r'\s*(?:请(?:你|帮我)?|麻烦(?:你|帮我)?|帮我|给我)(?:再)?'
        r'(?:分析|分析分析|分析下|分析一下)(?:一下|下)?'
        r'(?:这个岗位|这份岗位|这个职位|这份工作|这个机会|当前岗位|一下)?'
        r'(?:吧|呀|呗|好吗|可以吗)?[。！!？?\s]*', text)
    if direct:
        return True
    if re.search(r'(?:^|[。！；，,\n])\s*(?:请(?:帮我)?|帮我|我要|我想要|我需要).{0,24}(?:(?:完整|详细|深入|深度|全面|系统|重新|再次|再).{0,16}(?:分析|报告|判断|拆解)|(?:分析|报告).{0,16}(?:完整|详细|深入|深度|全面|重新|再次))', text):
        return True
    return bool(re.search(r'(?:根据|结合|基于|按照).{0,60}(?:补充|新增|刚才提供|更新后的).{0,30}(?:重新|再次|再).{0,12}(?:分析|判断|生成报告|出一份分析)', text))


def needs_task_clarification(text):
    if re.fullmatch(r'\s*(?:好|可以|行|嗯|OK|ok)[。！!？?\s]*', text):
        return True
    return bool(re.search(r'(?:请|帮我|想要|希望|再).{0,40}'
                          r'(?:分析|报告|简历|面试|招呼|任务|做一版|来一版)', text))



class DialogueSession:
    def __init__(self, store, task):
        self.store = store
        self.companion = Companion(store)
        self.history = []
        self.result = None
        with store.connect() as db:
            rows = db.execute("SELECT context_json,result_json FROM tasks WHERE job_id=? AND kind IN ('companion_chat','quick_analysis') AND status='done' AND created<? ORDER BY created DESC LIMIT 4", (task['job_id'], task['created'])).fetchall()
        for row in reversed(rows):
            c, r = json.loads(row[0]), json.loads(row[1])
            if r.get('profile_revision') == task['context']['profile']['revision'] and r.get('job_revision') == task['context']['job']['revision']:
                self.history.append({'user': c['instruction'][:5000], 'assistant': r.get('primary_output', '')[:4000]})

    def snapshot(self, task):
        settings = self.companion.settings()
        private_names = [task['context']['profile'].get('name',''), settings.get('user_name','')]
        # Include the dossier before privacy filtering and relevance compaction.
        # Previously it was appended after both, bypassing redaction and budget.
        original_context = {**task['context']}
        with self.store.connect() as db:
            from .company import dossier
            company_data = dossier(db, task['job_id']) if task.get('job_id') else None
        if company_data:
            original_context['company_background'] = company_data
        safe = safe_context(original_context, settings)
        _restore_opaque_ids(safe, original_context)
        safe = compact_context(safe, 'companion_chat')
        _restore_compacted_source_urls(safe, original_context,
                                       [*private_names, *terms_from(settings)])
        snapshot = {k: safe[k] for k in ('profile','job','confirmed_facts','career_stage',
                                         'company_background','company_research') if k in safe}
        with self.store.connect() as db:
            rows = db.execute("SELECT id,kind,status,context_json FROM tasks WHERE job_id=? AND kind IN ('analyze_job','tailor_resume','interview_prep','interview_review') ORDER BY created DESC LIMIT 4", (task['job_id'],)).fetchall()
        records = []
        for row in rows:
            c = json.loads(row['context_json'])
            records.append({'id':row['id'], 'kind':row['kind'], 'status':row['status'],
                'origin':'earlier_user_turn' if c.get('dialogue_source_task_id') else 'task_record', 'source_task_id':c.get('dialogue_source_task_id',''),
                'user_request':c.get('instruction','')[:400]})
        # Keep opaque task IDs exact; masking long numeric runs inside a UUID
        # would break artifact references. Only free-form user text needs
        # redaction here.
        private_names = [task['context']['profile'].get('name',''), settings.get('user_name','')]
        snapshot['task_state'] = [
            {**record, 'user_request': redact(record['user_request'], private_names, terms_from(settings))}
            for record in records
        ]
        from .artifacts import artifact_snapshot
        arts = artifact_snapshot(self.store, task['job_id'], settings, limit=4)
        snapshot['task_artifacts'] = arts
        snapshot['selected_reference_task_id'] = task['context'].get('reference', {}).get('task_id', '')
        if task['context'].get('reference'):
            reference = redact(task['context']['reference'], private_names, terms_from(settings))
            reference = _bound_selected_reference(reference)
            snapshot['selected_reference'] = {**reference,
                                              'task_id': task['context']['reference']['task_id']}
        snapshot['persona'] = settings.get('persona','gentle')
        _enforce_dialogue_snapshot_budget(snapshot)
        return snapshot

    def create_special(self, task, kind, *, authorized=False, intent_decision=None):
        if not authorized and intent_decision is None:
            return {'ok':False,'reason':'not_authorized'}
        try:
            child = self.store.create_task({'kind':kind,'job_id':task['job_id']},
                dialogue_parent=(task['id'],task['claim_token']), intent_decision=intent_decision)
            return {'ok':True,'id':child['id'],'kind':child['kind'],'status':child['status']}
        except Problem as exc:
            return {'ok':False,'reason':'task_creation_failed','error':str(exc)}

    def create_analysis(self, task, instruction, *, authorized=False, intent_decision=None):
        return self.create_special(task, 'analyze_job', authorized=authorized,
                                   intent_decision=intent_decision)

    def finish(self, task, result):
        # Worker owns final validation/redaction/lease-checked persistence.
        self.result = result

    def receipt_result(self, actions, elapsed, diagnostics):
        receipt = actions[-1]
        if receipt.get('id'):
            saved = self.store.get_task(receipt['id'])
            status = saved['status']
            words = {'queued':'排队中，尚未生成报告','running':'处理中','done':'已完成，请到任务列表查看', 'failed':'生成失败，可在任务列表重试','cancelled':'已取消'}
            reply = f'后台分析任务（ID：{receipt["id"]}）' + words.get(status,'已记录，请查看任务列表') + '。本轮对话未能继续，请重试聊天。'
        else:
            reply = '这次未创建分析任务。' + receipt.get('error','请使用深入分析按钮明确发起。')
        return {'reply':reply,'history':self.history,'usage':diagnostics,'tool_calls':[],
                'review':{'performed':False,'issues':[],'revised':False},'actions':actions,
                'seconds':round(elapsed,3),'first_text_seconds':None,'recovered_receipt':True}

    def intent_result(self, task, receipt, decision, elapsed, usage):
        names = {'analyze_job':'深入分析', 'tailor_resume':'岗位简历',
                 'suggest_reply':'HR 沟通', 'interview_prep':'面试准备'}
        title = names.get(decision['kind'], '专项')
        if receipt.get('id'):
            status = receipt.get('status', 'queued')
            reply = (f'已创建{title}任务（ID：{receipt["id"]}），目前排队中；结果会显示在任务与成果中。'
                     if status == 'queued' else f'{title}任务（ID：{receipt["id"]}）已记录，请在任务与成果中查看实际状态。')
        else:
            reply = f'这次未创建{title}任务：{receipt.get("error") or "请使用对应快捷按钮明确发起"}。'
        return {'reply':reply,'history':self.history + [{'user':task['context']['instruction'],'assistant':reply}],
                'usage':usage,'tool_calls':['intent_route'],'fact_candidate':False,
                'review':{'performed':False,'issues':[],'revised':False},'actions':[receipt],
                'seconds':round(elapsed,3),'first_text_seconds':round(elapsed,3),
                'intent':{'source':decision.get('source'),'kind':decision['kind']}}


def run_dialogue(settings, task, store, timeout=120, on_delta=None, intent_settings=None):
    session = DialogueSession(store,task)
    began = time.monotonic()
    instruction = task['context']['instruction']
    local_settings = session.companion.settings()
    names = [task['context']['profile'].get('name',''), local_settings.get('user_name','')]
    clean = lambda value: redact(value, names, terms_from(local_settings))
    snapshot = session.snapshot(task)
    usage = {'requests':0,'input_tokens':0,'output_tokens':0}
    decision = None
    selected_reference = bool(task['context'].get('reference_task_id'))
    job = snapshot.get('job') if isinstance(snapshot.get('job'), dict) else {}
    confirmed_company = job.get('company', '')
    if task['job_id'] and not selected_reference:
        usage['requests'] = 1
        candidate = classify_intent(intent_settings or settings, clean(instruction),
            history=clean(session.history[-2:]),
            job_title=snapshot.get('job',{}).get('title',''),
            selected_reference={key:snapshot['selected_reference'].get(key)
                                for key in ('task_id','kind','title')}
                               if isinstance(snapshot.get('selected_reference'),dict) else None,
            cancelled=lambda:not store.still_running(task['id'],task['claim_token']),
            timeout=min(10,max(1,timeout/4)),usage_out=usage)
        if candidate:
            # The classifier sees redacted text; authorization is bound to the
            # original saved user turn, never to a model-authored instruction.
            if candidate['kind'] == 'chat' or candidate.get('evidence','') in instruction:
                decision = {**candidate,'source_hash':source_hash(instruction)}
        # A local current-turn detector recovers ordinary company questions if
        # the intent model returns chat or is unavailable. A selected result,
        # quoted text, and third-party instructions never authorize research.
        if decision and decision.get('kind') == 'company_information_request':
            if not company_request_matches_target(instruction, confirmed_company):
                decision = {'kind':'chat','source':decision.get('source','model'),
                            'source_hash':source_hash(instruction)}
        if ((decision is None or decision.get('kind') == 'chat') and not selected_reference):
            if company_information_requested(instruction, confirmed_company):
                decision = {'kind':'company_information_request','source':'rule',
                            'source_hash':source_hash(instruction), 'evidence':instruction[:160]}
    if not store.still_running(task['id'],task['claim_token']):
        raise Problem('对话已取消')
    usage['input_tokens'] = usage.get('prompt_tokens',0)
    usage['output_tokens'] = usage.get('completion_tokens',0)
    if decision and decision['kind'] == 'company_information_request':
        from .company import Company
        from .company_research import CompanyResearch
        from .search_provider import research_search_provider
        company_name = confirmed_company
        if company_name:
            try:
                search_provider = research_search_provider(
                    local_settings,
                    cancelled=lambda:not store.still_running(task['id'],task['claim_token']))
                research = CompanyResearch(Company(store), search_provider=search_provider)
                preview = research.research(
                    company_name, instruction, job_id=task.get('job_id'),
                    allow_network=True,
                    timeout=min(20, max(2, timeout-(time.monotonic()-began))),
                )
            except Problem as exc:
                # Company research is enrichment for ordinary chat. A network
                # failure must leave the user with a usable chat turn and a
                # concrete retry/source-url instruction, rather than aborting
                # the whole dialogue.
                preview = {
                    'company_name': company_name, 'question': instruction,
                    'sources': [], 'facts': [],
                    'warnings': [str(exc), '企业公开资料暂时不可用；可提供企业官网公开 HTTPS URL 后重试，或稍后再试'],
                }
            except Exception:
                preview = {
                    'company_name': company_name, 'question': instruction,
                    'sources': [], 'facts': [],
                    'warnings': ['企业公开资料暂时不可用；可提供企业官网公开 HTTPS URL 后重试，或稍后再试'],
                }
            task['context']['company_research'] = preview
        else:
            task['context']['company_research'] = {
                'company_name':'', 'question':instruction, 'sources':[], 'facts':[],
                'warnings':['当前没有已确认目标公司，无法开展企业资料研究；请先选择一个已确认岗位'],
            }
        research_preview = task['context']['company_research']
        saved_company = snapshot.get('company_background') or {}
        if not research_preview.get('sources') and not saved_company.get('evidence'):
            warnings = research_preview.get('warnings') or ['没有找到可关联到当前公司的公开来源']
            reply = (f'这次未取得“{company_name or "当前公司"}”可引用的企业资料，不能据此判断产品、业务或风评。'
                     + '\n\n' + str(warnings[0])
                     + '\n\n可以在设置中检查“公司研究的搜索来源”，或点击“研究公司”提供官网公开 HTTPS 页面后重试。研究成功后会先显示来源预览，由你确认是否保存。')
            result = {'reply':reply, 'history':session.history + [{'user':instruction,'assistant':reply}],
                      'usage':usage, 'tool_calls':[], 'fact_candidate':False,
                      'review':{'performed':False,'issues':[],'revised':False}, 'actions':[],
                      'seconds':round(time.monotonic()-began,3),'first_text_seconds':None,
                      'intent':{'source':decision.get('source','model'),'kind':'company_information_request'},
                      'research_status':'no_sources'}
            session.finish(task,result)
            return result
        result = run_process(settings, task=task, sandbox=session, authorized=False, timeout=timeout-(time.monotonic()-began), on_delta=on_delta)
        result['intent'] = {'source':decision.get('source','model'),'kind':'company_information_request'}
        return result
    if decision and decision['kind'] in ACTION_KINDS:
        receipt = session.create_special(task, decision['kind'],intent_decision=decision)
        result = session.intent_result(task,receipt,decision,time.monotonic()-began,usage)
        session.finish(task,result)
        return result
    # A valid model chat decision is final. Rules are only a fallback when
    # classification was unavailable; a cited result always remains chat.
    legacy_kind = rule_fallback_kind(instruction) if task['job_id'] and decision is None and not selected_reference else None
    if legacy_kind:
        fallback = {'kind':legacy_kind,'source':'rule'}
        if legacy_kind == 'analyze_job':
            receipt = session.create_analysis(task,instruction,authorized=True)
        else:
            # The original sentence routes are preserved for compatibility.
            receipt = session.create_special(task,legacy_kind,intent_decision=fallback)
        result = session.intent_result(task,receipt,fallback,time.monotonic()-began,usage)
        session.finish(task,result)
        return result
    if task['job_id'] and not selected_reference and not discussion_only(instruction) and decision is None and needs_task_clarification(instruction):
        reply = ('这次没有创建后台任务；我还不能可靠确认你要发起哪一项。'
                 '请在当前岗位点击“深入分析”等对应专项按钮，或明确写出任务要求。')
        result = {'reply':reply,
                  'history':session.history + [{'user':instruction,'assistant':reply}],
                  'usage':usage,'tool_calls':[],'fact_candidate':False,
                  'review':{'performed':False,'issues':[],'revised':False},'actions':[],
                  'seconds':round(time.monotonic()-began,3),'first_text_seconds':None,
                  'intent':{'source':decision.get('source') if decision else 'unavailable',
                            'kind':'chat'}}
        session.finish(task,result)
        return result
    remaining = timeout - (time.monotonic()-began)
    if remaining <= 0:
        raise Problem('对话超过总时限')
    def safe_delta(value):
        # A chat model cannot create a task on this path. Hide provisional
        # claims of creation before the final ledger check below.
        if not re.search(r'已创建|已经创建|已提交|已经提交|任务已创建', value):
            on_delta(value)
    result = run_process(settings,task=task,sandbox=session,authorized=False,
                         timeout=remaining,on_delta=safe_delta if on_delta else None)
    if (not any(isinstance(action, dict) and action.get('id') for action in result.get('actions', []))
            and re.search(r'(?:已|已经)(?:创建|提交).{0,16}(?:后台|分析|简历|面试|HR|任务)|'
                          r'(?:后台|分析|简历|面试|HR).{0,12}任务.{0,8}(?:已|已经)(?:创建|提交)',
                          result.get('reply', ''))):
        # A free-form answer cannot claim a side effect absent from the ledger.
        result['reply'] = '这次没有创建后台任务。请先选择目标岗位，再点击对应的专项按钮，或明确写出要创建的任务。'
        if isinstance(result.get('history'), list) and result['history']:
            last = result['history'][-1]
            if isinstance(last, dict) and 'assistant' in last:
                last['assistant'] = result['reply']
    result['seconds'] = round(time.monotonic()-began,3)
    result['usage']['requests'] = result['usage'].get('requests',0) + usage['requests']
    result['usage']['input_tokens'] = result['usage'].get('input_tokens',0) + usage.get('prompt_tokens',0)
    result['usage']['output_tokens'] = result['usage'].get('output_tokens',0) + usage.get('completion_tokens',0)
    result['intent'] = {'source':decision.get('source') if decision else 'rule_fallback',
                        'kind':decision['kind'] if decision else 'chat'}
    return result


def run_process(settings, *, task, sandbox, authorized=False, timeout=120, cancelled=lambda: False,
                on_delta=None, python=None):
    """Bound model and tool rounds by one deadline; kill the child on cancel."""
    validate_url(settings["base_url"])
    local_settings = sandbox.companion.settings()
    names = [task["context"]["profile"].get("name", ""), local_settings.get("user_name", "")]
    clean = lambda value: redact(value, names, terms_from(local_settings))
    request = {"settings": {k: settings.get(k, "") for k in ("base_url", "api_model", "api_key")},
        "user_text": clean(task["context"]["instruction"]), "context": sandbox.snapshot(task),
        "history": clean(sandbox.history[-4:]), "allow_task_creation": authorized is True}
    if len(json.dumps({k: v for k, v in request.items() if k != "settings"}, ensure_ascii=False)) > 40000:
        raise Problem("这次讨论的必要材料太长，请缩短补充内容后重试")
    began = time.monotonic()
    proc = subprocess.Popen([python or sys.executable, "-m", "app.dialogue_child"], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    events = queue.Queue(maxsize=16)
    stopped = threading.Event()
    def read_events():
        while not stopped.is_set():
            line = proc.stdout.readline(MAX_EVENT + 1)
            if not line:
                event = {"type": "error", "message": "模型进程提前结束"}
            elif len(line) > MAX_EVENT:
                event = {"type": "error", "message": "对话返回超过预算"}
            else:
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                except ValueError:
                    event = {"type": "error", "message": "模型进程协议无效"}
            while not stopped.is_set():
                try:
                    events.put(event, timeout=.05)
                    break
                except queue.Full:
                    pass
            if event.get("type") in ("result", "error"):
                break
    reader = threading.Thread(target=read_events, daemon=True)
    reader.start()
    first_text = None
    actions = []
    try:
        if cancelled():
            raise Problem("对话已取消")
        proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        while True:
            if cancelled() or not sandbox.store.still_running(task["id"], task["claim_token"]):
                raise Problem("对话已取消")
            remaining = timeout - (time.monotonic() - began)
            if remaining <= 0:
                raise Problem("对话超过总时限")
            try:
                event = events.get(timeout=min(.05, remaining))
            except queue.Empty:
                continue
            kind = event.get("type")
            if kind == "delta":
                value = event.get("text", "")
                if not isinstance(value, str) or len(value) > 12000:
                    raise Problem("对话正文超过预算")
                boundaries = list(re.finditer(r"[。！？\n]", value))
                text = clean(value[:boundaries[-1].end()]) if boundaries else ""
                if text:
                    first_text = first_text or round(time.monotonic() - began, 3)
                    if on_delta:
                        on_delta(text)
            elif kind == "action":
                if cancelled() or time.monotonic() - began >= timeout:
                    raise Problem("对话已取消或超时")
                receipt = sandbox.create_analysis(task, event.get("instruction", ""), authorized=authorized)
                actions.append(receipt)
                proc.stdin.write(json.dumps({"action_result": receipt}, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            elif kind == "error":
                # Provider exception bodies must never be exposed.
                code = event.get("code", "unknown")
                code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z_]{1,60}", code) else "unknown"
                if code == "UsageLimitExceeded":
                    failure = Problem("对话达到模型调用次数或输出预算上限；本轮未完成，请查看实验记录")
                elif code == "ReviewValidationError":
                    failure = Problem("事实复核的修正无法应用；本轮草稿未展示，请重试")
                else:
                    failure = Problem(f"对话模型调用失败（{code}）；请核对工具调用兼容性、网络和额度")
                raw = event.get("diagnostics") or {}
                failure.diagnostics = {k: raw[k] for k in ("requests", "input_tokens", "output_tokens", "http_status")
                                       if isinstance(raw.get(k), int)}
                if raw.get("stage") in ("dialogue", "grounding_review"):
                    failure.diagnostics["stage"] = raw["stage"]
                if actions:
                    return sandbox.receipt_result(actions, time.monotonic() - began, failure.diagnostics)
                raise failure
            elif kind == "result":
                if cancelled() or time.monotonic() - began >= timeout:
                    raise Problem("对话已取消或超时")
                result = clean({k: event.get(k) for k in ("reply", "history", "usage", "tool_calls", "review", "fact_candidate")})
                result["fact_candidate"] = result.get("fact_candidate") is True
                if not isinstance(result["reply"], str) or not result["reply"].strip() or len(result["reply"]) > 12000:
                    raise Problem("对话没有返回有效正文")
                if not isinstance(result["history"], list):
                    raise Problem("对话历史格式无效")
                result.update(seconds=round(time.monotonic() - began, 3), first_text_seconds=first_text,
                              actions=actions)
                sandbox.finish(task, result)
                return result
    except Problem:
        if actions and sandbox.store.still_running(task['id'], task['claim_token']):
            return sandbox.receipt_result(actions, time.monotonic() - began, {})
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise Problem("对话传输失败；未保存原始异常") from None
    finally:
        stopped.set()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        reader.join(timeout=.5)
        proc.stdin.close()
        proc.stdout.close()
