"""BOSS public company evidence. No network crawler or private API."""
import hashlib
import json
import re
import time
from urllib.parse import urlparse
from .store import Problem, text_field, require_object


def source_url(value):
    value=text_field(value,'来源',2000,True)
    u=urlparse(value)
    if u.scheme!='https' or u.hostname not in ('www.zhipin.com','zhipin.com') or u.username or u.password:
        raise Problem('仅接受BOSS公开页面来源')
    if not re.fullmatch(r'/(?:job_detail/[A-Za-z0-9_-]{4,200}|gongsi/(?:job/(?:\d+/)?)?[A-Za-z0-9_~\-]{4,200})\.html',u.path):
        raise Problem('来源必须是公司介绍、公司招聘或独立职位页')
    return 'https://www.zhipin.com'+u.path


def company_ref(value):
    key=text_field(value.get('company_key',''),'公司标识',200,True)
    if not re.fullmatch(r'[A-Za-z0-9_~\-]{4,200}',key):raise Problem('公司标识无效')
    url=source_url(value.get('company_url',''))
    if url!='https://www.zhipin.com/gongsi/'+key+'.html':raise Problem('公司标识与来源不一致')
    return key,url


def init_tables(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS companies (company_key TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS job_companies (job_id TEXT PRIMARY KEY,company_key TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS company_evidence (id TEXT PRIMARY KEY,company_key TEXT NOT NULL,kind TEXT NOT NULL,source_url TEXT NOT NULL,content_json TEXT NOT NULL,observed REAL NOT NULL);
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
    if not c:return None
    rows=db.execute('SELECT * FROM company_evidence WHERE company_key=? ORDER BY observed DESC LIMIT 60',(c['company_key'],)).fetchall()
    # Keep the latest revision of each source/section in the current dossier;
    # older evidence stays in SQLite for provenance, not as duplicate context.
    seen=set();latest=[]
    for r in rows:
        body=json.loads(r['content_json'])
        slot=(r['source_url'],r['kind'],body.get('job_key') if r['kind']=='peer_job' else '')
        if slot not in seen:latest.append(r);seen.add(slot)
    rows=latest
    return {**dict(c),'evidence':[{'id':r['id'],'kind':r['kind'],'source_url':r['source_url'],'observed':r['observed'],**json.loads(r['content_json'])} for r in rows],
            'rules':'企业自述与招聘方表述不是核实事实。其他岗位只作为业务线索，不能推断离职率、编制或整个公司的实际组织结构；页面分类数量不是采集数量。'}


class Company:
    def __init__(self,store):self.store=store

    def read(self,job_id):
        job_id=text_field(job_id,'岗位',100)
        with self.store.connect() as db:return dossier(db,job_id)

    def ingest(self,job_id,value):
        require_object(value)
        key,url=company_ref(value)
        name=text_field(value.get('name',''),'公司名',300,True)
        source=source_url(value.get('source_url',''))
        path=urlparse(source).path
        company_page=path.startswith('/gongsi/')
        if company_page and path.rsplit('/',1)[-1]!=key+'.html':raise Problem('来源页面不属于该公司')
        entries=[]
        sections=value.get('sections',[])
        if not isinstance(sections,list) or len(sections)>8:raise Problem('公司栏目数量无效')
        for s in sections:
            require_object(s)
            if s.get('kind') not in ('introduction','products'):raise Problem('未知公司栏目')
            entries.append((s['kind'],{'text':text_field(s.get('text',''),'栏目正文',20000,True),'partial':s.get('partial') is True,'label':'企业自述'}))
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
            if urlparse(job_url).path!='/job_detail/'+job_key+'.html':raise Problem('岗位链接与标识不符')
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
            if urlparse(peer_url).path!='/job_detail/'+peer_key+'.html':raise Problem('对照岗位链接不符')
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
