"""Immutable snapshots for saved creator storyboard drafts."""
import hashlib
import json
import uuid


def content_hash(data):
    encoded=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def initialize(c):
    c.execute('ALTER TABLE creator_plans ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1')
    c.execute('''CREATE TABLE IF NOT EXISTS creator_plan_revisions(
      plan_id UUID NOT NULL REFERENCES creator_plans(id),
      revision INTEGER NOT NULL CHECK(revision>0),
      sha256 TEXT NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
      data JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(plan_id,revision))''')
    # Adopt the current saved draft as its first known revision. This is additive:
    # it neither changes the draft nor invents any prior approvals.
    rows=c.execute('''SELECT p.id,p.revision,p.data FROM creator_plans p
      LEFT JOIN creator_plan_revisions r ON r.plan_id=p.id AND r.revision=p.revision
      WHERE p.data IS NOT NULL AND r.plan_id IS NULL''').fetchall()
    for row in rows:
        c.execute('INSERT INTO creator_plan_revisions(plan_id,revision,sha256,data) VALUES(%s,%s,%s,%s) ON CONFLICT(plan_id,revision) DO NOTHING',
                  (row['id'],row['revision'],content_hash(row['data']),json.dumps(row['data'],ensure_ascii=False)))


def append(c,plan_id,revision,data):
    c.execute('INSERT INTO creator_plan_revisions(plan_id,revision,sha256,data) VALUES(%s,%s,%s,%s)',
              (plan_id,revision,content_hash(data),json.dumps(data,ensure_ascii=False)))


def save_locked_revision(c,row,data,expected):
    from fastapi import HTTPException
    if row['revision']!=expected:
        raise HTTPException(409,'O roteiro mudou em outra janela. Recarregue a revisão atual antes de salvar.')
    if content_hash(data)==content_hash(row['data']):return row['revision']
    revision=row['revision']+1
    c.execute('UPDATE creator_plans SET data=%s,revision=%s WHERE id=%s',
              (json.dumps(data,ensure_ascii=False),revision,row['id']))
    append(c,row['id'],revision,data)
    return revision


def history(c,plan_id):
    return c.execute('''SELECT r.revision,r.sha256,r.created_at FROM creator_plan_revisions r
      JOIN creator_plans p ON p.id=r.plan_id
      WHERE r.plan_id=%s AND p.status<>'deleted' ORDER BY r.revision DESC''',
      (plan_id,)).fetchall()


def redact_deleted_plans(c,plan_ids):
    """Remove recoverable storyboard content while retaining a minimal audit trail."""
    if not plan_ids or not c.execute("SELECT to_regclass('creator_plan_revisions') t").fetchone()['t']:
        return 0
    tombstone={'redacted':True,'reason':'permanent_deletion'}
    digest=content_hash(tombstone)
    result=c.execute('''UPDATE creator_plan_revisions
      SET data=%s::jsonb,sha256=%s WHERE plan_id=ANY(%s)''',
      (json.dumps(tombstone,separators=(',',':')),digest,plan_ids))
    return result.rowcount


def get(c,plan_id,revision):
    return c.execute('''SELECT r.plan_id,r.revision,r.sha256,r.data,r.created_at
      FROM creator_plan_revisions r JOIN creator_plans p ON p.id=r.plan_id
      WHERE r.plan_id=%s AND r.revision=%s AND p.status<>'deleted' ''',
      (plan_id,revision)).fetchone()


def require_current_revision(c,plan_id,expected):
    from fastapi import HTTPException
    row=c.execute('SELECT revision FROM creator_plans WHERE id=%s FOR UPDATE',(plan_id,)).fetchone()
    if not row:raise HTTPException(404,'Roteiro não encontrado')
    if row['revision']!=expected:
        raise HTTPException(409,'O roteiro mudou em outra janela. Recarregue a revisão atual antes de salvar.')
    return row['revision']
