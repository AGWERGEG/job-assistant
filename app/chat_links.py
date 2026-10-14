"""Validated, conversation-specific HR chat identities and job matching."""
import hashlib
import json
import re
from urllib.parse import urlparse

from .store import Problem, require_object, text_field


def compact(value):
    return re.sub(r"[\s·•,，.。:：()（）\-－_]+", "", value).casefold()


def company_key(value):
    name = compact(value)
    for suffix in ("股份有限公司", "有限责任公司", "有限公司"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def recruiter_key(value):
    # Older BOSS JD captures included the trailing availability badge in .name.
    return compact(re.sub(r"\s+(?:在线|离线)\s*$", "", value))


def chat_identity(value):
    """Never identify a BOSS conversation by its shared /web/geek/chat URL."""
    require_object(value)
    from .bridge import safe_recruitment_url
    url, site = safe_recruitment_url(value.get("url", ""), "hr_chat")
    if site != "boss" or urlparse(url).path.rstrip('/') != '/web/geek/chat':
        raise Problem("当前仅支持核验 BOSS HR 会话")
    recruiter = text_field(value.get("recruiter_name", ""), "招聘者姓名", 100, True)
    company = text_field(value.get("company", ""), "聊天页企业", 300, True)
    title = text_field(value.get("job_title", ""), "聊天页岗位", 200, True)
    if len(compact(recruiter)) < 2 or len(company_key(company)) < 2 or len(compact(title)) < 2:
        raise Problem("聊天页招聘者、企业或岗位信息不足，暂不关联")
    raw_id = text_field(value.get("conversation_id", ""), "会话标识", 200)
    if raw_id and not re.fullmatch(r"[A-Za-z0-9._:~-]{4,200}", raw_id):
        raise Problem("聊天页会话标识无效")
    result = {"url": url, "site": site, "recruiter_name": recruiter,
              "company": company, "job_title": title}
    job_source = None
    if value.get('job_url'):
        job_url, job_site = safe_recruitment_url(value['job_url'], 'job_detail')
        if job_site != site:
            raise Problem('聊天页岗位链接与招聘网站不一致')
        from .bridge import source_identity
        job_source = source_identity(job_url)
        result['job_url'] = urlparse(job_url)._replace(query='', fragment='').geturl()
    identity = json.dumps([raw_id,compact(recruiter),company_key(company),compact(title),job_source],ensure_ascii=False)
    result['key'] = site + ":" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return result


def match_job(chat, job, expected_recruiter=""):
    from .bridge import source_identity
    source = source_identity(job["url"])
    if not source or source[0] != chat["site"]:
        return "招聘网站不一致"
    if chat.get('job_url') and source_identity(chat['job_url']) != source:
        return "聊天页岗位链接与已建档 JD 不一致"
    if company_key(job["company"]) != company_key(chat["company"]):
        return "企业名称不一致"
    if compact(job["title"]) != compact(chat["job_title"]):
        return "岗位名称不一致"
    if expected_recruiter and recruiter_key(expected_recruiter) != compact(chat["recruiter_name"]):
        return "招聘者姓名与 JD 页不一致"
    return ""
