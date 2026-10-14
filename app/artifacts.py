"""Helpers for exposing bounded, redacted professional task artifacts."""
import json
from .privacy import redact, terms_from
from .task_labels import display_name

ALLOWED_KINDS = ('tailor_resume','analyze_job','interview_prep','interview_review','suggest_reply')

def _stale(store, result, job_id):
    with store.connect() as db:
        p = db.execute('SELECT revision FROM profile WHERE id=1').fetchone()
        j = db.execute('SELECT revision FROM jobs WHERE id=?',(job_id,)).fetchone()
    return bool(result.get('profile_revision') != (p[0] if p else 0) or result.get('job_revision') != (j[0] if j else 0))

def list_artifacts(store, job_id, limit=20, include_result=True):
    with store.connect() as db:
        sequence_rows = db.execute("SELECT id,kind,created FROM tasks WHERE job_id=? AND kind IN (%s) ORDER BY created,id" % ','.join('?'*len(ALLOWED_KINDS)), (job_id,*ALLOWED_KINDS)).fetchall()
        rows = db.execute("SELECT * FROM tasks WHERE job_id=? AND kind IN (%s) AND status='done' ORDER BY updated DESC,id DESC LIMIT ?" % ','.join('?'*len(ALLOWED_KINDS)), (job_id,*ALLOWED_KINDS,limit)).fetchall()
    sequences = {}
    counters = {}
    for row in sequence_rows:
        counters[row['kind']] = counters.get(row['kind'], 0) + 1
        sequences[row['id']] = counters[row['kind']]
    out=[]
    for row in rows:
        result=json.loads(row['result_json'] or '{}')
        stale=_stale(store,result,job_id)
        summary=(result.get('summary') or result.get('decision') or result.get('primary_output') or '')[:500]
        item={'task_id':row['id'],'kind':row['kind'],'status':row['status'],'created':row['created'],'updated':row['updated'],'stale':stale,'title':result.get('title') or row['kind'],'label':result.get('label') or result.get('title') or row['kind'],'display_name':display_name(row['kind'], sequences[row['id']]),'display_index':sequences[row['id']],'preview':summary}
        if include_result:
            item.update({'primary_output':result.get('primary_output') or '', 'result_markdown':result.get('markdown') or result.get('primary_output') or '', 'references':result.get('references') or []})
        out.append(item)
    return out

def artifact_snapshot(store, job_id, settings, limit=4):
    # The dialogue needs an index, not every historical report body. A result
    # explicitly selected by the user is carried separately in the task's
    # bounded reference snapshot.
    items=list_artifacts(store,job_id,limit=limit,include_result=False)
    clean_names=[]
    with store.connect() as db:
        p=db.execute('SELECT name FROM profile WHERE id=1').fetchone()
        if p: clean_names.append(p[0])
    safe=redact(items,clean_names,terms_from(settings))
    for item, original in zip(safe,items):
        item['task_id']=original['task_id']
    return safe
