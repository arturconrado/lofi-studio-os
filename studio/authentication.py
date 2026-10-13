"""Session authentication and membership. Legacy Basic stays platform-only.

Identity tables are global; content lives in separate tenant schemas. Signup
is disabled until transactional email and a public origin are configured.
"""
import hashlib
import hmac
import json
import os
import secrets
import uuid
from cryptography.fernet import Fernet
from datetime import datetime, timedelta, timezone
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from .tenancy import WORKSPACE, schema_name
from .email_delivery import configured as email_configured

router=APIRouter(prefix='/api/auth')
COOKIE='lofi_session'
ROLES={'workspace_owner','workspace_admin','operator','creator','viewer'}

def connection():
    return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,connect_timeout=5)

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def password_hash(password):
    salt=secrets.token_bytes(16)
    value=hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=1,dklen=32,maxmem=128*1024*1024)
    return 'scrypt$32768$8$1$'+salt.hex()+'$'+value.hex()

def verify(password,stored):
    try:
        algorithm,n,r,p,salt,wanted=stored.split('$')
        if algorithm!='scrypt' or (n,r,p)!=('32768','8','1'):return False
        value=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p),dklen=32,maxmem=128*1024*1024)
        return hmac.compare_digest(value.hex(),wanted)
    except (ValueError,TypeError):return False

DUMMY=password_hash('dummy-account-timing-placeholder')

def initialize():
    with connection() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_users(
          id UUID PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,
          verified BOOLEAN NOT NULL DEFAULT false,disabled BOOLEAN NOT NULL DEFAULT false,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_workspaces(
          id UUID PRIMARY KEY,name TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_memberships(
          user_id UUID REFERENCES public.os_users(id),workspace_id UUID REFERENCES public.os_workspaces(id),
          role TEXT NOT NULL CHECK(role IN ('workspace_owner','workspace_admin','operator','creator','viewer')),
          PRIMARY KEY(user_id,workspace_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_sessions(
          token_hash TEXT PRIMARY KEY,user_id UUID REFERENCES public.os_users(id),
          workspace_id UUID REFERENCES public.os_workspaces(id),csrf_hash TEXT NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_platform_sessions(
          token_hash TEXT PRIMARY KEY,csrf_hash TEXT NOT NULL,expires_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_tokens(
          token_hash TEXT PRIMARY KEY,user_id UUID REFERENCES public.os_users(id),
          purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')),
          expires_at TIMESTAMPTZ NOT NULL,used_at TIMESTAMPTZ)''')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_email_outbox(
          id UUID PRIMARY KEY,recipient TEXT NOT NULL,payload JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),sent_at TIMESTAMPTZ,
          status TEXT NOT NULL DEFAULT 'pending')''')
        c.execute('ALTER TABLE public.os_email_outbox ADD COLUMN IF NOT EXISTS provider_message_id TEXT')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_auth_audit(
          id BIGSERIAL PRIMARY KEY,user_id UUID,event TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        c.execute('''CREATE TABLE IF NOT EXISTS public.os_rate_limits(
          key TEXT PRIMARY KEY,attempts INTEGER NOT NULL,reset_at TIMESTAMPTZ NOT NULL)''')

def rate_limit(request,action):
    # Never trust X-Forwarded-For without an explicitly configured trusted proxy.
    key=digest(action+':'+(request.client.host if request.client else 'unknown'))
    with connection() as c:
        row=c.execute('''INSERT INTO public.os_rate_limits(key,attempts,reset_at)
          VALUES(%s,1,now()+interval '15 minutes') ON CONFLICT(key) DO UPDATE SET
          attempts=CASE WHEN os_rate_limits.reset_at<now() THEN 1 ELSE os_rate_limits.attempts+1 END,
          reset_at=CASE WHEN os_rate_limits.reset_at<now() THEN now()+interval '15 minutes' ELSE os_rate_limits.reset_at END
          RETURNING attempts''',(key,)).fetchone()
    if row['attempts']>20:raise HTTPException(429,'Muitas tentativas. Aguarde alguns minutos.')

def mail_token(c,user,purpose):
    token=secrets.token_urlsafe(32)
    c.execute("UPDATE public.os_tokens SET used_at=now() WHERE user_id=%s AND purpose=%s AND used_at IS NULL",(user['id'],purpose))
    c.execute('INSERT INTO public.os_tokens(token_hash,user_id,purpose,expires_at) VALUES(%s,%s,%s,%s)',
              (digest(token),user['id'],purpose,datetime.now(timezone.utc)+timedelta(hours=1)))
    origin=os.environ['STUDIO_PUBLIC_ORIGIN'].rstrip('/')
    protected=Fernet(os.environ['STUDIO_MASTER_KEY'].encode()).encrypt((origin+'/login?'+purpose+'='+token).encode()).decode()
    c.execute('INSERT INTO public.os_email_outbox(id,recipient,payload) VALUES(%s,%s,%s::jsonb)',
              (uuid.uuid4(),user['email'],json.dumps({'purpose':purpose,'protected_url':protected})))

class Credentials(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=12,max_length=128)
    @field_validator('email')
    @classmethod
    def email_valid(cls,value):
        value=value.strip().lower()
        if value.count('@')!=1 or any(ch.isspace() for ch in value) or '.' not in value.split('@')[1]:
            raise ValueError('Informe um e-mail válido')
        return value

class Registration(Credentials):
    studio_name:str=Field(min_length=2,max_length=100)

@router.get('/capabilities')
def capabilities():
    return {'signup_available':os.getenv('STUDIO_SIGNUP_ENABLED')=='1' and bool(os.getenv('STUDIO_PUBLIC_ORIGIN')) and bool(os.getenv('STUDIO_MASTER_KEY')),
            'email_delivery_configured':email_configured()}

@router.post('/register')
def register(body:Registration,request:Request):
    if not capabilities()['signup_available'] or not capabilities()['email_delivery_configured']:
        raise HTTPException(503,'Cadastro indisponível até configurar o envio de e-mail.')
    rate_limit(request,'register')
    hashed=password_hash(body.password)
    with connection() as c:
        user=c.execute('SELECT id,email,password_hash,verified FROM public.os_users WHERE email=%s',(body.email,)).fetchone()
        if not user:
            uid,wid=uuid.uuid4(),uuid.uuid4()
            c.execute('INSERT INTO public.os_users(id,email,password_hash) VALUES(%s,%s,%s)',(uid,body.email,hashed))
            c.execute('INSERT INTO public.os_workspaces(id,name) VALUES(%s,%s)',(wid,body.studio_name.strip()))
            c.execute('INSERT INTO public.os_memberships(user_id,workspace_id,role) VALUES(%s,%s,%s)',(uid,wid,'workspace_owner'))
            c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name(wid))))
            # User, membership, schema and catalog initialize in one transaction.
            c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema_name(wid))))
            from .core import init_db
            init_db(c)
            mail_token(c,{'id':uid,'email':body.email},'verify')
        elif not user['verified'] and verify(body.password,user['password_hash']):
            mail_token(c,user,'verify')
    return {'message':'Se o cadastro estiver disponível, você receberá um e-mail com os próximos passos.'}

class TokenBody(BaseModel):
    token:str=Field(min_length=20,max_length=200)

@router.post('/verify')
def verify_email(body:TokenBody,request:Request):
    rate_limit(request,'verify')
    with connection() as c:
        token=c.execute("UPDATE public.os_tokens SET used_at=now() WHERE token_hash=%s AND purpose='verify' AND used_at IS NULL AND expires_at>now() RETURNING user_id",(digest(body.token),)).fetchone()
        if not token:raise HTTPException(400,'Link inválido ou expirado.')
        c.execute('UPDATE public.os_users SET verified=true WHERE id=%s',(token['user_id'],))
    return {'ok':True}

@router.post('/login')
def login(body:Credentials,request:Request,response:Response):
    rate_limit(request,'login')
    with connection() as c:
        user=c.execute('SELECT * FROM public.os_users WHERE email=%s',(body.email,)).fetchone()
        valid=verify(body.password,user['password_hash'] if user else DUMMY)
        if not valid or not user or not user['verified'] or user['disabled']:
            c.execute("INSERT INTO public.os_auth_audit(user_id,event) VALUES(%s,'LOGIN_FAILED')",(user['id'] if user else None,));c.commit()
            raise HTTPException(401,'E-mail ou senha inválidos, ou conta indisponível.')
        membership=c.execute('SELECT * FROM public.os_memberships WHERE user_id=%s ORDER BY workspace_id LIMIT 1',(user['id'],)).fetchone()
        if not membership:raise HTTPException(403,'Nenhum estúdio disponível.')
        token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        c.execute('INSERT INTO public.os_sessions(token_hash,user_id,workspace_id,csrf_hash,expires_at) VALUES(%s,%s,%s,%s,%s)',
          (digest(token),user['id'],membership['workspace_id'],digest(csrf),datetime.now(timezone.utc)+timedelta(hours=12)))
        c.execute("INSERT INTO public.os_auth_audit(user_id,event) VALUES(%s,'LOGIN_SUCCEEDED')",(user['id'],))
    response.set_cookie(COOKIE,token,httponly=True,secure=True,samesite='lax',max_age=43200,path='/')
    response.headers['Cache-Control']='no-store'
    return {'csrf_token':csrf,'workspace_id':membership['workspace_id'],'role':membership['role']}

def session(token):
    if not token or len(token)>200:return None
    with connection() as c:
        platform=c.execute("SELECT *, 'platform_admin' AS role FROM public.os_platform_sessions WHERE token_hash=%s AND expires_at>now()",(digest(token),)).fetchone()
        if platform:return platform
        return c.execute('''SELECT s.*,m.role,u.email FROM public.os_sessions s
          JOIN public.os_memberships m ON m.user_id=s.user_id AND m.workspace_id=s.workspace_id
          JOIN public.os_users u ON u.id=s.user_id
          WHERE s.token_hash=%s AND s.expires_at>now() AND u.verified AND NOT u.disabled''',(digest(token),)).fetchone()

@router.get('/me')
def me(request:Request):
    identity=session(request.cookies.get(COOKIE))
    if not identity:raise HTTPException(401,'Entre na sua conta.')
    return {k:identity.get(k) for k in ('user_id','workspace_id','role','email')}

@router.post('/logout')
def logout(request:Request,response:Response):
    with connection() as c:
        hashed=digest(request.cookies.get(COOKIE,''))
        c.execute('DELETE FROM public.os_sessions WHERE token_hash=%s',(hashed,))
        c.execute('DELETE FROM public.os_platform_sessions WHERE token_hash=%s',(hashed,))
    response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='lax')
    return {'ok':True}

class EmailOnly(BaseModel):
    email:str=Field(min_length=3,max_length=254)

@router.post('/forgot-password')
def forgot(body:EmailOnly,request:Request):
    rate_limit(request,'forgot')
    with connection() as c:
        user=c.execute('SELECT id,email FROM public.os_users WHERE email=%s AND verified AND NOT disabled',(body.email.strip().lower(),)).fetchone()
        if user:mail_token(c,user,'reset')
    return {'message':'Se a conta existir, enviaremos as instruções de recuperação.'}

class Reset(TokenBody):
    password:str=Field(min_length=12,max_length=128)

@router.post('/reset-password')
def reset(body:Reset,request:Request):
    rate_limit(request,'reset')
    hashed=password_hash(body.password)
    with connection() as c:
        token=c.execute("UPDATE public.os_tokens SET used_at=now() WHERE token_hash=%s AND purpose='reset' AND used_at IS NULL AND expires_at>now() RETURNING user_id",(digest(body.token),)).fetchone()
        if not token:raise HTTPException(400,'Link inválido ou expirado.')
        c.execute('UPDATE public.os_users SET password_hash=%s WHERE id=%s',(hashed,token['user_id']))
        c.execute('DELETE FROM public.os_sessions WHERE user_id=%s',(token['user_id'],))
        c.execute("INSERT INTO public.os_auth_audit(user_id,event) VALUES(%s,'PASSWORD_RESET')",(token['user_id'],))
    return {'ok':True}

class AdminCredentials(BaseModel):
    username:str=Field(min_length=1,max_length=128)
    password:str=Field(min_length=1,max_length=256)

@router.post('/admin-login')
def admin_login(body:AdminCredentials,request:Request,response:Response):
    rate_limit(request,'admin-login')
    if not (hmac.compare_digest(body.username,os.getenv('STUDIO_ADMIN_USER','')) and
            hmac.compare_digest(body.password,os.getenv('STUDIO_ADMIN_PASSWORD',''))):
        raise HTTPException(401,'Credenciais administrativas inválidas.')
    token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
    with connection() as c:
        c.execute('INSERT INTO public.os_platform_sessions(token_hash,csrf_hash,expires_at) VALUES(%s,%s,%s)',
                  (digest(token),digest(csrf),datetime.now(timezone.utc)+timedelta(hours=4)))
        c.execute("INSERT INTO public.os_auth_audit(event) VALUES('PLATFORM_LOGIN_SUCCEEDED')")
    response.set_cookie(COOKIE,token,secure=True,httponly=True,samesite='lax',max_age=14400,path='/')
    response.headers['Cache-Control']='no-store'
    return {'role':'platform_admin','csrf_token':csrf}

@router.get('/workspaces')
def workspaces(request:Request):
    identity=session(request.cookies.get(COOKIE))
    if not identity:raise HTTPException(401,'Entre na sua conta.')
    if identity['role']=='platform_admin':return {'workspaces':[],'current_workspace':None}
    with connection() as c:
        rows=c.execute('''SELECT w.id,w.name,m.role FROM public.os_memberships m
          JOIN public.os_workspaces w ON w.id=m.workspace_id WHERE m.user_id=%s ORDER BY w.created_at''',(identity['user_id'],)).fetchall()
    return {'workspaces':rows,'current_workspace':identity['workspace_id']}

class WorkspaceSwitch(BaseModel):
    workspace_id:uuid.UUID

@router.post('/workspace')
def switch_workspace(body:WorkspaceSwitch,request:Request):
    identity=session(request.cookies.get(COOKIE))
    if not identity or identity['role']=='platform_admin':raise HTTPException(403,'Escolha um estúdio da sua conta.')
    with connection() as c:
        if not c.execute('SELECT 1 FROM public.os_memberships WHERE user_id=%s AND workspace_id=%s',(identity['user_id'],body.workspace_id)).fetchone():raise HTTPException(403,'Estúdio indisponível.')
        c.execute('UPDATE public.os_sessions SET workspace_id=%s WHERE token_hash=%s',(body.workspace_id,identity['token_hash']))
    return {'ok':True}

def management_identity(request):
    identity=session(request.cookies.get(COOKIE))
    if not identity or identity['role'] not in ('workspace_owner','workspace_admin'):raise HTTPException(403,'Administradores do estúdio apenas.')
    return identity

@router.get('/members')
def members(request:Request):
    identity=management_identity(request)
    with connection() as c:return c.execute('''SELECT u.id,u.email,m.role FROM public.os_memberships m
      JOIN public.os_users u ON u.id=m.user_id WHERE m.workspace_id=%s ORDER BY u.created_at''',(identity['workspace_id'],)).fetchall()

class MemberEdit(BaseModel):
    user_id:uuid.UUID
    role:str
    @field_validator('role')
    @classmethod
    def valid_role(cls,value):
        if value not in ROLES:raise ValueError('Perfil inválido')
        return value

@router.put('/members')
def edit_member(body:MemberEdit,request:Request):
    identity=management_identity(request)
    if identity['role']!='workspace_owner':raise HTTPException(403,'Somente o proprietário pode alterar permissões.')
    with connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(str(identity['workspace_id']),))
        target=c.execute('SELECT role FROM public.os_memberships WHERE user_id=%s AND workspace_id=%s FOR UPDATE',(body.user_id,identity['workspace_id'])).fetchone()
        if not target:raise HTTPException(404,'Membro inexistente')
        if target['role']=='workspace_owner' and body.role!='workspace_owner':
            owners=c.execute("SELECT count(*) n FROM public.os_memberships WHERE workspace_id=%s AND role='workspace_owner'",(identity['workspace_id'],)).fetchone()['n']
            if owners<=1:raise HTTPException(409,'O estúdio precisa de um proprietário.')
        c.execute('UPDATE public.os_memberships SET role=%s WHERE user_id=%s AND workspace_id=%s',(body.role,body.user_id,identity['workspace_id']))
        c.execute("INSERT INTO public.os_auth_audit(user_id,event) VALUES(%s,'MEMBERSHIP_ROLE_CHANGED')",(identity['user_id'],))
    return {'ok':True}

class AddMember(EmailOnly):
    role:str='viewer'
    @field_validator('role')
    @classmethod
    def valid_role(cls,value):
        if value not in ROLES or value=='workspace_owner':raise ValueError('Perfil inválido')
        return value

@router.post('/members')
def add_member(body:AddMember,request:Request):
    identity=management_identity(request)
    if identity['role']!='workspace_owner':raise HTTPException(403,'Somente o proprietário pode adicionar membros.')
    with connection() as c:
        user=c.execute('SELECT id FROM public.os_users WHERE email=%s AND verified AND NOT disabled',(body.email.strip().lower(),)).fetchone()
        if not user:raise HTTPException(409,'O membro deve ter uma conta confirmada antes de entrar no estúdio.')
        c.execute('INSERT INTO public.os_memberships(user_id,workspace_id,role) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(user['id'],identity['workspace_id'],body.role))
        c.execute("INSERT INTO public.os_auth_audit(user_id,event) VALUES(%s,'MEMBER_ADDED')",(identity['user_id'],))
    return {'ok':True}
