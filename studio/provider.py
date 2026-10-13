"""Explicit musical allowlist, bounded streaming, no fallback or retry."""
import base64, json, time
from decimal import Decimal
import httpx
from . import runtime

MAX_AUDIO=30*1024*1024

def decode_chunk(value):
    if not isinstance(value,str):raise ValueError('Áudio base64 ausente')
    if value.startswith('data:'):
        if ';base64,' not in value:raise ValueError('Envelope de áudio inválido')
        value=value.split(';base64,',1)[1]
    return base64.b64decode(value,validate=True)

class PartialGenerationError(ValueError):
    def __init__(self,buf,generation_id,cost):
        super().__init__('Stream incompleto ou inválido; resposta parcial preservada, sem retry')
        self.buf,self.generation_id,self.cost=buf,generation_id,cost

def collect_stream(lines):
    chunks=[];size=0;generation_id=None;cost=None;done=False;start=time.monotonic()
    try:
        for line in lines:
            if time.monotonic()-start>360:raise TimeoutError('Prazo de geração excedido; não haverá nova tentativa automática')
            if not line or not line.startswith('data:'):continue
            raw=line[5:].strip()
            if raw=='[DONE]':done=True;break
            msg=json.loads(raw)
            if msg.get('error'):raise RuntimeError('OpenRouter retornou falha durante geração')
            generation_id=msg.get('id') or generation_id
            if msg.get('usage',{}).get('cost') is not None:cost=Decimal(str(msg['usage']['cost']))
            for choice in msg.get('choices',[]):
                if choice.get('error') or choice.get('finish_reason')=='error':raise RuntimeError('Geração interrompida pelo provedor')
                payload=choice.get('delta') or choice.get('message') or {}
                audio=payload.get('audio')
                if isinstance(audio,dict) and audio.get('data'):
                    buf=decode_chunk(audio['data']);size+=len(buf)
                    if size>MAX_AUDIO:raise ValueError('Áudio excede 30 MB')
                    chunks.append(buf)
        if not done:raise ValueError('Stream incompleto; áudio não será aprovado')
        if not chunks:raise ValueError('Provedor não retornou áudio reconhecível')
    except Exception:
        raise PartialGenerationError(b''.join(chunks),generation_id,cost) from None
    return b''.join(chunks),generation_id,cost

def generate(prompt,model):
    if model not in runtime.MODELS:raise RuntimeError('Modelo musical não autorizado')
    if not runtime.settings()['enabled']:raise RuntimeError('Geração desativada pelo administrador')
    token=runtime.key()
    if not token:raise RuntimeError('Chave OpenRouter não configurada')
    # Music models do not require a speech voice. Exact model, no model fallback.
    payload={'model':model,'messages':[{'role':'user','content':prompt}],
             'modalities':['text','audio'],'audio':{'format':'mp3'},'stream':True,
             'provider':{'allow_fallbacks':False}}
    with httpx.Client(timeout=httpx.Timeout(180,connect=15)) as client:
        with client.stream('POST','https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization':f'Bearer {token}','Content-Type':'application/json','X-Title':'Lo-Fi Vibe Coding Studio'},json=payload) as response:
            if response.status_code!=200:raise RuntimeError(f'OpenRouter HTTP {response.status_code}; sem nova tentativa automática')
            return collect_stream(response.iter_lines())
