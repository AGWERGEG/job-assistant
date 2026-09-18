"""Local-only export recovery for legacy redacted drafts; never a prompt input."""
import json
import re
from .store import Problem, text_field

PLACEHOLDER = re.compile(r'\[(?:本地隐去|姓名|手机号|电话|邮箱|地址|微信|链接|证件号码|长号码|密钥)\]')
LABELS = {'姓名': ('真实姓名', '姓名'), '手机号': ('手机号', '手机', '电话'),
          '邮箱': ('邮箱', '电子邮件'), '微信': ('微信号', '微信'),
          '地址': ('联系地址', '家庭住址', '现居住址', '详细地址', '住址', '地址')}


def preview_resume(store, version_id):
    version_id = text_field(version_id, '简历版本', 100, True)
    with store.connect() as db:
        row = db.execute('SELECT v.content,t.context_json FROM resume_versions v JOIN tasks t ON t.id=v.task_id WHERE v.id=?', (version_id,)).fetchone()
    if not row:
        raise Problem('简历版本不存在', 404)
    # Use the original task snapshot, not a newer person's profile or nickname.
    profile = json.loads(row['context_json']).get('profile', {})
    source = profile.get('facts', '')
    values = {k: set() for k in LABELS}
    if profile.get('name', '').strip():
        values['姓名'].add(profile['name'].strip())
    for key, aliases in LABELS.items():
        pattern = r'(?:^|[\n|｜；;，,])\s*(?:' + '|'.join(aliases) + r')\s*[:：]\s*([^\n|｜；;，,]+)'
        for match in re.finditer(pattern, source):
            value = match[1].strip()
            if value and not PLACEHOLDER.search(value):
                values[key].add(value)
    # Resume headers often omit labels. Read only the original candidate
    # resume, never the JD or HR messages; ambiguous contacts remain manual.
    phone = r'(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)'
    email = r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'
    values['手机号'] = set(re.findall(phone, source))
    values['邮箱'] = set(re.findall(email, source))
    unique = {k: next(iter(v)) for k, v in values.items() if len(v) == 1}
    content = row['content']
    restored = []
    for key, value in unique.items():
        aliases = '|'.join(LABELS[key])
        pattern = r'((?:' + aliases + r')\s*[:：]\s*)' + PLACEHOLDER.pattern
        content, count = re.subn(pattern, lambda m: m[1] + value, content)
        if key in ('手机号', '邮箱'):
            content, more = re.subn(re.escape('['+key+']'), lambda _: value, content)
            count += more
        if count:
            restored.append(key)
    # Models frequently omit the entire contact header. Restore a minimal one.
    header = []
    for key in ('姓名', '手机号', '邮箱'):
        if key in unique and unique[key] not in content:
            header.append(key + '：' + unique[key]); restored.append(key)
    if header:
        content = '\n'.join(header) + '\n\n' + content
    warnings = ['仅在本机回填，不调用模型。请核对姓名、联系方式及正文后下载。']
    ambiguous = [k for k, v in values.items() if len(v) > 1]
    if ambiguous:
        warnings.append('原始资料有多个值，未猜测：' + '、'.join(ambiguous))
    missing = [k for k in ('姓名', '手机号', '邮箱') if k not in unique]
    if missing:
        warnings.append('未定位到唯一字段，请手动补充：' + '、'.join(missing))
    if PLACEHOLDER.search(content):
        warnings.append('仍有脱敏占位符。旧版通用占位符无法准确反推学校/公司等信息，请逐项补齐或删除无关字段。')
    warnings.append('身份证、密钥等不自动回填；地址、微信仅在稿件已有对应字段且原值唯一时回填。')
    return {'content': content, 'warnings': warnings, 'restored': sorted(set(restored))}


def checked_content(value):
    if value.get('confirmed') is not True:
        raise Problem('请先核对本机回填后的简历并确认')
    content = text_field(value.get('content', ''), '导出简历', 30000, True)
    if PLACEHOLDER.search(content):
        raise Problem('正文仍有脱敏占位符，请补齐或删除无关字段后导出')
    return content
