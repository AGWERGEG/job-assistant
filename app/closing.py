"""Explicit chat intent and local-only closing summary, never model statistics."""
import re
from datetime import datetime

AUTHOR_NOTE = '希望这个搭子曾在你不知道怎么开口、怎么整理经历的时候，帮你少绕一点路。走到这里，做决定和付出努力的人一直是你。愿你接下来遇到尊重你的人，做有收获的事，也有时间照顾自己的生活。—— 求职搭子作者'


def declares_joined(message):
    # Conservative positive first-person statement. Quotes, hypothetical,
    # future, negation and requests stay ordinary chat; never classify a JD.
    if re.search(r'[?？“”「」『』"\']|如果|假如|假设|比如|例如|要是|还没|尚未|没有|未入职|没入职|不入职|不是|不算|不确定|准备|打算|计划|即将|将要|明天|下周|下月|后天|可能|听说|说过|说了|这句话|怎么|如何|帮我|请问|翻译|改写|能否|是否|才怪|开玩笑|骗你|梦到|以前|去年|离职', message):
        return False
    return bool(re.search(r'(?:^|[，,。！!\n；;])\s*我(?:已经|已|今天已经|今天|刚刚|刚|终于|正式)?(?:正式|成功)?入职(?:了|啦|！|!|。|，|,|\s|$)', message))


def closing_snapshot(db):
    """Aggregate only, using the task creation transaction for a stable record."""
    rows=db.execute('SELECT e.*,j.company FROM career_events e LEFT JOIN jobs j ON e.job_id=j.id').fetchall()
    versions=[r[0] for r in db.execute('SELECT created FROM resume_versions')]
    apps=[r for r in rows if r['kind']=='applied'];companies=set()
    for r in apps:
        ref=db.execute('SELECT company_key FROM job_companies WHERE job_id=?',(r['job_id'],)).fetchone()
        companies.add('id:'+ref[0] if ref else 'name:'+(r['company'] or r['job_id']).strip())
    times=[r['at'] for r in rows]+versions
    dates='尚无已记录进展'
    if times:
        dates=' 至 '.join(datetime.fromtimestamp(t).astimezone().strftime('%Y-%m-%d') for t in (min(times),max(times)))
    span=round((max(times)-min(times))/86400,1) if times else 0
    return (f'这一程的本机记录\n{dates}\n'
            f'已确认投递 {len(apps)} 次，涉及 {len(companies)} 家公司；'
            f'验收简历 {len(versions)} 个版本；实际发招呼 {sum(r["kind"]=="greeting_sent" for r in rows)} 次；记录跨度 {span} 天。\n'
            '仅统计已确认进展与验收版本，生成/复制不算发送；未记录不等于没有发生。跨度按首末记录时间，版本数不等于全部修改次数。\n'
            '本次聊天不会自动把入职关联到当前岗位，进展记录由你核对。')
