"""Local companion moments and factual retrospectives. No model calls."""
from datetime import datetime, timezone
from .companion import Companion
from .journey import Journey
from .store import Problem

BLESSINGS = {
    'gentle': {
        'rest': '今天先到这里也可以。没有回复的消息，不是对你的定论。喝口水，离开屏幕一会儿，下一步可以晚一点再想。',
        'step': '这一小步也值得记下来。你不必一天解决所有问题，先把眼前这件事照顾好。',
        'interview': '面试也是你了解对方的机会。带上真实做过的事，也带上你想问的问题，不用把自己说成无所不能。',
        'offer': '恭喜，你收到了一个新的选择。先好好开心一下，再慢慢核对工作内容、条件和自己的感受，不必急着替所有人做决定。',
        'joined': '这段求职路先走到这里了。愿新工作里有值得学的东西，也有能好好休息的日子。你的生活不只属于工作。',
    },
    'direct': {
        'rest': '今天可以收工了。招聘结果受很多因素影响，别拿一条未读消息给自己打分。休息好，再决定下一步。',
        'step': '这一步记下了。接下来只挑一件最有用的事做，不必用忙碌证明自己。',
        'interview': '准备两件能讲清的真实经历，再想好两个反问。你也在选公司，不是只等对方给你打分。',
        'offer': '恭喜，拿到一个选择。开心之后核对岗位、薪酬结构和约定，再决定接不接受；offer不等于必须答应。',
        'joined': '这一程完成了。新工作继续观察、继续学习，也记得留住自己的边界。祝你做得踏实，生活也过得自在。',
    },
}
AUTHOR_NOTE = '希望这个搭子曾在你不知道怎么开口、怎么整理经历的时候，帮你少绕一点路。走到这里，做决定和付出努力的人一直是你。愿你接下来遇到尊重你的人，做有收获的事，也有时间照顾自己的生活。—— 求职搭子作者'


class Milestones:
    def __init__(self, store):
        self.store = store

    def blessing(self, occasion='rest'):
        if occasion not in ('rest', 'step', 'interview'):
            raise Problem('祝福场景无效')
        settings = Companion(self.store).settings()
        return {'text': BLESSINGS[settings['persona']][occasion], 'local': True}

    def retrospective(self):
        state = Journey(self.store).state()
        events, summary = state['events'], dict(state['summary'])
        with self.store.connect() as db:
            versions = [r[0] for r in db.execute('SELECT created FROM resume_versions')]
        times = [r['at'] for r in events] + versions
        first, last = (min(times), max(times)) if times else (None, None)
        summary.update(interviews=sum(r['kind'] == 'interview' for r in events),
                       interviews_done=sum(r['kind'] == 'interview_done' for r in events),
                       offers=sum(r['kind'] == 'offer' for r in events),
                       first_at=first, last_at=last,
                       span_days=round((last-first)/86400, 1) if times else 0)
        # Actual success only comes from an explicit user-confirmed record.
        success = next((r for r in events if r['kind'] in ('offer', 'joined')), None)
        settings = Companion(self.store).settings()
        title = ('新的开始，祝你顺利' if success['kind'] == 'joined' else '恭喜，收到一个新的选择') if success else '我们一起走过的这段路'
        wish = BLESSINGS[settings['persona']][success['kind'] if success else 'step']
        dates = (datetime.fromtimestamp(first, timezone.utc).astimezone().strftime('%Y-%m-%d') + ' 至 ' + datetime.fromtimestamp(last, timezone.utc).astimezone().strftime('%Y-%m-%d')) if times else '尚无记录'
        note = '仅统计本机用户确认的进展及已验收简历；生成、复制和分析次数不算投递或发送。日期为记录时间，跨度从首条进展/验收版本到最后一条，不代表完整求职周期。同公司优先按BOSS公司ID去重，否则按已保存名称。'
        text = (f'{title}\n\n本机累计记录：{dates}\n'
                f'投递 {summary["applications"]} 次，涉及 {summary["companies"]} 家公司\n'
                f'验收简历 {summary["resume_versions"]} 个版本（不是全部修改次数）\n'
                f'实际发送招呼 {summary["greetings"]} 次\n'
                f'面试邀请 {summary["interviews"]} 次，面试完成 {summary["interviews_done"]} 次\n'
                f'收到offer {summary["offers"]} 次\n记录跨度 {summary["span_days"]} 天\n\n'
                f'{wish}\n\n来自作者的一句话\n{AUTHOR_NOTE}\n\n统计口径：{note}')
        # No profile, event notes, job names or private contacts in this output.
        return {'title': title, 'success': bool(success), 'success_event': success['id'] if success else None,
                'summary': summary, 'dates': dates, 'wish': wish, 'author_note': AUTHOR_NOTE,
                'note': note, 'text': text, 'local': True}
