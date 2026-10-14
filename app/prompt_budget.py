"""Deterministic task-specific prompt budgets.

The complete local profile and evidence remain in SQLite.  This module only
selects the material needed by one model call; it never invents summaries or
mutates the stored snapshot.
"""
import json
import re
from .store import Problem


PROMPT_BUDGET_VERSION = "context-budget-2"
PROMPT_BUDGETS = {
    "companion_chat": 24000, "quick_analysis": 26000, "suggest_reply": 22000,
    "analyze_job": 36000, "tailor_resume": 44000, "interview_prep": 36000,
    "interview_review": 30000, "rest_message": 14000, "closing_message": 14000,
}


def _json_chars(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _clip(value, limit):
    if not isinstance(value, str) or len(value) <= limit:
        return value
    marker = "\n[本地提示词预算已压缩]\n"
    if limit <= len(marker):
        return value[:limit]
    available = limit - len(marker)
    head = int(available * .62)
    return value[:head] + marker + value[-(available - head):]


PROFILE_BUDGETS = {
    "companion_chat": 1200,
    "rest_message": 700,
    "closing_message": 700,
    "quick_analysis": 1800,
    "suggest_reply": 1500,
    "analyze_job": 2200,
    "tailor_resume": 2600,
    "interview_prep": 2800,
    "interview_review": 2600,
}

COMPANY_BUDGETS = {
    "companion_chat": 4000,
    "quick_analysis": 1000,
    "suggest_reply": 900,
    "analyze_job": 2600,
    "tailor_resume": 1800,
    "interview_prep": 2600,
    "interview_review": 1400,
}

STOP = {
    "负责", "岗位", "职位", "要求", "工作", "相关", "能力", "优先", "经验", "公司",
    "进行", "以及", "具有", "具备", "良好", "能够", "完成", "协助", "通过", "以上",
}


def _terms(value):
    """Small local keyword set; no embedding or extra model call."""
    output = set()
    for ascii_word in re.findall(r"[A-Za-z][A-Za-z0-9+.#/-]{1,30}", value or ""):
        output.add(ascii_word.lower())
    for run in re.findall(r"[\u4e00-\u9fff]{2,40}", value or ""):
        if len(run) <= 6 and run not in STOP:
            output.add(run)
        for width in (2, 3, 4):
            for index in range(max(0, len(run) - width + 1)):
                term = run[index:index + width]
                if term not in STOP:
                    output.add(term)
    return output


def _blocks(value):
    value = (value or "").strip()
    if not value:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", value) if part.strip()]
    output = []
    for paragraph in paragraphs:
        if len(paragraph) <= 850:
            output.append(paragraph)
            continue
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if len(lines) <= 1:
            output.extend(paragraph[i:i + 700] for i in range(0, len(paragraph), 700))
            continue
        heading = lines[0] if len(lines[0]) <= 40 else ""
        current = heading
        for line in lines[1 if heading else 0:]:
            candidate = (current + "\n" + line).strip()
            if len(candidate) > 750 and current:
                output.append(current)
                current = (heading + "\n" + line).strip() if heading else line
            else:
                current = candidate
        if current:
            output.append(current)
    return output


def _score(text, terms, index=0):
    lowered = text.lower()
    overlap = sum(1 + min(2, lowered.count(term)) for term in terms if term in lowered)
    structure = 5 if re.search(r"(?:个人优势|求职目标|教育经历|工作经历|项目经历|实习经历|技能|证书|资格)", text) else 0
    date = 2 if re.search(r"(?:19|20)\d{2}|至今|现在", text) else 0
    return overlap * 3 + structure + date - index * 0.01


def select_text(value, reference, budget):
    blocks = _blocks(value)
    if not blocks or sum(len(block) for block in blocks) <= budget:
        return (value or "").strip(), len(blocks), len(blocks)
    terms = _terms(reference)
    ranked = sorted(enumerate(blocks), key=lambda item: _score(item[1], terms, item[0]), reverse=True)
    chosen = set()
    used = 0
    # Keep compact section labels/date-bearing fragments before filling by relevance.
    for index, block in ranked:
        cost = len(block) + (2 if chosen else 0)
        if used + cost <= budget or not chosen:
            chosen.add(index)
            used += cost
    selected = "\n\n".join(blocks[index] for index in sorted(chosen))
    return selected[:budget], len(chosen), len(blocks)


def _compact_profile(context, kind, reference):
    profile = context.get("profile") or {}
    budget = PROFILE_BUDGETS.get(kind, 1800)
    if kind == "tailor_resume" and context.get("accepted_resume"):
        budget = 1600
    facts, selected, total = select_text(profile.get("facts", ""), reference, budget)
    return {
        "name": "求职者",
        "preferences": (profile.get("preferences") or "")[:500],
        "facts": facts,
        "selection_note": f"本轮从本机完整档案的 {total} 个片段中发送 {selected} 个相关片段；未发送不代表没有相关经历。",
    }


def _compact_facts(items, reference, budget=1600):
    if not isinstance(items, list):
        return []
    terms = _terms(reference)
    ranked = sorted(
        enumerate(items),
        key=lambda item: _score(str(item[1].get("content", "")), terms, item[0]),
        reverse=True,
    )
    result = []
    used = 0
    for _, item in ranked:
        compact = {key: item.get(key, "") for key in ("id", "category", "content", "source")}
        compact["content"] = _clip(compact["content"], 1200)
        encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if used + len(encoded) > budget:
            continue
        result.append(compact)
        used += len(encoded)
        if len(result) >= 12:
            break
    return result


def _evidence_text(item):
    pieces = [item.get("title", ""), item.get("label", ""), item.get("source", ""),
              item.get("text", ""), item.get("coverage", ""), item.get("filters", "")]
    for job in item.get("jobs", []) if isinstance(item.get("jobs"), list) else []:
        pieces.extend([job.get("title", ""), job.get("conditions", "")])
    return "\n".join(piece for piece in pieces if isinstance(piece, str))


def _compact_company(company, kind, reference):
    if not isinstance(company, dict) or kind not in COMPANY_BUDGETS:
        return None
    terms = _terms(reference)
    evidence = company.get("evidence") if isinstance(company.get("evidence"), list) else []
    ranked = sorted(enumerate(evidence), key=lambda item: _score(_evidence_text(item[1]), terms, item[0]), reverse=True)
    result = []
    used = 0
    seen = set()
    budget = COMPANY_BUDGETS[kind]
    for _, item in ranked:
        compact = {key: item.get(key) for key in ("id", "kind", "label", "title", "source", "source_url", "source_type", "confidence", "observed", "text", "jobs", "categories", "filters", "coverage") if item.get(key) not in (None, "", [])}
        compact["source_group"] = ("saved_public_research"
                                   if compact.get("source_type") in {"public_web_page", "public_search_excerpt"}
                                   else "saved_site_material")
        # Source links are redacted before this point. Compare actual material,
        # including other-job cards, rather than the now-identical URL marker.
        identity = json.dumps({k: v for k, v in compact.items() if k != "id"}, ensure_ascii=False, sort_keys=True)
        if identity in seen:
            continue
        seen.add(identity)
        encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > 1500:
            if "text" in compact:
                compact["text"] = compact["text"][:1000]
            if "jobs" in compact:
                compact["jobs"] = [{**job, "conditions": _clip(job.get("conditions", ""), 180)} for job in compact["jobs"][:5] if isinstance(job, dict)]
            if "categories" in compact:
                compact["categories"] = compact["categories"][:8]
            encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if used + len(encoded) > budget:
            continue
        result.append(compact)
        used += len(encoded)
        if len(result) >= 5:
            break
    return {
        "name": company.get("name", ""),
        "revision": company.get("revision", 0),
        "evidence": result,
        "coverage": f"本轮发送 {len(result)} 条已保存企业材料；每条 source_group 区分站内采集与已确认公开研究，完整材料仍保存在本机，节选不足不能据此断言公司没有资料。",
    }


def _compact_company_research(research, kind):
    """Keep the current-turn public research preview in the chat prompt."""
    if not isinstance(research, dict):
        return None
    sources = []
    for source in research.get("sources") or []:
        if not isinstance(source, dict):
            continue
        sources.append({key: str(source.get(key, ""))[:1600 if key == "excerpt" else 1000]
                        for key in ("id", "url", "source_type", "confidence", "observed_at", "excerpt")
                        if source.get(key) is not None})
    facts = []
    for fact in research.get("facts") or []:
        if isinstance(fact, dict):
            facts.append({"text": str(fact.get("text", ""))[:1200],
                          "source_ids": fact.get("source_ids") or [],
                          "confidence": fact.get("confidence", "")})
    return {
        "company_name": str(research.get("company_name", ""))[:300],
        "question": str(research.get("question", ""))[:2000],
        "sources": sources[:5], "facts": facts[:5],
        "warnings": [str(item)[:500] for item in (research.get("warnings") or [])[:8]],
        "note": "本轮公开研究为未确认预览；仅可引用带来源内容，不能视为已保存事实。",
    }

def _compact_prior(items, kind):
    if not isinstance(items, list):
        return []
    result = []
    for item in items[:2]:
        compact = {key: item.get(key, "") for key in ("kind", "summary", "decision", "strategy")}
        compact["summary"] = compact["summary"][:500]
        compact["strategy"] = compact["strategy"][:1200]
        if kind == "tailor_resume" and item.get("kind") == "tailor_resume":
            compact["previous_draft"] = item.get("primary_output", "")[:3000]
        result.append(compact)
    return result


def _compact_dialogue(items, limit=4):
    if not isinstance(items, list):
        return []
    return [{"user": item.get("user", "")[:500], "assistant": item.get("assistant", "")[:800]} for item in items[-limit:]]


def compact_context(context, kind):
    """Return the task whitelist used by the model, without changing context."""
    job = context.get("job") or {}
    reference = "\n".join(str(value) for value in (job.get("title", ""), job.get("jd", ""), context.get("instruction", "")))
    compact = {
        "profile": _compact_profile(context, kind, reference),
        "job": {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "jd": (job.get("jd", "") or "")[:8000],
        },
        "instruction": context.get("instruction") or "",
        "privacy_note": context.get("privacy_note", ""),
        "career_stage": context.get("career_stage", ""),
    }
    if kind in ("suggest_reply", "companion_chat") and job.get("conversation"):
        compact["job"]["conversation"] = job.get("conversation", "")[:3000]
    facts = _compact_facts(context.get("confirmed_facts"), reference)
    if facts:
        compact["confirmed_facts"] = facts
    prior = _compact_prior(context.get("prior_results"), kind)
    if prior and kind not in ("rest_message", "closing_message"):
        compact["prior_results"] = prior
    selected = context.get('reference')
    if isinstance(selected, dict) and selected.get('task_id'):
        result = selected.get('result') or {}
        compact['reference'] = {
            'task_id': selected['task_id'], 'kind': selected.get('kind', ''),
            'stale': selected.get('stale', False),
            'profile_revision': selected.get('profile_revision'),
            'job_revision': selected.get('job_revision'),
            'result': {key: _clip(result.get(key, ''), limit) for key, limit in
                       (('summary', 500), ('decision', 500), ('strategy', 700),
                        ('primary_output', 3000), ('markdown', 1500))},
            'note': '本轮用户明确选择的成果；内容可能为节选，历史 AI 草稿不是本人事实。',
        }
    company = _compact_company(context.get("company_background"), kind, reference)
    if company:
        compact["company_background"] = company
    research = _compact_company_research(context.get("company_research"), kind)
    if research:
        compact["company_research"] = research
    if kind in ("companion_chat", "rest_message", "closing_message", "suggest_reply"):
        dialogue = _compact_dialogue(context.get("dialogue"), 4 if kind == "companion_chat" else 2)
        if dialogue:
            compact["dialogue"] = dialogue
    if kind == "tailor_resume" and context.get("accepted_resume"):
        accepted, selected, total = select_text(context.get("accepted_resume", ""), reference, 5000)
        compact["accepted_resume"] = accepted
        compact["accepted_resume_note"] = f"本轮发送已验收简历的 {selected}/{total} 个相关片段。"
    if context.get("companion"):
        compact["companion"] = True
    return _enforce_budget(compact, context, kind)


def _enforce_budget(compact, source, kind):
    """Apply a hard serialized-character cap after relevance selection."""
    budget = PROMPT_BUDGETS.get(kind, 28000)
    compact["_prompt_budget"] = {
        "version": PROMPT_BUDGET_VERSION,
        "max_chars": budget,
        "original_context_chars": _json_chars(source),
        "estimated_context_chars": 0,
        "note": "部分材料可能为节选；未发送的片段不代表没有相关经历。完整资料仍在本地。",
    }

    def measure():
        meta = compact["_prompt_budget"]
        while True:
            size = _json_chars(compact)
            if size == meta["estimated_context_chars"]:
                return size
            meta["estimated_context_chars"] = size

    def trim_text(parent, key, minimum):
        value = parent.get(key)
        if measure() <= budget or not isinstance(value, str) or len(value) <= minimum:
            return
        low, high = minimum, len(value)
        parent[key] = _clip(value, low)
        if measure() > budget:
            return
        while low < high:
            middle = (low + high + 1) // 2
            parent[key] = _clip(value, middle)
            if measure() <= budget:
                low = middle
            else:
                high = middle - 1
        parent[key] = _clip(value, low)

    def drop_oldest(items, minimum, newest_last=False):
        while len(items) > minimum and measure() > budget:
            items.pop(0 if newest_last else -1)

    # Keep the latest instruction intact. Existing relevance selection chooses
    # the profile and evidence; this pass reduces older/derived material first.
    dialogue = compact.get("dialogue", [])
    prior = compact.get("prior_results", [])
    company = compact.get("company_background", {})
    evidence = company.get("evidence", [])
    company_research = compact.get("company_research", {})
    research_sources = company_research.get("sources", [])
    research_facts = company_research.get("facts", [])
    facts = compact.get("confirmed_facts", [])
    profile = compact["profile"]
    job = compact["job"]
    drop_oldest(dialogue, 1, newest_last=True)
    drop_oldest(prior, 1)
    trim_text(compact, "accepted_resume", 2500)
    drop_oldest(evidence, 1)
    drop_oldest(research_sources, 1)
    drop_oldest(research_facts, 1)
    drop_oldest(facts, 1)
    for item in prior:
        trim_text(item, "previous_draft", 300)
        trim_text(item, "strategy", 300)
    for item in evidence:
        trim_text(item, "text", 300)
    for item in research_sources:
        trim_text(item, "excerpt", 400)
    for item in research_facts:
        trim_text(item, "text", 300)
    for item in facts:
        trim_text(item, "content", 250)
    for item in dialogue:
        trim_text(item, "assistant", 350)
    trim_text(profile, "facts", 800 if profile.get("facts") else 0)
    trim_text(job, "jd", 5000)
    trim_text(job, "conversation", 1500)
    # Short messages have smaller caps; remove optional history and drafts next.
    drop_oldest(dialogue, 0)
    drop_oldest(prior, 0)
    drop_oldest(evidence, 0)
    drop_oldest(research_sources, 0)
    drop_oldest(research_facts, 0)
    trim_text(compact, "accepted_resume", 0)
    drop_oldest(facts, 1)
    trim_text(profile, "facts", 300 if profile.get("facts") else 0)
    trim_text(job, "jd", 1500)
    trim_text(job, "conversation", 700)
    if measure() > budget:
        raise Problem("当前任务必要材料仍超过输入预算，请缩短本轮补充内容后重试；本地资料未改变")
    return compact
