"""Public company evidence from supported job sites. No crawler or private API."""
import hashlib
import json
import re
import time
from urllib.parse import urlparse
from .store import Problem, text_field, require_object


ZHAOPIN_HOSTS = ('www.zhaopin.com', 'zhaopin.com')


def _zhaopin_company_path(path):
    match = re.fullmatch(r'/companydetail/([^/]+)\.(?:htm|html)', path, re.I)
    if match:
        return match.group(1)
    match = re.fullmatch(r'/companydetail/jobs-([^/]+)/?', path, re.I)
    return match.group(1) if match else None


def _company_site(key):
    return 'zhaopin' if key.startswith('zhaopin:') else 'boss'


def _job_identity(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if host in ('www.zhipin.com', 'zhipin.com'):
        match = re.fullmatch(r'/job_detail/([A-Za-z0-9_-]{4,200})\.html', parsed.path)
        return ('boss', match.group(1)) if match else None
    if host in ZHAOPIN_HOSTS:
        match = re.fullmatch(r'/jobdetail/([A-Za-z0-9._~-]{4,200})\.(?:htm|html)', parsed.path, re.I)
        return ('zhaopin', match.group(1)) if match else None
    return None


def source_url(value):
    value=text_field(value,'来源',2000,True)
    u=urlparse(value)
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443):
        raise Problem('来源必须是支持站点的 HTTPS 公开页面')
    if u.hostname in ('www.zhipin.com','zhipin.com'):
        if not re.fullmatch(r'/(?:job_detail/[A-Za-z0-9_-]{4,200}|gongsi/(?:job/(?:\d+/)?)?[A-Za-z0-9_~\-]{4,200})\.html',u.path):
            raise Problem('来源必须是公司介绍、公司招聘或独立职位页')
        return 'https://www.zhipin.com'+u.path
    if u.hostname in ZHAOPIN_HOSTS:
        valid_job = re.fullmatch(r'/jobdetail/[A-Za-z0-9._~-]{4,200}\.(?:htm|html)',u.path,re.I)
        valid_company = _zhaopin_company_path(u.path)
        if not valid_job and not valid_company:
            raise Problem('来源必须是已支持的智联公司页或岗位详情页')
        return 'https://www.zhaopin.com'+u.path
    raise Problem('来源必须是支持站点的 HTTPS 公开页面')


def company_ref(value):
    key=text_field(value.get('company_key',''),'公司标识',200,True)
    url=source_url(value.get('company_url',''))
    parsed=urlparse(url)
    if parsed.hostname in ('www.zhipin.com','zhipin.com'):
        if not re.fullmatch(r'[A-Za-z0-9_~-]{4,200}',key) or key.startswith('zhaopin:'):
            raise Problem('BOSS 公司标识无效')
        if url!='https://www.zhipin.com/gongsi/'+key+'.html':raise Problem('公司标识与来源不一致')
        if value.get('source_site') not in (None,'boss'):
            raise Problem('来源站点与 BOSS 公司链接不一致')
    else:
        raw=_zhaopin_company_path(parsed.path)
        if not raw or len(raw)>180 or key!='zhaopin:'+raw or value.get('source_site')!='zhaopin':
            raise Problem('智联公司标识与来源链接不一致')
        url='https://www.zhaopin.com/companydetail/'+raw+'.htm'
    return key,url


def init_tables(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS companies (company_key TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS job_companies (job_id TEXT PRIMARY KEY,company_key TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS company_evidence (id TEXT PRIMARY KEY,company_key TEXT NOT NULL,kind TEXT NOT NULL,source_url TEXT NOT NULL,content_json TEXT NOT NULL,observed REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS job_company_research (id TEXT PRIMARY KEY,job_id TEXT NOT NULL,source_url TEXT NOT NULL,content_json TEXT NOT NULL,observed REAL NOT NULL);
    ''')


def bind(db,job_id,ref,name):
    key,url=company_ref(ref)
    db.execute('INSERT OR IGNORE INTO companies VALUES(?,?,?,1,?)',(key,name,url,time.time()))
    old=db.execute('SELECT company_key FROM job_companies WHERE job_id=?',(job_id,)).fetchone()
    if old and old[0]!=key:raise Problem('岗位公司标识冲突，请人工核对',409)
    db.execute('INSERT OR IGNORE INTO job_companies VALUES(?,?)',(job_id,key))
    return key


def dossier(db,job_id):
    c=db.execute('SELECT c.* FROM companies c JOIN job_companies j ON c.company_key=j.company_key WHERE j.job_id=?',(job_id,)).fetchone()
    job=db.execute('SELECT company,url FROM jobs WHERE id=?',(job_id,)).fetchone()
    job_rows=db.execute('SELECT * FROM job_company_research WHERE job_id=? ORDER BY observed DESC LIMIT 30',(job_id,)).fetchall()
    job_rows=[row for row in job_rows if job and
              json.loads(row['content_json']).get('target_company')==job['company'] and
              json.loads(row['content_json']).get('target_job_url')==job['url']]
    if not c and (not job or not job_rows):return None
    rows=(db.execute('SELECT * FROM company_evidence WHERE company_key=? ORDER BY observed DESC LIMIT 60',(c['company_key'],)).fetchall() if c else [])
    # Keep the latest revision of each source/section in the current dossier;
    # older evidence stays in SQLite for provenance, not as duplicate context.
    seen=set();latest=[]
    for r in rows:
        body=json.loads(r['content_json'])
        slot=(r['source_url'],r['kind'],body.get('job_key') if r['kind']=='peer_job' else '')
        if slot not in seen:latest.append(r);seen.add(slot)
    rows=latest
    evidence=[{'id':r['id'],'kind':r['kind'],'source_url':r['source_url'],'observed':r['observed'],**json.loads(r['content_json'])} for r in rows]
    evidence.extend({'id':r['id'],'kind':'research','source_url':r['source_url'],'observed':r['observed'],**json.loads(r['content_json'])} for r in job_rows)
    return {**(dict(c) if c else {'company_key':None,'name':job['company'],'url':'','updated':max((r['observed'] for r in job_rows),default=0)}),
            'revision':(c['revision'] if c else 0)+len(job_rows), 'evidence':evidence,
            'rules':'企业自述与招聘方表述不是核实事实。其他岗位只作为业务线索，不能推断离职率、编制或整个公司的实际组织结构；页面分类数量不是采集数量。'}


class Company:
    def __init__(self,store):self.store=store

    def read(self,job_id):
        job_id=text_field(job_id,'岗位',100)
        with self.store.connect() as db:return dossier(db,job_id)

    def confirm_research(self, job_id, research, *, confirmed=False, expected_target=None):
        """Persist an explicitly confirmed public-research preview as evidence."""
        if not confirmed:
            raise Problem('保存企业研究材料需要用户明确确认')
        require_object(research)
        job_id = text_field(job_id, '岗位', 100, True)
        sources = research.get('sources', [])
        if (not isinstance(sources, list) or len(sources) > 10 or
                sum(1 for source in sources if isinstance(source,dict) and source.get('already_saved') is not True) > 5):
            raise Problem('企业研究来源数量无效')
        from .company_research import public_url
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT revision,company,url FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job:
                raise Problem('岗位不存在', 404)
            binding = db.execute('SELECT company_key FROM job_companies WHERE job_id=?', (job_id,)).fetchone()
            key = binding[0] if binding else None
            if expected_target is not None:
                identity = db.execute('SELECT name,url FROM companies WHERE company_key=?', (key,)).fetchone() if key else None
                actual = {'job_revision':job['revision'],'company_key':key,
                          'company_name':identity['name'] if identity else None,
                          'company_url':identity['url'] if identity else None}
                if actual != expected_target:
                    raise Problem('岗位或公司身份已变化，请重新研究', 409)
            changed = False
            for source in sources:
                require_object(source)
                if source.get('already_saved') is True:
                    continue
                source_type = text_field(source.get('source_type', 'public_web_page'), '来源类型', 80, True)
                if source_type == 'saved_company_material':
                    continue
                url = public_url(source.get('url', ''))
                excerpt = text_field(source.get('excerpt', ''), '来源摘录', 20000, True)
                confidence = text_field(source.get('confidence', 'unverified'), '置信度', 40, True)
                observed = source.get('observed_at', time.time())
                if not isinstance(observed, (int, float)):
                    raise Problem('来源时间无效')
                body = {'text': excerpt, 'source_type': source_type, 'confidence': confidence,
                        'observed_at': observed, 'question': text_field(research.get('question', ''), '企业问题', 2000)}
                body['title']=text_field(source.get('title',''), '来源标题', 500)
                body['provider']=text_field(source.get('provider',''), '搜索来源', 40)
                if not key:
                    body.update(target_company=job['company'],target_job_url=job['url'])
                encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
                eid = hashlib.sha256(((key or ('job:'+job_id)) + '|research|' + url + '|' + encoded).encode()).hexdigest()
                if key:
                    if not db.execute('SELECT 1 FROM company_evidence WHERE id=?', (eid,)).fetchone():
                        db.execute('INSERT INTO company_evidence VALUES(?,?,?,?,?,?)', (eid, key, 'research', url, encoded, time.time()))
                        changed = True
                elif not db.execute('SELECT 1 FROM job_company_research WHERE id=?', (eid,)).fetchone():
                    db.execute('INSERT INTO job_company_research VALUES(?,?,?,?,?)', (eid, job_id, url, encoded, time.time()))
                    changed = True
            if changed and key:
                db.execute('UPDATE companies SET revision=revision+1,updated=? WHERE company_key=?', (time.time(), key))
            return dossier(db, job_id)

    def ingest(self,job_id,value):
        require_object(value)
        key,url=company_ref(value)
        name=text_field(value.get('name',''),'公司名',300,True)
        source=source_url(value.get('source_url',''))
        source_path=urlparse(source).path
        site=_company_site(key)
        page_key=_zhaopin_company_path(source_path) if site=='zhaopin' else None
        company_page=source_path.startswith('/gongsi/') if site=='boss' else page_key is not None
        if company_page and (page_key!=key.split(':',1)[1] if site=='zhaopin' else source_path.rsplit('/',1)[-1]!=key+'.html'):
            raise Problem('来源页面不属于该公司')
        entries=[]
        sections=value.get('sections',[])
        if not isinstance(sections,list) or len(sections)>8:raise Problem('公司栏目数量无效')
        for s in sections:
            require_object(s)
            if s.get('kind') not in ('introduction','products'):raise Problem('未知公司栏目')
            label=s.get('label','企业自述')
            if label not in ('企业自述','智联公司页介绍，未经独立核实','平台AI生成，仅供参考'):
                raise Problem('公司资料来源标签无效')
            entries.append((s['kind'],{'text':text_field(s.get('text',''),'栏目正文',20000,True),'partial':s.get('partial') is True,'label':label}))
        grouped={}
        for kind,body in entries:
            if kind not in grouped:grouped[kind]=body
            elif body['text'] not in grouped[kind]['text']:
                grouped[kind]['text']+='\n\n'+body['text']
                grouped[kind]['partial']=grouped[kind]['partial'] or body['partial']
        entries=list(grouped.items())
        jobs=value.get('jobs',[])
        if not isinstance(jobs,list) or len(jobs)>30:raise Problem('每次最多读取30个已加载职位卡片')
        cards=[]
        for j in jobs:
            require_object(j)
            job_url=source_url(j.get('url',''))
            job_key=text_field(j.get('job_key',''),'岗位标识',200,True)
            identity=_job_identity(job_url)
            if not identity or identity!=(site,job_key):raise Problem('岗位链接与标识或来源站点不符')
            cards.append({'job_key':job_key,'url':job_url,'title':text_field(j.get('title',''),'岗位名称',240,True),'salary':text_field(j.get('salary',''),'薪资',200),'conditions':text_field(j.get('conditions',''),'条件',1000)})
        categories=value.get('categories',[])
        if not isinstance(categories,list) or len(categories)>20:raise Problem('分类数量无效')
        categories=[text_field(c,'招聘分类',45) for c in categories]
        if cards or categories:
            if not company_page:raise Problem('职位概况只能来自公司招聘页')
            entries.append(('recruitment',{'jobs':cards,'categories':categories,'filters':text_field(value.get('filters',''),'筛选条件',1500),'coverage':'当前已加载卡片；未读取全部招聘岗位，不包含完整JD'}))
        peer=value.get('peer')
        if peer:
            require_object(peer)
            peer_url=source_url(peer.get('url',''))
            peer_key=text_field(peer.get('job_key',''),'对照岗位标识',200,True)
            peer_identity=_job_identity(peer_url)
            if not peer_identity or peer_identity!=(site,peer_key):raise Problem('对照岗位链接与来源站点不符')
            if peer.get('company_key')!=key:raise Problem('对照岗位缺少同公司身份依据')
            entries.append(('peer_job',{'job_key':peer_key,'title':text_field(peer.get('title',''),'对照职位',240,True),'text':text_field(peer.get('jd',''),'对照JD',50000,True),'job_url':peer_url,'label':'招聘方表述'}))
        if not entries:raise Problem('当前页面尚无可保存的公司栏目或岗位材料，请展开正文后重试')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            binding=db.execute('SELECT company_key FROM job_companies WHERE job_id=?',(job_id,)).fetchone()
            if not binding or binding[0]!=key:raise Problem('公司资料与目标岗位不属于同一公司，未保存',409)
            # A detail source must be the target itself or an explicitly
            # submitted peer of the same company. No arbitrary cross-job merge.
            if not company_page:
                target=db.execute('SELECT url FROM jobs WHERE id=?',(job_id,)).fetchone()
                if source!=target[0] and (not peer or source!=peer_url):raise Problem('来源岗位未与目标关联')
            changed=False
            for kind,body in entries:
                encoded=json.dumps(body,ensure_ascii=False,sort_keys=True)
                eid=hashlib.sha256((key+'|'+source+'|'+kind+'|'+encoded).encode()).hexdigest()
                old=db.execute('SELECT 1 FROM company_evidence WHERE id=?',(eid,)).fetchone()
                if not old:
                    db.execute('INSERT INTO company_evidence VALUES(?,?,?,?,?,?)',(eid,key,kind,source,encoded,time.time()))
                    changed=True
            if changed:db.execute('UPDATE companies SET revision=revision+1,updated=? WHERE company_key=?',(time.time(),key))
            return dossier(db,job_id)
