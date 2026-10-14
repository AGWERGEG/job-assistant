"""Explicit, local-only import drafts from supported public online resume pages."""
import hashlib
import json
import time
import uuid
from urllib.parse import urlparse

from .store import Problem, require_object, text_field


SCHEMA = "job-assistant.boss-resume.v1"
ZHAOPIN_SCHEMA = "job-assistant.zhaopin-resume.v1"
SCHEMAS = {SCHEMA: "boss-online-resume", ZHAOPIN_SCHEMA: "zhaopin-online-resume"}
SECTION_KEYS = ("advantage", "expectations", "work", "projects", "education", "certificates", "custom")
SECTION_LABELS = {
    "advantage": "个人优势",
    "expectations": "期望职位",
    "work": "工作经历",
    "projects": "项目经历",
    "education": "教育经历",
    "certificates": "资格证书",
    "custom": "其他经历",
}
STATUSES = {"present", "empty", "unavailable"}


def init_tables(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS profile_import_drafts (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_url TEXT NOT NULL,
            content_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            created REAL NOT NULL
        );
    ''')


def _source_url(value, schema):
    url = text_field(value, "简历来源", 1000, True)
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise Problem("简历来源端口无效") from exc
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        raise Problem("简历来源必须是受支持站点的 HTTPS 在线简历页")
    if schema == SCHEMA:
        if parsed.hostname not in ("www.zhipin.com", "zhipin.com") or parsed.path.rstrip("/") != "/web/geek/resume":
            raise Problem("BOSS 草稿必须来自 BOSS 本人在线简历页")
        return "https://www.zhipin.com/web/geek/resume"
    if schema == ZHAOPIN_SCHEMA:
        if parsed.hostname != "i.zhaopin.com" or parsed.path.rstrip("/") != "/resume":
            raise Problem("智联草稿必须来自智联本人在线简历页")
        return "https://i.zhaopin.com/resume"
    raise Problem("在线简历数据版本不支持")


def _section(key, value):
    if not isinstance(value, dict):
        raise Problem(f"{SECTION_LABELS[key]}结构无效")
    status = value.get("status")
    if status not in STATUSES:
        raise Problem(f"{SECTION_LABELS[key]}读取状态无效")
    items = value.get("items", [])
    if not isinstance(items, list) or len(items) > 50:
        raise Problem(f"{SECTION_LABELS[key]}条目过多")
    clean = []
    for item in items:
        item = text_field(item, SECTION_LABELS[key], 12000)
        if item and item not in clean:
            clean.append(item)
    if status == "present" and not clean:
        raise Problem(f"{SECTION_LABELS[key]}标记为已读取但没有内容")
    if status != "present" and clean:
        raise Problem(f"{SECTION_LABELS[key]}读取状态与内容不一致")
    return {"status": status, "items": clean}


def normalize_resume(value):
    require_object(value)
    schema = value.get("schema")
    if not isinstance(schema, str) or schema not in SCHEMAS:
        raise Problem("在线简历数据版本不支持")
    source_url = _source_url(value.get("source_url", ""), schema)
    name = text_field(value.get("name", ""), "姓名", 100)
    if "*" in name or "@" in name or any(ch.isdigit() for ch in name):
        name = ""
    sections = value.get("sections")
    if not isinstance(sections, dict) or set(sections) != set(SECTION_KEYS):
        raise Problem("在线简历栏目不完整")
    clean = {
        "schema": schema,
        "source_url": source_url,
        "name": name,
        "sections": {key: _section(key, sections[key]) for key in SECTION_KEYS},
    }
    if not any(section["status"] == "present" for section in clean["sections"].values()):
        raise Problem("没有读到可导入的在线简历内容")
    return clean


def _fingerprint(content):
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _draft(row):
    content = json.loads(row["content_json"])
    site = "智联" if row["source"] == "zhaopin-online-resume" else "BOSS"
    return {
        "id": row["id"],
        "source": row["source"],
        "source_url": row["source_url"],
        "created": row["created"],
        "content": content,
        "warnings": [
            f"{site} 页面中的手机号、邮箱等为掩码时无法还原，请在本机档案中自行补充。",
            "附件、头像、简历诊断、隐私设置和平台推荐没有导入。",
            "加入编辑器不会自动保存或发送；请逐项核对后再保存并确认脱敏。",
        ],
    }


class ProfileImport:
    def __init__(self, store):
        self.store = store

    def save(self, value):
        require_object(value)
        content = normalize_resume(value.get("resume"))
        fingerprint = _fingerprint(content)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM profile_import_drafts WHERE fingerprint=?", (fingerprint,)).fetchone()
            if not row:
                draft_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO profile_import_drafts VALUES(?,?,?,?,?,?)",
                    (draft_id, SCHEMAS[content["schema"]], content["source_url"],
                     json.dumps(content, ensure_ascii=False, separators=(",", ":")), fingerprint, time.time()),
                )
                row = db.execute("SELECT * FROM profile_import_drafts WHERE id=?", (draft_id,)).fetchone()
        return _draft(row)

    def read(self, draft_id):
        draft_id = text_field(draft_id, "导入草稿", 100, True)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM profile_import_drafts WHERE id=?", (draft_id,)).fetchone()
        if not row:
            raise Problem("在线简历草稿不存在或已删除", 404)
        return _draft(row)

    @staticmethod
    def editor_values(draft):
        content = draft["content"]
        facts = []
        for key in ("advantage", "work", "projects", "education", "certificates", "custom"):
            section = content["sections"][key]
            if section["status"] == "present":
                facts.append(SECTION_LABELS[key] + "：\n" + "\n\n".join(section["items"]))
        preferences = content["sections"]["expectations"]
        return {
            "name": content["name"],
            "preferences": "\n".join(preferences["items"]) if preferences["status"] == "present" else "",
            "facts": "\n\n".join(facts),
        }
