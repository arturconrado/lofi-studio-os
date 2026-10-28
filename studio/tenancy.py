"""Tenant identifiers come from authenticated membership, never request headers."""
from contextvars import ContextVar
from uuid import UUID
import os

_UNBOUND = object()
WORKSPACE = ContextVar('lofi_workspace', default=_UNBOUND)

def schema_name(workspace):
    return 'ws_' + UUID(str(workspace)).hex

def active_workspace():
    # Worker processes may inherit their workspace from the environment when no
    # request/task context is bound. An explicit None means public scope and must
    # never fall through to that worker-only default.
    value=WORKSPACE.get()
    if value is _UNBOUND:value=os.getenv('LOFI_WORKSPACE_ID')
    return str(UUID(str(value))) if value else None

class ScopedStorage:
    def __init__(self, client, workspace):
        self.client=client
        self.prefix='workspaces/'+str(UUID(str(workspace)))+'/'
    def key(self,value):
        if not isinstance(value,str) or value.startswith('/') or '..' in value.split('/'):
            raise ValueError('Invalid media key')
        return self.prefix+value
    def get_object(self,**kw):
        return self.client.get_object(**(kw|{'Key':self.key(kw['Key'])}))
    def head_object(self,**kw):
        return self.client.head_object(**(kw|{'Key':self.key(kw['Key'])}))
    def put_object(self,**kw):
        return self.client.put_object(**(kw|{'Key':self.key(kw['Key'])}))
    def download_file(self,bucket,key,*args,**kw):
        return self.client.download_file(bucket,self.key(key),*args,**kw)
    def upload_file(self,path,bucket,key,*args,**kw):
        return self.client.upload_file(path,bucket,self.key(key),*args,**kw)
    def head_bucket(self,**kw):return self.client.head_bucket(**kw)

class ScopedQueue:
    def __init__(self,client,workspace):
        self.client=client;self.prefix='workspace:'+str(UUID(str(workspace)))+':'
    def set(self,key,*args,**kwargs):return self.client.set(self.prefix+key,*args,**kwargs)
    def exists(self,key):return self.client.exists(self.prefix+key)
    def ping(self):return self.client.ping()
