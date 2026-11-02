"""Audit an existing YouTube channel and apply only human-approved metadata edits.

Everything comes from official Google APIs (YouTube Data API v3 and, when the
owner authorized it, YouTube Analytics API v2) or from the Studio captures the
Growth screen already stores. No vidIQ, no scraping, no generated videos.

Findings keep the observed fact (evidence) apart from the likely impact, which
is always a hypothesis. A change is a proposal until an administrator approves
that exact value; applying needs an explicit confirmation that names every
change, and success is recorded only after a fresh read returns the value.
"""
import hashlib,json,re,statistics,uuid
from datetime import datetime,timedelta,timezone
from typing import Literal
from urllib.parse import unquote,urlparse
from zoneinfo import ZoneInfo
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .core import db,audit,ensure_once
from .channels import profile
from .permissions import SPEND_ROLES
from .youtube import ANALYTICS_SCOPE,cipher,configured
from .youtube_publish import MANAGE_SCOPES,access_token

router=APIRouter(prefix='/api/growth')
DATA_API='https://www.googleapis.com/youtube/v3'
ANALYTICS_API='https://youtubeanalytics.googleapis.com/v2/reports'
READ_SCOPES=('https://www.googleapis.com/auth/youtube.readonly',)+MANAGE_SCOPES
OFFICIAL_NAME='LoFi Vibe Coding'
FORBIDDEN_VARIANTS=('Lo-Fi Vibe Coding','Tração')
MAX_VIDEOS=200
MAX_PLAYLISTS=25
SOURCE_DATA='youtube_data_api_v3'
SOURCE_ANALYTICS='youtube_analytics_api_v2'
SOURCE_MANUAL='manual_youtube_studio'
CAUTION=('Evidências são leituras das APIs oficiais ou capturas do YouTube Studio. Impactos são hipóteses: '
         'nenhuma recomendação garante posição na busca, impressões ou visualizações.')
OPEN_STATES=('proposed','approved','rejected')

# (kind, field) -> (editable through the API, local limit, unit). Limits are the documented ones;
# the playlist resource documents none, so only a sanity guard applies there.
FIELDS={('video','title'):(True,100,'chars'),('video','description'):(True,5000,'bytes'),
        ('playlist','title'):(True,5000,'bytes'),('playlist','description'):(True,5000,'bytes'),
        ('channel','description'):(True,1000,'chars'),('channel','keywords'):(True,500,'chars'),
        ('channel','title'):(False,30,'chars'),('channel','handle'):(False,30,'chars')}
VIDEO_SNIPPET_KEEP=('title','description','categoryId','tags','defaultLanguage','defaultAudioLanguage')
PLAYLIST_SNIPPET_KEEP=('title','description','defaultLanguage')
STUDIO_STEPS={
    ('channel','title'):'A API do YouTube não altera o nome do canal (channels.update exige manter o título atual). No YouTube Studio: Personalização → Informações básicas → Nome; edite, clique em Publicar e depois use “Reler no YouTube” aqui.',
    ('channel','handle'):'A API do YouTube não altera o identificador (@handle). No YouTube Studio: Personalização → Informações básicas → Identificador; publique e depois use “Reler no YouTube” aqui.',
    ('channel','links'):'A API de Dados não expõe nem altera os links da seção Sobre. Confira em YouTube Studio: Personalização → Informações básicas → Links.',
    ('video','thumbnail'):'Este fluxo não cria nem envia miniaturas. Para trocar: YouTube Studio → Conteúdo → vídeo → Detalhes → Miniatura.',
}

def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS channel_audit_runs(
      id UUID PRIMARY KEY,channel_id UUID NOT NULL REFERENCES radio_channels(id),youtube_channel_id TEXT NOT NULL,
      channel_ref TEXT NOT NULL,brand JSONB NOT NULL,intended_searches JSONB NOT NULL DEFAULT '[]'::jsonb,
      snapshot JSONB NOT NULL,snapshot_sha256 TEXT NOT NULL,analytics JSONB NOT NULL,findings JSONB NOT NULL,
      diagnosis JSONB NOT NULL,provenance JSONB NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('CREATE INDEX IF NOT EXISTS channel_audit_runs_history ON channel_audit_runs(channel_id,created_at DESC)')
    c.execute('''CREATE TABLE IF NOT EXISTS channel_audit_changes(
      id UUID PRIMARY KEY,run_id UUID NOT NULL REFERENCES channel_audit_runs(id),channel_id UUID NOT NULL REFERENCES radio_channels(id),
      youtube_channel_id TEXT NOT NULL,target_kind TEXT NOT NULL CHECK(target_kind IN ('channel','video','playlist')),
      target_id TEXT NOT NULL,target_label TEXT NOT NULL DEFAULT '',field TEXT NOT NULL,current_value TEXT NOT NULL,
      suggested_value TEXT NOT NULL,rationale TEXT NOT NULL DEFAULT '',finding_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
      origin TEXT NOT NULL,api_supported BOOLEAN NOT NULL,manual_instructions TEXT NOT NULL DEFAULT '',
      state TEXT NOT NULL DEFAULT 'proposed' CHECK(state IN ('proposed','approved','rejected','applying','verified','unverified','failed','conflict','superseded')),
      approved_by TEXT,approved_at TIMESTAMPTZ,approved_sha256 TEXT,applied_at TIMESTAMPTZ,observed_value TEXT,
      verified_at TIMESTAMPTZ,detail TEXT NOT NULL DEFAULT '',created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('CREATE INDEX IF NOT EXISTS channel_audit_changes_run ON channel_audit_changes(run_id,state)')
    c.execute('ALTER TABLE channel_audit_changes ADD COLUMN IF NOT EXISTS approved_editorial_sha256 TEXT')
    c.execute('''CREATE TABLE IF NOT EXISTS channel_audit_events(
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,change_id UUID NOT NULL REFERENCES channel_audit_changes(id),
      action TEXT NOT NULL,actor TEXT NOT NULL,detail JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('CREATE INDEX IF NOT EXISTS channel_audit_events_change ON channel_audit_events(change_id,id)')

def ready():ensure_once('channel_audit',ensure)

def actor(request):
    identity=getattr(request.state,'identity',None) or {}
    return str(identity.get('email') or identity.get('user_id') or identity.get('role') or 'unknown')[:200]

def require_admin(request:Request)->None:
    """Approving or publishing to YouTube is an owner/admin decision."""
    if ((getattr(request.state,'identity',None) or {}).get('role')) not in SPEND_ROLES:
        raise HTTPException(403,'Somente administradores do workspace aprovam ou publicam alterações no YouTube.')

def digest(value):return hashlib.sha256(str(value).encode()).hexdigest()

# ---------------------------------------------------------------- channel reference

CHANNEL_ID=re.compile(r'UC[0-9A-Za-z_-]{22}')
HANDLE=re.compile(r'@[\w.\-]{3,30}')

def parse_channel_ref(value):
    """Return the channels.list filter for a URL, handle or channel ID; never guesses."""
    value=str(value or '').strip()
    if CHANNEL_ID.fullmatch(value):return {'id':value}
    if HANDLE.fullmatch(value):return {'forHandle':value}
    u=urlparse(value if '://' in value else 'https://'+value)
    if u.scheme!='https' or u.hostname not in ('youtube.com','www.youtube.com','m.youtube.com') or u.username or u.password or u.port:
        raise ValueError('Use o endereço HTTPS do canal no YouTube, o @identificador ou o ID que começa com UC.')
    parts=[unquote(p) for p in u.path.split('/') if p]
    if len(parts)>=2 and parts[0]=='channel' and CHANNEL_ID.fullmatch(parts[1]):return {'id':parts[1]}
    if parts and HANDLE.fullmatch(parts[0]):return {'forHandle':parts[0]}
    if len(parts)>=2 and parts[0]=='user':return {'forUsername':parts[1]}
    raise ValueError('Endereços /c/ e de vídeo não identificam o canal pela API. Use youtube.com/@identificador, youtube.com/channel/UC… ou o ID do canal.')

# ---------------------------------------------------------------- brand rules

BRAND_SEPARATORS=r'[\s._\-–—]*'

def brand_pattern(official):
    letters=[ch for ch in official if ch.isalnum()]
    return re.compile(BRAND_SEPARATORS.join(re.escape(ch) for ch in letters),re.I)

def brand_rules(official=OFFICIAL_NAME,forbidden=FORBIDDEN_VARIANTS):
    official=' '.join(str(official or '').split())
    if len(official)<2:raise ValueError('Informe a grafia oficial da marca.')
    terms=[' '.join(str(t).split()) for t in forbidden if str(t).strip()]
    return {'official_name':official,'forbidden_variants':list(dict.fromkeys(t for t in terms if t!=official))}

def _inside_handle_or_url(text,start):
    before=text[:start]
    return before.endswith(('@','/')) or bool(re.search(r'https?://\S*$',before))

def brand_issues(text,brand):
    """Wrong spellings of the official name plus explicitly forbidden terms; handles and URLs are left alone."""
    text=str(text or '');found=[]
    for m in brand_pattern(brand['official_name']).finditer(text):
        if m.group(0)!=brand['official_name'] and not _inside_handle_or_url(text,m.start()):found.append(m.group(0))
    for term in brand['forbidden_variants']:
        for m in re.finditer(r'(?<!\w)'+re.escape(term)+r'(?!\w)',text,re.I):
            if not _inside_handle_or_url(text,m.start()):found.append(m.group(0))
    return list(dict.fromkeys(found))

def brand_fix(text,brand):
    """Replace only spellings of the official name; other forbidden terms need a human rewrite."""
    text=str(text or '')
    def swap(m):return m.group(0) if _inside_handle_or_url(text,m.start()) else brand['official_name']
    return brand_pattern(brand['official_name']).sub(swap,text)

# ---------------------------------------------------------------- text heuristics

STOPWORDS={'a','an','and','at','by','for','from','in','into','of','on','or','the','to','with','your','you','this','that','is','are','it',
           'e','o','os','as','de','da','do','das','dos','em','no','na','para','por','com','um','uma','hour','hours','hora','horas','1'}
GENRE_TERMS={'lofi','jazzhop','jazz','hiphop','chillhop','beats','ambient','music','música','musica','instrumental','piano','synthwave'}
USE_TERMS={'coding','code','programming','programmer','developer','study','studying','focus','work','reading','read','sleep','relax',
           'relaxing','concentration','estudar','estudo','programar','programação','foco','trabalho','leitura','dormir','relaxar'}
TITLE_SEPARATORS=('|','—','–',':')
URL=re.compile(r'https?://[^\s<>()]+',re.I)

def tokens(text):
    text=str(text or '').casefold()
    text=re.sub(r'lo[\s\-]?fi','lofi',text);text=re.sub(r'hip[\s\-]?hop','hiphop',text);text=re.sub(r'jazz[\s\-]hop','jazzhop',text)
    return [w for w in re.findall(r'\w+',text) if w not in STOPWORDS]

def phrase_covered(phrase,text):
    words=set(tokens(phrase))
    return bool(words) and words<=set(tokens(text))

def norm(value):return ' '.join(str(value or '').split())

# ---------------------------------------------------------------- findings

def finding(kind,severity,scope,target_id,target_label,basis,evidence,impact,recommendation,source=SOURCE_DATA,**extra):
    return {'id':digest(f'{kind}:{scope}:{target_id}')[:16],'kind':kind,'severity':severity,'scope':scope,'target_id':target_id,
            'target_label':target_label,'basis':basis,'evidence':evidence,'impact':impact,'recommendation':recommendation,'source':source,**extra}

def _brand_findings(scope,target_id,label,fields,brand):
    out=[]
    for field,value in fields:
        issues=brand_issues(value,brand)
        if issues:
            out.append(finding('brand_inconsistency','high',scope,target_id,label,'observed',
                f'O campo {field} contém {", ".join("“"+i+"”" for i in issues)}; a grafia oficial é “{brand["official_name"]}”.',
                'Hipótese: grafias diferentes dificultam reconhecer a marca e associar os vídeos ao mesmo canal.',
                f'Use exatamente “{brand["official_name"]}”. Termos que não são grafias do nome precisam de reescrita humana.',field=field))
    return out

def analyze_channel(channel,brand):
    out=[];cid=channel['id'];label=channel.get('title','')
    if channel.get('title')!=brand['official_name']:
        out.append(finding('channel_name_mismatch','high','channel',cid,label,'observed',
            f'Nome atual: “{channel.get("title","")}”. Grafia oficial: “{brand["official_name"]}”.',
            'Hipótese: o nome diferente da grafia oficial enfraquece o reconhecimento da marca.',
            'Ajuste o nome no YouTube Studio (a API não permite).',field='title',manual_instructions=STUDIO_STEPS[('channel','title')]))
    handle=channel.get('handle','')
    official_letters=''.join(ch for ch in brand['official_name'].casefold() if ch.isalnum())
    if not handle:
        out.append(finding('handle_missing','medium','channel',cid,label,'observed','A API não retornou identificador (@handle) para o canal.',
            'Hipótese: sem identificador, o endereço do canal fica menos memorável.','Defina um identificador no YouTube Studio.',
            field='handle',manual_instructions=STUDIO_STEPS[('channel','handle')]))
    elif official_letters not in ''.join(ch for ch in handle.casefold() if ch.isalnum()):
        out.append(finding('handle_brand_mismatch','low','channel',cid,label,'hypothesis',f'Identificador atual: {handle}.',
            'Hipótese: um identificador que não lembra o nome oficial pode confundir quem procura o canal pelo nome.',
            'Avalie se vale trocar; verifique a disponibilidade no YouTube Studio antes de decidir.',field='handle',manual_instructions=STUDIO_STEPS[('channel','handle')]))
    description=channel.get('description','')
    out+=_brand_findings('channel',cid,label,[('title',channel.get('title','')),('description',description),('keywords',channel.get('keywords',''))],brand)
    if not description.strip():
        out.append(finding('about_missing','high','channel',cid,label,'observed','A descrição “Sobre” está vazia.',
            'Hipótese: visitantes e o próprio YouTube têm menos contexto sobre o tema do canal.',
            'Escreva uma descrição curta com a proposta do canal e o nome oficial.',field='description'))
    elif brand['official_name'] not in description:
        out.append(finding('about_without_brand','medium','channel',cid,label,'observed',f'A descrição “Sobre” ({len(description)} caracteres) não menciona “{brand["official_name"]}”.',
            'Hipótese: a página do canal perde uma oportunidade de fixar a grafia da marca.','Mencione o nome oficial uma vez, de forma natural.',field='description'))
    insecure=[u for u in URL.findall(description) if u.lower().startswith('http://')]
    if insecure:
        out.append(finding('insecure_link','medium','channel',cid,label,'observed',f'Links sem HTTPS na descrição “Sobre”: {", ".join(insecure[:5])}.',
            'Hipótese: navegadores podem alertar visitantes que clicam.','Troque por endereços HTTPS equivalentes.',field='description'))
    out.append(finding('about_links_not_in_api','info','channel',cid,label,'limitation','A API de Dados do YouTube não expõe os links da seção Sobre.',
        'Não é possível avaliar esses links por aqui.','Revise os links manualmente no YouTube Studio.',field='links',manual_instructions=STUDIO_STEPS[('channel','links')]))
    return out

def analyze_videos(videos,brand,lofi_vocabulary=True):
    """lofi_vocabulary: the genre/use word lists below are English LoFi terms; other niches skip that heuristic."""
    out=[];by_title={}
    for v in videos:
        vid,title,description=v['id'],v.get('title',''),v.get('description','');label=title or vid
        out+=_brand_findings('video',vid,label,[('title',title),('description',description)],brand)
        words=tokens(title);bag=set(words)
        repeated=sorted({w for w in words if words.count(w)>1 and w not in {'music','música'}})
        if repeated:
            out.append(finding('title_repetition','medium','video',vid,label,'observed',f'Palavras repetidas no título: {", ".join(repeated)}.',
                'Hipótese: repetição soa como lista de palavras-chave e não acrescenta informação ao espectador.',
                'Diga cada ideia uma vez; mantenha o tema e a cena específicos.',field='title'))
        separators=sum(title.count(s) for s in TITLE_SEPARATORS)
        if separators>1:
            out.append(finding('title_stacked_segments','low','video',vid,label,'observed',f'O título usa {separators} separadores.',
                'Hipótese: vários segmentos empilhados dificultam ler o tema de relance.','Prefira uma ideia principal e no máximo um separador.',field='title'))
        if lofi_vocabulary and (not bag&GENRE_TERMS or not bag&USE_TERMS):
            missing=[n for n,s in (('gênero musical',GENRE_TERMS),('uso/intenção (ex.: programar, estudar)',USE_TERMS)) if not bag&s]
            out.append(finding('title_topic_unclear','medium','video',vid,label,'hypothesis',f'O título não contém termo de {" nem de ".join(missing)}.',
                'Hipótese: quem lê o título pode não entender que tipo de vídeo é nem para que serve.',
                'Deixe explícito o gênero e o uso, sem repetir palavras-chave; mantenha a cena específica do vídeo.',field='title'))
        by_title.setdefault(norm(title).casefold(),[]).append(v)
        if not description.strip():
            out.append(finding('description_missing','high','video',vid,label,'observed','A descrição está vazia.',
                'Hipótese: falta contexto sobre o conteúdo para espectadores e para a busca.','Escreva 2–3 parágrafos sobre a cena, a música e o uso.',field='description'))
        else:
            if len(description)<200:
                out.append(finding('description_short','medium','video',vid,label,'observed',f'A descrição tem {len(description)} caracteres.',
                    'Hipótese: uma descrição curta explica pouco o que o vídeo oferece.','Descreva a cena, o caráter musical e o uso, apenas com fatos do vídeo.',field='description'))
            opening=description[:200];shared=set(tokens(opening))&(bag-GENRE_TERMS)
            if bag-GENRE_TERMS and not shared:
                out.append(finding('description_opening_off_topic','low','video',vid,label,'hypothesis','A abertura da descrição (200 primeiros caracteres) não retoma nenhum termo específico do título.',
                    'Hipótese: a primeira linha, visível antes de “mais”, pode não confirmar a promessa do título.','Retome o tema do título na primeira frase, de forma natural.',field='description'))
            desc_words=tokens(description);counts={w:desc_words.count(w) for w in set(desc_words)}
            heavy=sorted(w for w,n in counts.items() if n>=6 and n/len(desc_words)>.05)
            if heavy:
                out.append(finding('description_keyword_repetition','medium','video',vid,label,'observed',f'Termos repetidos muitas vezes na descrição: {", ".join(f"{w} ({counts[w]}×)" for w in heavy)}.',
                    'Hipótese: repetição artificial prejudica a leitura e pode ser tratada como excesso de palavras-chave.','Mantenha cada termo só onde ele informa algo.',field='description'))
            insecure=[u for u in URL.findall(description) if u.lower().startswith('http://')]
            if insecure:
                out.append(finding('insecure_link','low','video',vid,label,'observed',f'Links sem HTTPS: {", ".join(insecure[:5])}.',
                    'Hipótese: navegadores podem alertar quem clica.','Troque por endereços HTTPS equivalentes.',field='description'))
    for group in by_title.values():
        if len(group)>1 and group[0].get('title'):
            ids=[v['id'] for v in group]
            out.append(finding('duplicate_title','medium','video',ids[0],group[0]['title'],'observed',f'{len(group)} vídeos têm o mesmo título: {", ".join(ids)}.',
                'Hipótese: títulos idênticos dificultam distinguir os vídeos nas listas e nos resultados.','Diferencie pela cena ou pelo conceito real de cada vídeo.',field='title',related_ids=ids))
    if videos:
        out.append(finding('thumbnail_manual_review','info','channel','thumbnails','Miniaturas','limitation',
            f'{len(videos)} miniaturas importadas por URL. A API não informa se são personalizadas nem avalia legibilidade ou contraste.',
            'Sem revisão visual, não há como afirmar problema nas miniaturas.','Revise as miniaturas lado a lado na lista de vídeos desta auditoria.',
            field='thumbnail',manual_instructions=STUDIO_STEPS[('video','thumbnail')]))
    return out

def analyze_playlists(playlists,videos,brand):
    out=[]
    if not playlists:
        out.append(finding('no_playlists','medium','channel','playlists','Playlists','observed','O canal não tem playlists retornadas pela API.',
            'Hipótese: sem playlists, quem termina um vídeo tem menos caminhos para continuar no canal.','Agrupe os vídeos por uso ou cena em playlists com títulos claros.'))
        return out
    for p in playlists:
        label=p.get('title') or p['id']
        out+=_brand_findings('playlist',p['id'],label,[('title',p.get('title','')),('description',p.get('description',''))],brand)
        if not p.get('description','').strip():
            out.append(finding('playlist_description_missing','low','playlist',p['id'],label,'observed','A playlist não tem descrição.',
                'Hipótese: a página da playlist explica menos o que o espectador vai encontrar.','Descreva o tema da playlist em uma ou duas frases.',field='description'))
    listed={vid for p in playlists for vid in p.get('video_ids',[])}
    public=[v for v in videos if v.get('privacy')=='public']
    orphans=[v for v in public if v['id'] not in listed]
    if orphans:
        partial=any(p.get('items_truncated') for p in playlists)
        out.append(finding('videos_outside_playlists','medium','channel','playlists','Playlists','observed',
            f'{"Pelo menos " if not partial else "Até "}{len(orphans)} de {len(public)} vídeos públicos não aparecem nas playlists lidas'+(' (algumas playlists têm mais itens que o lido)' if partial else '')+': '+', '.join((v.get('title') or v['id']) for v in orphans[:8])+('…' if len(orphans)>8 else '')+'.',
            'Hipótese: vídeos fora de playlists têm menos chances de serem assistidos em sequência.','Inclua cada vídeo na playlist do seu uso principal.',related_ids=[v['id'] for v in orphans]))
    return out

def analyze_search(videos,phrases,origin,source):
    """Coverage only: whether titles contain the phrase words. Never a search-volume or ranking claim."""
    out=[]
    for phrase in phrases:
        covered=[v for v in videos if phrase_covered(phrase,v.get('title',''))]
        described=[v for v in videos if phrase_covered(phrase,v.get('description',''))]
        if not covered:
            out.append(finding('search_phrase_not_in_titles','medium' if origin=='observed' else 'low','channel',f'search:{phrase.casefold()}',phrase,'observed',
                f'Nenhum dos {len(videos)} títulos contém todas as palavras de “{phrase}” ({"termo observado no YouTube" if origin=="observed" else "busca pretendida informada"}); {len(described)} descrições contêm.',
                'Hipótese: se o vídeo realmente atende essa busca, o título pode não deixar isso claro.',
                'Use o termo só nos vídeos cujo conteúdo corresponde a ele, uma vez e de forma natural. Isso não garante posição na busca.',source=source,phrase_origin=origin))
    return out

def analyze_analytics(analytics,videos):
    """Signals, not causes. Without authorized Analytics data the diagnosis stays explicitly open."""
    out=[];sections=(analytics or {}).get('sections') or {}
    status=(analytics or {}).get('status')
    if status!='ok':
        return out,{'status':'insufficient_data','message':'Sem dados do YouTube Analytics autorizados para este canal, a auditoria não aponta a causa da baixa visibilidade. '
                    'Autorize o acesso de leitura ao Analytics ou registre capturas do YouTube Studio.','reason':status or 'not_requested'}
    period=analytics.get('period') or {};when=f"{period.get('start')} a {period.get('end')}"
    sources=(sections.get('traffic_sources') or {}).get('rows') or []
    total=sum(float(r.get('views') or 0) for r in sources)
    if total>0:
        search=sum(float(r.get('views') or 0) for r in sources if r.get('insightTrafficSourceType')=='YT_SEARCH')
        top=sorted(sources,key=lambda r:-float(r.get('views') or 0))[:4]
        out.append(finding('traffic_mix','info','channel','analytics:traffic','Origem do tráfego','observed',
            f'{when}: Pesquisa do YouTube = {search/total*100:.1f}% de {total:,.0f} visualizações. Principais origens: '+', '.join(f"{r.get('insightTrafficSourceType')} {float(r.get('views') or 0)/total*100:.1f}%" for r in top)+'.',
            'A composição mostra de onde vieram as visualizações, não por que vieram.',
            'Compare a mesma janela em capturas futuras antes de atribuir qualquer mudança a títulos ou descrições.',source=SOURCE_ANALYTICS))
    rows=[r for r in ((sections.get('videos') or {}).get('rows') or []) if r.get('averageViewPercentage') is not None]
    if len(rows)>=4:
        median=statistics.median(float(r['averageViewPercentage']) for r in rows)
        titles={v['id']:v.get('title','') for v in videos}
        low=sorted((r for r in rows if float(r['averageViewPercentage'])<median),key=lambda r:float(r['averageViewPercentage']))[:5]
        out.append(finding('retention_below_channel_median','info','channel','analytics:retention','Retenção','observed',
            f'{when}: mediana interna de porcentagem média assistida = {median:.1f}% ({len(rows)} vídeos). Abaixo dela: '+'; '.join(f"{titles.get(r.get('video'),r.get('video'))} {float(r['averageViewPercentage']):.1f}%" for r in low)+'.',
            'Hipótese: retenção abaixo da média interna pode indicar promessa de título/miniatura desalinhada com o conteúdo, mas idade, duração e origem do tráfego também explicam diferenças.',
            'Antes de editar, confira se título e primeira linha descrevem fielmente a cena e a música desses vídeos.',source=SOURCE_ANALYTICS))
    return out,{'status':'signals_only','message':'Há dados do Analytics, mas eles mostram sinais observacionais. Nenhuma causa é afirmada.','period':period}

def manual_findings(manual):
    latest=(manual or {}).get('latest_channel_capture')
    if not latest:
        return [finding('impressions_ctr_unavailable','info','channel','analytics:impressions','Impressões e CTR','limitation',
            'A YouTube Analytics API oficial não documenta métricas de impressões nem de CTR de miniatura, e não há captura manual do YouTube Studio registrada.',
            'Sem esses dados, não é possível avaliar se o problema está na exposição ou no clique.',
            'Registre impressões e CTR da mesma janela em Análises → Sinais do canal.',source=SOURCE_MANUAL)]
    m=latest.get('metrics') or {}
    return [finding('impressions_ctr_manual','info','channel','analytics:impressions','Impressões e CTR','observed',
        f"Captura manual do YouTube Studio em {latest.get('observed_date')} ({latest.get('window')}): impressões {m.get('impressions','não informado')}, CTR {m.get('ctr_percent','não informado')}%.",
        'Valores digitados a partir do Studio; servem de contexto, não de causa.','Compare com uma nova captura da mesma janela depois das alterações.',source=SOURCE_MANUAL)]

def run_findings(snapshot,brand,analytics,manual,intended,lofi_vocabulary=True):
    videos=snapshot.get('videos') or []
    found=analyze_channel(snapshot['channel'],brand)+analyze_videos(videos,brand,lofi_vocabulary)+analyze_playlists(snapshot.get('playlists') or [],videos,brand)
    observed=[r.get('insightTrafficSourceDetail') for r in (((analytics or {}).get('sections') or {}).get('search_terms') or {}).get('rows') or [] if r.get('insightTrafficSourceDetail')]
    observed+=[p['phrase'] for p in (manual or {}).get('search_phrases',[])]
    observed=list(dict.fromkeys(p for p in observed if tokens(p)))[:25]
    found+=analyze_search(videos,observed,'observed',SOURCE_ANALYTICS if (analytics or {}).get('status')=='ok' else SOURCE_MANUAL)
    found+=analyze_search(videos,[p for p in intended if p not in observed],'intended','user_input')
    extra,diagnosis=analyze_analytics(analytics,videos)
    found+=extra+manual_findings(manual)
    order={'high':0,'medium':1,'low':2,'info':3}
    found.sort(key=lambda f:(order.get(f['severity'],4),f['scope'],f['kind']))
    return found,diagnosis

def brand_proposals(snapshot,brand,findings):
    """Deterministic, reviewable fixes: only spellings of the official name are rewritten automatically."""
    by_target={}
    for f in findings:
        if f['kind'] in ('brand_inconsistency','channel_name_mismatch'):by_target.setdefault((f['scope'],f['target_id'],f.get('field')),[]).append(f['id'])
    out=[];ch=snapshot['channel']
    targets=[('channel',ch['id'],ch.get('title',''),field,ch.get(field,'')) for field in ('description','keywords')]
    targets+=[('video',v['id'],v.get('title') or v['id'],field,v.get(field,'')) for v in snapshot.get('videos') or [] for field in ('title','description')]
    targets+=[('playlist',p['id'],p.get('title') or p['id'],field,p.get(field,'')) for p in snapshot.get('playlists') or [] for field in ('title','description')]
    for kind,tid,label,field,current in targets:
        fixed=brand_fix(current,brand)
        if fixed!=current and valid_value(kind,field,fixed)[0]:
            left=brand_issues(fixed,brand)
            out.append({'target_kind':kind,'target_id':tid,'target_label':label,'field':field,'current_value':current,'suggested_value':fixed,
                        'rationale':f'Padroniza a grafia oficial “{brand["official_name"]}”.'+(f' Ainda contém {", ".join(left)}: reescreva antes de aprovar.' if left else ''),
                        'finding_ids':by_target.get((kind,tid,field),[]),'origin':'brand_rule'})
    if ch.get('title')!=brand['official_name']:
        out.append({'target_kind':'channel','target_id':ch['id'],'target_label':ch.get('title',''),'field':'title','current_value':ch.get('title',''),
                    'suggested_value':brand['official_name'],'rationale':'Nome do canal com a grafia oficial. Alteração manual no YouTube Studio.',
                    'finding_ids':by_target.get(('channel',ch['id'],'title'),[]),'origin':'brand_rule'})
    return out

def valid_value(kind,field,value):
    spec=FIELDS.get((kind,field))
    if not spec:return False,'Campo não suportado.'
    _,limit,unit=spec;size=len(value.encode()) if unit=='bytes' else len(value)
    if field=='title' and not value.strip():return False,'O título não pode ficar vazio.'
    if size>limit:return False,f'Excede o limite de {limit} {"bytes" if unit=="bytes" else "caracteres"} documentado.'
    if kind=='video' and ('<' in value or '>' in value):return False,'Títulos e descrições de vídeo não aceitam < nem >.'
    return True,''

# ---------------------------------------------------------------- YouTube reads and writes

class YouTubeError(Exception):
    def __init__(self,status,reason=''):super().__init__(f'YouTube {status} {reason}'.strip());self.status=status;self.reason=reason

def _reason(response):
    try:return str((((response.json().get('error') or {}).get('errors') or [{}])[0]).get('reason') or '')[:80]
    except (ValueError,AttributeError,IndexError):return ''

def _get(client,url,token,params):
    r=client.get(url,params=params,headers={'Authorization':'Bearer '+token})
    if r.status_code!=200:raise YouTubeError(r.status_code,_reason(r))
    return r.json()

def _put(client,url,token,params,body):
    r=client.put(url,params=params,headers={'Authorization':'Bearer '+token},json=body)
    if r.status_code!=200:raise YouTubeError(r.status_code,_reason(r))
    return r.json()

def _thumbnail(snippet):
    sizes=snippet.get('thumbnails') or {}
    for key in ('maxres','standard','high','medium','default'):
        if (sizes.get(key) or {}).get('url'):return sizes[key]['url']
    return ''

def _count(value):
    try:return int(value)
    except (TypeError,ValueError):return None

def channel_summary(item):
    s=item.get('snippet') or {};b=(item.get('brandingSettings') or {}).get('channel') or {};st=item.get('statistics') or {}
    return {'id':item['id'],'title':s.get('title',''),'handle':s.get('customUrl',''),'description':b.get('description',s.get('description','')),
            'keywords':b.get('keywords',''),'country':b.get('country') or s.get('country') or '','published_at':s.get('publishedAt'),
            'thumbnail':_thumbnail(s),'uploads_playlist':((item.get('contentDetails') or {}).get('relatedPlaylists') or {}).get('uploads',''),
            'public_counts':{'videos':_count(st.get('videoCount')),'views':_count(st.get('viewCount')),
                             'subscribers':None if st.get('hiddenSubscriberCount') else _count(st.get('subscriberCount'))}}

def resolve(client,token,ref):
    data=_get(client,f'{DATA_API}/channels',token,{'part':'snippet,brandingSettings,contentDetails,statistics',**ref})
    items=data.get('items') or []
    if len(items)!=1:raise HTTPException(404,'O YouTube não encontrou um canal único para esse endereço ou ID.')
    return items[0]

def import_snapshot(client,token,channel_item):
    """Existing channel, uploads and playlists only. Nothing is created on YouTube."""
    channel=channel_summary(channel_item);video_ids=[];page=None;truncated=False
    while channel['uploads_playlist']:
        data=_get(client,f'{DATA_API}/playlistItems',token,{'part':'contentDetails','playlistId':channel['uploads_playlist'],'maxResults':50,**({'pageToken':page} if page else {})})
        video_ids+=[i['contentDetails']['videoId'] for i in data.get('items') or [] if (i.get('contentDetails') or {}).get('videoId')]
        page=data.get('nextPageToken')
        if not page:break
        if len(video_ids)>=MAX_VIDEOS:truncated=True;break
    video_ids=list(dict.fromkeys(video_ids))[:MAX_VIDEOS];videos=[]
    for start in range(0,len(video_ids),50):
        data=_get(client,f'{DATA_API}/videos',token,{'part':'snippet,contentDetails,status,statistics','id':','.join(video_ids[start:start+50]),'maxResults':50})
        for i in data.get('items') or []:
            s=i.get('snippet') or {}
            videos.append({'id':i['id'],'title':s.get('title',''),'description':s.get('description',''),'published_at':s.get('publishedAt'),
                           'privacy':(i.get('status') or {}).get('privacyStatus',''),'duration':(i.get('contentDetails') or {}).get('duration',''),
                           'thumbnail':_thumbnail(s),'tags_count':len(s.get('tags') or []),'public_views':_count((i.get('statistics') or {}).get('viewCount'))})
    playlists=[];page=None
    while True:
        data=_get(client,f'{DATA_API}/playlists',token,{'part':'snippet,contentDetails','channelId':channel['id'],'maxResults':50,**({'pageToken':page} if page else {})})
        for i in data.get('items') or []:
            s=i.get('snippet') or {}
            playlists.append({'id':i['id'],'title':s.get('title',''),'description':s.get('description',''),'item_count':(i.get('contentDetails') or {}).get('itemCount')})
        page=data.get('nextPageToken')
        if not page or len(playlists)>=MAX_PLAYLISTS:break
    playlists=playlists[:MAX_PLAYLISTS]
    for p in playlists:
        data=_get(client,f'{DATA_API}/playlistItems',token,{'part':'contentDetails','playlistId':p['id'],'maxResults':50})
        p['video_ids']=[i['contentDetails']['videoId'] for i in data.get('items') or [] if (i.get('contentDetails') or {}).get('videoId')]
        p['items_truncated']=bool(data.get('nextPageToken'))
    return {'channel':channel,'videos':videos,'playlists':playlists,
            'limits':{'max_videos':MAX_VIDEOS,'videos_truncated':truncated,'max_playlists':MAX_PLAYLISTS,'playlist_items_read':50}}

def _rows(data):
    names=[h.get('name') for h in data.get('columnHeaders') or []]
    return [dict(zip(names,row)) for row in data.get('rows') or []]

def fetch_analytics(client,token,today=None):
    """Last complete 28 days through the documented reports; each section fails on its own."""
    end=(today or datetime.now(ZoneInfo('America/Sao_Paulo')).date())-timedelta(days=2);start=end-timedelta(days=27)
    base={'ids':'channel==MINE','startDate':start.isoformat(),'endDate':end.isoformat()}
    queries={'videos':{'metrics':'views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage','dimensions':'video','sort':'-views','maxResults':50},
             'traffic_sources':{'metrics':'views,estimatedMinutesWatched','dimensions':'insightTrafficSourceType'},
             'search_terms':{'metrics':'views','dimensions':'insightTrafficSourceDetail','filters':'insightTrafficSourceType==YT_SEARCH','sort':'-views','maxResults':25}}
    sections={}
    for name,params in queries.items():
        try:sections[name]={'status':'ok','rows':_rows(_get(client,ANALYTICS_API,token,base|params))}
        except YouTubeError as e:sections[name]={'status':'error','http_status':e.status,'reason':e.reason}
    ok=any(s['status']=='ok' for s in sections.values())
    return {'status':'ok' if ok else 'error','source':SOURCE_ANALYTICS,'period':{'start':start.isoformat(),'end':end.isoformat()},'sections':sections,
            'not_available_in_api':['impressions','impressions_click_through_rate']}

def read_field(client,token,kind,target_id,field):
    if kind=='video':
        items=_get(client,f'{DATA_API}/videos',token,{'part':'snippet','id':target_id}).get('items') or []
        return (items[0].get('snippet') or {}).get(field,'') if items else None
    if kind=='playlist':
        items=_get(client,f'{DATA_API}/playlists',token,{'part':'snippet','id':target_id}).get('items') or []
        return (items[0].get('snippet') or {}).get(field,'') if items else None
    items=_get(client,f'{DATA_API}/channels',token,{'part':'snippet,brandingSettings','id':target_id}).get('items') or []
    if not items:return None
    summary=channel_summary(items[0])
    return summary['handle'] if field=='handle' else summary.get(field,'')

def same(kind,field,left,right):
    if left is None or right is None:return False
    if field=='handle':return norm(left).casefold().lstrip('@')==norm(right).casefold().lstrip('@')
    return norm(left)==norm(right)

def prepare_write(client,token,kind,target_id,field,current,value,owner):
    """Fresh read before any write: the item must belong to the connected channel and still hold the audited value.

    Returns (status, detail, resource) with status ready, unchanged, conflict or failed.
    """
    if kind=='channel':
        if target_id!=owner:return 'failed','O canal auditado não é o canal conectado; nada foi enviado.',None
        items=_get(client,f'{DATA_API}/channels',token,{'part':'brandingSettings','id':target_id}).get('items') or []
        if not items:return 'failed','O YouTube não encontrou o canal.',None
        resource=items[0].get('brandingSettings') or {};live=(resource.get('channel') or {}).get(field,'')
    else:
        items=_get(client,f'{DATA_API}/{kind}s',token,{'part':'snippet','id':target_id}).get('items') or []
        if not items:return 'failed','O YouTube não encontrou o item; ele pode ter sido removido.',None
        resource=items[0].get('snippet') or {};live=resource.get(field,'')
        if resource.get('channelId')!=owner:return 'failed','O item não pertence ao canal conectado; nada foi enviado.',None
        if kind=='video' and not resource.get('categoryId'):return 'failed','O YouTube não retornou a categoria obrigatória para atualizar o vídeo.',None
    if same(kind,field,live,value):return 'unchanged','',resource
    if not same(kind,field,live,current):return 'conflict','O valor no YouTube mudou desde a auditoria; nada foi enviado.',resource
    return 'ready','',resource

def send_write(client,token,kind,target_id,field,value,resource):
    """videos/playlists/channels.update delete omitted properties, so every mutable field read is sent back."""
    if kind=='video':
        _put(client,f'{DATA_API}/videos',token,{'part':'snippet'},{'id':target_id,'snippet':{k:resource[k] for k in VIDEO_SNIPPET_KEEP if k in resource}|{field:value}})
    elif kind=='playlist':
        _put(client,f'{DATA_API}/playlists',token,{'part':'snippet'},{'id':target_id,'snippet':{k:resource[k] for k in PLAYLIST_SNIPPET_KEEP if k in resource}|{field:value}})
    else:
        settings=dict(resource.get('channel') or {})|{field:value}
        body={'channel':settings}|({'watch':resource['watch']} if resource.get('watch') else {})
        _put(client,f'{DATA_API}/channels',token,{'part':'brandingSettings'},{'id':target_id,'brandingSettings':body})

def send_through_publication(jid,field,value,snippet):
    """Studio uploads keep using the existing edit route so youtube_publications stays in sync."""
    from .youtube_publish import MetadataUpdate,update_metadata
    title=value if field=='title' else snippet.get('title','')
    description=value if field=='description' else snippet.get('description','')
    update_metadata(jid,MetadataUpdate(title=title,description=description,confirm_update=True))

# ---------------------------------------------------------------- persistence helpers

def credential(c,cid):
    row=c.execute('SELECT youtube_channel_id,youtube_title,token_encrypted FROM channel_credentials WHERE channel_id=%s',(cid,)).fetchone()
    if not row:return None
    scopes=set(json.loads(cipher().decrypt(row['token_encrypted'].encode())).get('scope','').split())
    return {'youtube_channel_id':row['youtube_channel_id'],'youtube_title':row['youtube_title'],'read_authorized':bool(scopes&set(READ_SCOPES)),
            'analytics_authorized':ANALYTICS_SCOPE in scopes,'edit_authorized':bool(scopes&set(MANAGE_SCOPES))}

def scope_check(*required):
    def allowed(tokens):
        scopes=set(tokens.get('scope','').split())
        return all(scopes&set(group) for group in required)
    return allowed

def token_for(client,cid,yt_id,*required):
    try:return access_token(client,{'channel_id':cid,'youtube_channel_id':yt_id},allowed=scope_check(*required))
    except ValueError:raise HTTPException(409,'Reconecte o YouTube autorizando as permissões indicadas nesta tela.') from None
    except httpx.HTTPError:raise HTTPException(502,'Não foi possível renovar o acesso ao YouTube. Tente novamente.') from None

def manual_context(c,cid):
    """Studio captures already stored by Growth, labelled as manual."""
    from .growth import ranked_search_phrases
    latest=c.execute('SELECT observed_date,"window",metrics FROM channel_growth_observations WHERE channel_id=%s ORDER BY observed_date DESC,created_at DESC LIMIT 1',(cid,)).fetchone()
    rows=c.execute('SELECT video_url,observed_date,metrics FROM analytics_snapshots WHERE channel_id=%s ORDER BY observed_date DESC LIMIT 1000',(cid,)).fetchall()
    phrases=ranked_search_phrases(rows)
    trends=((latest or {}).get('metrics') or {}).get('search_trends') or []
    phrases+=[{'phrase':t,'observations':1,'videos':0,'last_observed':str(latest['observed_date'])} for t in trends if t.casefold() not in {p['phrase'].casefold() for p in phrases}]
    return {'source':SOURCE_MANUAL,'latest_channel_capture':{'observed_date':str(latest['observed_date']),'window':latest['window'],'metrics':latest['metrics']} if latest else None,
            'search_phrases':phrases}

VIDEO_ID=re.compile(r'[0-9A-Za-z_-]{11}')
OBSERVED_METRICS=('impressions','ctr_percent','views','average_view_duration_seconds','watch_hours','returning_viewers',
                  'retention_15_percent','retention_30_percent','retention_45_percent')

def video_id_from_url(url):
    """watch?v=, youtu.be/, /shorts/, /live/ and /embed/ addresses of one video; anything else is unmatched."""
    u=urlparse(str(url or '').strip())
    if u.hostname=='youtu.be':candidate=u.path.strip('/').split('/')[0]
    elif u.hostname in ('youtube.com','www.youtube.com','m.youtube.com'):
        parts=[p for p in u.path.split('/') if p]
        if parts[:1]==['watch']:candidate=next((q[2:] for q in u.query.split('&') if q.startswith('v=')),'')
        elif len(parts)>=2 and parts[0] in ('shorts','live','embed'):candidate=parts[1]
        else:candidate=''
    else:candidate=''
    return candidate if VIDEO_ID.fullmatch(candidate or '') else None

def registered_publications(c,cid):
    if not c.execute("SELECT to_regclass('youtube_publications') AS t").fetchone()['t']:return {}
    rows=c.execute("SELECT id,video_id,intent,primary_phrase,title FROM youtube_publications WHERE channel_id=%s AND state='uploaded' AND video_id IS NOT NULL",(cid,)).fetchall()
    return {r['video_id']:r for r in rows}

def infer_intent(title,description):
    from .growth import _INTENT_TERMS
    words=set(tokens(f'{title} {description[:300]}'))
    scores={intent:len(words&terms) for intent,terms in _INTENT_TERMS.items()}
    best=max(scores.values(),default=0)
    leaders=[intent for intent,score in scores.items() if score==best]
    return leaders[0] if best and len(leaders)==1 else None

def channel_metadata_rules(c,cid):
    """Editorial rules of the channel's default recipe profile; legacy LoFi rules when none is set."""
    from .niche_profiles import metadata_rules,resolve
    try:
        from .recipes import for_channel
        recipe=for_channel(c,cid)
    except HTTPException:recipe=None
    data=(recipe or {}).get('data')
    return {**metadata_rules(data),'source':resolve(data)['source'],'recipe_sha256':(recipe or {}).get('sha256')}

def video_catalog(c,cid,run):
    """Every imported video with the observations already saved for it; absent data stays absent, never zero."""
    from .youtube_metadata import editorial_phrase,metadata_issues
    snapshot=run['snapshot'];findings=run['findings'] or []
    rows=c.execute('''SELECT video_url,observed_date,"window",video_age_days,content_format,intent,metrics,created_at FROM analytics_snapshots
                      WHERE channel_id=%s ORDER BY observed_date DESC,created_at DESC LIMIT 2000''',(cid,)).fetchall()
    observations={}
    for row in rows:
        vid=video_id_from_url(row['video_url'])
        if vid:observations.setdefault(vid,[]).append(row)
    publications=registered_publications(c,cid)
    rules_source=channel_metadata_rules(c,cid)
    api_rows={r.get('video'):r for r in ((((run['analytics'] or {}).get('sections') or {}).get('videos') or {}).get('rows') or [])}
    period=(run['analytics'] or {}).get('period')
    out=[]
    for v in snapshot.get('videos') or []:
        vid=v['id'];own=observations.get(vid,[]);publication=publications.get(vid)
        latest={}
        for row in own:latest.setdefault(row['window'],row)
        windows=[]
        for window,row in sorted(latest.items(),key=lambda item:['24h','7d','28d','90d'].index(item[0]) if item[0] in ('24h','7d','28d','90d') else 9):
            metrics=row['metrics'] if isinstance(row['metrics'],dict) else json.loads(row['metrics'] or '{}')
            windows.append({'window':window,'observed_date':row['observed_date'],'video_age_days':row['video_age_days'],'source':SOURCE_MANUAL,
                            'metrics':{k:metrics.get(k) for k in OBSERVED_METRICS if metrics.get(k) is not None},
                            'missing':[k for k in OBSERVED_METRICS if metrics.get(k) is None],'search_terms':metrics.get('search_terms') or []})
        recorded_intent=(publication or {}).get('intent') or next((r['intent'] for r in own if r.get('intent')),'')
        intent={'value':recorded_intent,'source':'youtube_publications' if (publication or {}).get('intent') else SOURCE_MANUAL,'basis':'recorded'} if recorded_intent else None
        if not intent:
            guess=infer_intent(v.get('title',''),v.get('description',''))
            intent={'value':guess,'source':'title_and_description_terms','basis':'hypothesis'} if guess else None
        phrase=(publication or {}).get('primary_phrase') or ''
        issues=[{'rule':rule,'message':message} for rule,message in metadata_issues(v.get('title',''),v.get('description',''),phrase or None,
                min_description=rules_source['min_description'],phrase_first=rules_source['phrase_first'])]
        rules={'primary_phrase':phrase or None,'primary_phrase_source':'youtube_publications' if phrase else None,'issues':issues,
               'profile_rules':rules_source,
               'phrase_rules_evaluated':bool(phrase),
               'reference_phrase':None if phrase or not intent or rules_source['language']!='en' else editorial_phrase(intent['value'])}
        mine=[f for f in findings if f.get('target_id')==vid or vid in (f.get('related_ids') or [])]
        recommendations=[{'text':f['recommendation'],'evidence':f['evidence'],'basis':'hypothesis' if f['basis']!='observed' else 'observed',
                          'impact':f['impact'],'finding_id':f['id']} for f in mine if f['scope']=='video']
        recommendations+=[{'text':i['message'],'evidence':'Regra do contrato editorial em studio/youtube_metadata.py.','basis':'observed',
                           'impact':'Hipótese: o texto foge do padrão editorial do canal; isso não mede desempenho.','finding_id':None} for i in issues]
        if not windows:
            recommendations.append({'text':'Registre as métricas deste vídeo em Análises → Métricas por vídeo antes de priorizar mudanças por desempenho.',
                                    'evidence':'Nenhuma observação do YouTube Studio salva para este vídeo.','basis':'hypothesis',
                                    'impact':'Sem dados, as recomendações acima são editoriais, não baseadas em desempenho.','finding_id':None})
        api=api_rows.get(vid)
        out.append({'id':vid,'title':v.get('title',''),'description':v.get('description',''),'url':f'https://www.youtube.com/watch?v={vid}',
                    'observed_urls':sorted({r['video_url'] for r in own}),'privacy':v.get('privacy'),'published_at':v.get('published_at'),
                    'duration':v.get('duration'),'thumbnail':v.get('thumbnail'),'public_views':v.get('public_views'),
                    'origin':'studio' if publication else 'external','publication_id':(publication or {}).get('id'),
                    'observations':windows,'data_status':'observed' if windows else 'no_observations',
                    'analytics_api':{'source':SOURCE_ANALYTICS,'period':period,**{k:api.get(k) for k in ('views','estimatedMinutesWatched','averageViewDuration','averageViewPercentage')}} if api else None,
                    'intent':intent,'metadata_rules':rules,'findings':[f['id'] for f in mine],'recommendations':recommendations})
    return out

def event(c,change_id,action,who,**detail):
    c.execute('INSERT INTO channel_audit_events(change_id,action,actor,detail) VALUES(%s,%s,%s,%s::jsonb)',(change_id,action,who,json.dumps(detail,ensure_ascii=False,default=str)))

def insert_change(c,run,item,who):
    supported,_,_=FIELDS[(item['target_kind'],item['field'])]
    c.execute(f"""UPDATE channel_audit_changes SET state='superseded',updated_at=now() WHERE run_id=%s AND target_kind=%s AND target_id=%s AND field=%s
                  AND state IN ({",".join(["%s"]*len(OPEN_STATES))})""",(run['id'],item['target_kind'],item['target_id'],item['field'],*OPEN_STATES))
    chid=uuid.uuid4()
    c.execute('''INSERT INTO channel_audit_changes(id,run_id,channel_id,youtube_channel_id,target_kind,target_id,target_label,field,current_value,suggested_value,
                 rationale,finding_ids,origin,api_supported,manual_instructions) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)''',
              (chid,run['id'],run['channel_id'],run['youtube_channel_id'],item['target_kind'],item['target_id'],item.get('target_label','')[:300],item['field'],
               item['current_value'],item['suggested_value'],item.get('rationale','')[:2000],json.dumps(item.get('finding_ids',[])),item['origin'],supported,
               '' if supported else STUDIO_STEPS.get((item['target_kind'],item['field']),'Faça a alteração no YouTube Studio.')))
    event(c,chid,'proposed',who,origin=item['origin'],suggested_sha256=digest(item['suggested_value']))
    return chid

def snapshot_value(snapshot,kind,target_id,field):
    if kind=='channel':
        ch=snapshot['channel']
        return ch.get(field,'') if ch['id']==target_id else None
    rows=snapshot.get('videos' if kind=='video' else 'playlists') or []
    row=next((r for r in rows if r['id']==target_id),None)
    return None if row is None else row.get(field,'')

def run_row(c,cid,rid):
    row=c.execute('SELECT * FROM channel_audit_runs WHERE id=%s AND channel_id=%s',(rid,cid)).fetchone()
    if not row:raise HTTPException(404,'Auditoria não encontrada neste canal.')
    return row

def change_row(c,cid,chid,lock=False):
    row=c.execute('SELECT * FROM channel_audit_changes WHERE id=%s AND channel_id=%s'+(' FOR UPDATE' if lock else ''),(chid,cid)).fetchone()
    if not row:raise HTTPException(404,'Alteração não encontrada neste canal.')
    return row

PUBLIC_CHANGE=('id','run_id','target_kind','target_id','target_label','field','current_value','suggested_value','rationale','finding_ids','origin',
               'api_supported','manual_instructions','state','approved_by','approved_at','applied_at','observed_value','verified_at','detail','created_at','updated_at')

def public_change(row):
    return {k:row.get(k) for k in PUBLIC_CHANGE}|{'suggested_sha256':digest(row['suggested_value'])}


def review_editorial_change(c,cid,row):
    if row['field'] not in ('title','description'):return None
    from .editorial import for_channel,require
    return require({row['field']:row['suggested_value']},for_channel(c,cid),reviewed=True)

# ---------------------------------------------------------------- routes

class ChannelRef(BaseModel):
    model_config=ConfigDict(extra='forbid')
    channel_ref:str=Field(min_length=2,max_length=300)

class AuditRequest(ChannelRef):
    confirmed_youtube_channel_id:str=Field(min_length=24,max_length=24)
    official_name:str=Field(default=OFFICIAL_NAME,min_length=2,max_length=100)
    forbidden_variants:list[str]=Field(default_factory=lambda:list(FORBIDDEN_VARIANTS),max_length=20)
    intended_searches:list[str]=Field(default_factory=list,max_length=12)
    include_analytics:bool=True

    @field_validator('forbidden_variants','intended_searches')
    @classmethod
    def clean(cls,values):return list(dict.fromkeys(' '.join(v.split())[:100] for v in values if v.strip()))

class ChangeProposal(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target_kind:Literal['channel','video','playlist']
    target_id:str=Field(min_length=1,max_length=64)
    field:Literal['title','description','keywords','handle']
    suggested_value:str=Field(max_length=6000)
    rationale:str=Field(default='',max_length=2000)

class ChangeEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    suggested_value:str=Field(max_length=6000)
    rationale:str|None=Field(default=None,max_length=2000)

class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    decision:Literal['approve','reject']
    suggested_sha256:str=Field(min_length=64,max_length=64)

class ApplyRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    change_ids:list[uuid.UUID]=Field(min_length=1,max_length=100)
    confirm_apply:bool=False
    confirmed_count:int=Field(ge=1,le=100)

def _client():return httpx.Client(timeout=30)

@router.get('/{cid}/channel-audit/connection')
def connection(cid:uuid.UUID):
    with db() as c:
        profile(c,cid)
        state=credential(c,cid) if configured() else None
    return {'oauth_available':configured(),'connected':bool(state),**(state or {}),
            'scopes_needed':{'audit':'youtube.readonly','analytics':'yt-analytics.readonly (opcional)','apply':'youtube.force-ssl (somente para aplicar)'},
            'interpretation_note':CAUTION}

@router.post('/{cid}/channel-audit/resolve')
def resolve_channel(cid:uuid.UUID,body:ChannelRef):
    """Identify the exact channel before any import or analysis."""
    try:ref=parse_channel_ref(body.channel_ref)
    except ValueError as e:raise HTTPException(422,str(e)) from None
    with db() as c:
        profile(c,cid);state=credential(c,cid) if configured() else None
    if not state:raise HTTPException(409,'Conecte o YouTube deste canal antes de auditar.')
    with _client() as client:
        token=token_for(client,cid,state['youtube_channel_id'],READ_SCOPES)
        try:item=resolve(client,token,ref)
        except YouTubeError as e:raise HTTPException(502,f'O YouTube recusou a consulta ({e.status}{" "+e.reason if e.reason else ""}).') from None
    summary=channel_summary(item)
    return {'channel':{k:summary[k] for k in ('id','title','handle','thumbnail','published_at','public_counts')},'resolved_by':next(iter(ref)),
            'matches_connection':summary['id']==state['youtube_channel_id'],'connected_youtube_channel_id':state['youtube_channel_id'],
            'analytics_authorized':state['analytics_authorized'],'edit_authorized':state['edit_authorized']}

@router.post('/{cid}/channel-audit/runs')
def create_run(cid:uuid.UUID,body:AuditRequest,request:Request):
    ready()
    try:ref=parse_channel_ref(body.channel_ref);brand=brand_rules(body.official_name,body.forbidden_variants)
    except ValueError as e:raise HTTPException(422,str(e)) from None
    with db() as c:
        profile(c,cid);state=credential(c,cid) if configured() else None
        manual=manual_context(c,cid);rules=channel_metadata_rules(c,cid)
    if not state:raise HTTPException(409,'Conecte o YouTube deste canal antes de auditar.')
    if body.confirmed_youtube_channel_id!=state['youtube_channel_id']:
        raise HTTPException(409,'O canal confirmado não é o canal do YouTube conectado a este estúdio. Nada foi importado.')
    fetched_at=datetime.now(timezone.utc).isoformat()
    with _client() as client:
        token=token_for(client,cid,state['youtube_channel_id'],READ_SCOPES)
        try:
            item=resolve(client,token,ref)
            if item['id']!=body.confirmed_youtube_channel_id:raise HTTPException(409,'O endereço agora aponta para outro canal. Confirme a identidade novamente.')
            snapshot=import_snapshot(client,token,item)
        except YouTubeError as e:raise HTTPException(502,f'O YouTube recusou a leitura do canal ({e.status}{" "+e.reason if e.reason else ""}). Nada foi salvo.') from None
        if not body.include_analytics:analytics={'status':'not_requested'}
        elif not state['analytics_authorized']:analytics={'status':'not_authorized'}
        else:analytics=fetch_analytics(client,token_for(client,cid,state['youtube_channel_id'],READ_SCOPES,(ANALYTICS_SCOPE,)))
    findings,diagnosis=run_findings(snapshot,brand,analytics,manual,body.intended_searches,rules['source']=='legacy_lofi_default')
    snapshot_json=json.dumps(snapshot,ensure_ascii=False,sort_keys=True)
    provenance={'data':{'source':SOURCE_DATA,'fetched_at':fetched_at,'resolved_by':next(iter(ref)),
                        'endpoints':['channels.list','playlistItems.list','videos.list','playlists.list']},
                'analytics':{'source':SOURCE_ANALYTICS,'status':analytics.get('status'),'period':analytics.get('period')},
                'manual':{'source':SOURCE_MANUAL,'latest_capture_date':(manual.get('latest_channel_capture') or {}).get('observed_date'),'search_phrases':len(manual['search_phrases'])},
                'third_party_tools':[]}
    rid=uuid.uuid4();who=actor(request)
    with db() as c:
        c.execute('''INSERT INTO channel_audit_runs(id,channel_id,youtube_channel_id,channel_ref,brand,intended_searches,snapshot,snapshot_sha256,analytics,findings,diagnosis,provenance,created_by)
                     VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s)''',
                  (rid,cid,item['id'],body.channel_ref.strip(),json.dumps(brand,ensure_ascii=False),json.dumps(body.intended_searches,ensure_ascii=False),snapshot_json,
                   hashlib.sha256(snapshot_json.encode()).hexdigest(),json.dumps(analytics,ensure_ascii=False),json.dumps(findings,ensure_ascii=False),
                   json.dumps(diagnosis,ensure_ascii=False),json.dumps(provenance,ensure_ascii=False),who))
        run={'id':rid,'channel_id':cid,'youtube_channel_id':item['id']}
        for proposal in brand_proposals(snapshot,brand,findings):insert_change(c,run,proposal,who)
        audit(c,'CHANNEL_AUDIT_CREATED',str(rid),f"{item['id']} videos={len(snapshot['videos'])} findings={len(findings)}")
        c.commit()
    return get_run(cid,rid)

@router.get('/{cid}/channel-audit/runs')
def list_runs(cid:uuid.UUID):
    ready()
    with db() as c:
        profile(c,cid)
        rows=c.execute('''SELECT r.id,r.youtube_channel_id,r.created_at,r.created_by,r.snapshot->'channel'->>'title' AS title,
                          jsonb_array_length(r.snapshot->'videos') AS videos,jsonb_array_length(r.findings) AS findings,r.diagnosis->>'status' AS diagnosis,
                          (SELECT count(*) FROM channel_audit_changes x WHERE x.run_id=r.id AND x.state='verified') AS verified_changes
                          FROM channel_audit_runs r WHERE r.channel_id=%s ORDER BY r.created_at DESC LIMIT 50''',(cid,)).fetchall()
    return {'runs':rows,'interpretation_note':CAUTION}

@router.get('/{cid}/channel-audit/runs/{rid}')
def get_run(cid:uuid.UUID,rid:uuid.UUID):
    ready()
    with db() as c:
        profile(c,cid);run=run_row(c,cid,rid)
        changes=c.execute("SELECT * FROM channel_audit_changes WHERE run_id=%s AND state<>'superseded' ORDER BY target_kind,target_label,field",(rid,)).fetchall()
        events=c.execute('''SELECT e.change_id,e.action,e.actor,e.detail,e.created_at FROM channel_audit_events e JOIN channel_audit_changes x ON x.id=e.change_id
                            WHERE x.run_id=%s ORDER BY e.id''',(rid,)).fetchall()
        videos=video_catalog(c,cid,run)
        from .editorial import for_channel as editorial_for_channel
        editorial_policy=editorial_for_channel(c,cid)
    return {'run':{k:run[k] for k in ('id','youtube_channel_id','channel_ref','brand','intended_searches','snapshot','snapshot_sha256','analytics',
                                      'findings','diagnosis','provenance','created_by','created_at')},
            'videos':videos,'changes':[public_change(r)|{'editorial_language':editorial_policy['language']} for r in changes],
            'editorial_contract':editorial_policy,'events':events,'interpretation_note':CAUTION}

@router.post('/{cid}/channel-audit/runs/{rid}/changes')
def propose_change(cid:uuid.UUID,rid:uuid.UUID,body:ChangeProposal,request:Request):
    ready()
    with db() as c:
        profile(c,cid);run=run_row(c,cid,rid)
        if (body.target_kind,body.field) not in FIELDS:raise HTTPException(422,'Campo não suportado para este tipo de item.')
        current=snapshot_value(run['snapshot'],body.target_kind,body.target_id,body.field)
        if current is None:raise HTTPException(404,'Item não encontrado no canal importado por esta auditoria.')
        value=body.suggested_value.strip()
        check(run['brand'],body.target_kind,body.field,value,current)
        label=next((r.get('title') for r in run['snapshot'].get('videos' if body.target_kind=='video' else 'playlists') or [] if r['id']==body.target_id),None) if body.target_kind!='channel' else run['snapshot']['channel'].get('title')
        chid=insert_change(c,run,{'target_kind':body.target_kind,'target_id':body.target_id,'target_label':label or body.target_id,'field':body.field,
                                  'current_value':current,'suggested_value':value,'rationale':body.rationale.strip(),'origin':'user'},actor(request))
        c.commit()
        row=change_row(c,cid,chid)
    return public_change(row)

def check(brand,kind,field,value,current):
    ok,message=valid_value(kind,field,value)
    if not ok:raise HTTPException(422,message)
    issues=brand_issues(value,brand)
    if issues:raise HTTPException(422,'O valor sugerido contém grafia proibida: '+', '.join(issues)+'.')
    if norm(value)==norm(current):raise HTTPException(422,'O valor sugerido é igual ao atual.')

@router.put('/{cid}/channel-audit/changes/{chid}')
def edit_change(cid:uuid.UUID,chid:uuid.UUID,body:ChangeEdit,request:Request):
    """Editing returns the change to review; a previous approval never carries over to new text."""
    ready()
    with db() as c:
        row=change_row(c,cid,chid,lock=True)
        if row['state'] not in OPEN_STATES:raise HTTPException(409,'Só alterações ainda não aplicadas podem ser editadas.')
        run=run_row(c,cid,row['run_id']);value=body.suggested_value.strip()
        check(run['brand'],row['target_kind'],row['field'],value,row['current_value'])
        c.execute('''UPDATE channel_audit_changes SET suggested_value=%s,rationale=COALESCE(%s,rationale),state='proposed',approved_by=NULL,approved_at=NULL,
                     approved_sha256=NULL,updated_at=now() WHERE id=%s''',(value,body.rationale,chid))
        event(c,chid,'edited',actor(request),suggested_sha256=digest(value),previous_state=row['state'])
        c.commit();row=change_row(c,cid,chid)
    return public_change(row)

@router.post('/{cid}/channel-audit/changes/{chid}/decision',dependencies=[Depends(require_admin)])
def decide(cid:uuid.UUID,chid:uuid.UUID,body:Decision,request:Request):
    ready()
    with db() as c:
        row=change_row(c,cid,chid,lock=True)
        if row['state'] not in OPEN_STATES:raise HTTPException(409,'Esta alteração já saiu da revisão.')
        if body.suggested_sha256!=digest(row['suggested_value']):raise HTTPException(409,'O texto mudou desde que você o revisou. Revise de novo antes de decidir.')
        who=actor(request)
        editorial=None
        if body.decision=='approve':
            issues=brand_issues(row['suggested_value'],run_row(c,cid,row['run_id'])['brand'])
            if issues:raise HTTPException(409,'A sugestão ainda contém grafia proibida ('+', '.join(issues)+'). Reescreva antes de aprovar.')
            editorial=review_editorial_change(c,cid,row)
            c.execute('UPDATE channel_audit_changes SET approved_editorial_sha256=%s WHERE id=%s',((editorial or {}).get('contract_sha256'),chid))
            c.execute("UPDATE channel_audit_changes SET state='approved',approved_by=%s,approved_at=now(),approved_sha256=%s,updated_at=now() WHERE id=%s",(who,body.suggested_sha256,chid))
        else:
            c.execute("UPDATE channel_audit_changes SET state='rejected',approved_by=NULL,approved_at=NULL,approved_sha256=NULL,updated_at=now() WHERE id=%s",(chid,))
        event(c,chid,'approved' if body.decision=='approve' else 'rejected',who,suggested_sha256=body.suggested_sha256,editorial_review=editorial)
        c.commit();row=change_row(c,cid,chid)
    return public_change(row)

@router.post('/{cid}/channel-audit/runs/{rid}/apply',dependencies=[Depends(require_admin)])
def apply_changes(cid:uuid.UUID,rid:uuid.UUID,body:ApplyRequest,request:Request):
    """Send only approved, API-editable changes named in this request, then confirm each by re-reading YouTube."""
    if not body.confirm_apply:raise HTTPException(422,'Confirme explicitamente a publicação das alterações selecionadas no YouTube.')
    ids=list(dict.fromkeys(body.change_ids))
    if body.confirmed_count!=len(ids):raise HTTPException(422,'A confirmação não corresponde à quantidade de alterações selecionadas.')
    ready();who=actor(request)
    with db() as c:
        profile(c,cid);run=run_row(c,cid,rid);state=credential(c,cid) if configured() else None
        if not state or state['youtube_channel_id']!=run['youtube_channel_id']:raise HTTPException(409,'O YouTube conectado não é o canal auditado. Nada foi enviado.')
        if not state['edit_authorized']:raise HTTPException(409,'Autorize a edição (youtube.force-ssl) antes de aplicar. Nada foi enviado.')
        rows=c.execute('SELECT * FROM channel_audit_changes WHERE run_id=%s AND id=ANY(%s) FOR UPDATE',(rid,ids)).fetchall()
        if len(rows)!=len(ids):raise HTTPException(404,'Alguma alteração não pertence a esta auditoria.')
        blocked=[r for r in rows if r['state']!='approved' or r['approved_sha256']!=digest(r['suggested_value'])]
        if blocked:raise HTTPException(409,f'{len(blocked)} alteração(ões) não estão aprovadas com o texto atual. Nada foi enviado.')
        manual=[r for r in rows if not r['api_supported']]
        if manual:raise HTTPException(409,'Alterações manuais (nome, identificador) são feitas no YouTube Studio e confirmadas com “Reler no YouTube”.')
        for r in rows:
            editorial=review_editorial_change(c,cid,r)
            if editorial and r.get('approved_editorial_sha256')!=editorial['contract_sha256']:
                raise HTTPException(409,'O perfil editorial mudou ou a aprovação é anterior a esta validação. Revise e aprove novamente antes de publicar.')
        for r in rows:
            c.execute("UPDATE channel_audit_changes SET state='applying',updated_at=now() WHERE id=%s",(r['id'],))
            event(c,r['id'],'apply_requested',who,confirmed_count=body.confirmed_count)
        c.commit()
    with db() as c:publications=registered_publications(c,cid)
    results=[];owner=run['youtube_channel_id']
    with _client() as client:
        try:token=token_for(client,cid,owner,MANAGE_SCOPES)
        except HTTPException as e:
            token=None;failure=e.detail
        for r in rows:
            outcome={'id':r['id'],'target_kind':r['target_kind'],'target_id':r['target_id'],'field':r['field']}
            if token is None:
                results.append(outcome|record(cid,r['id'],'failed',failure,None,who,applied=False));continue
            try:
                status,detail,resource=prepare_write(client,token,r['target_kind'],r['target_id'],r['field'],r['current_value'],r['suggested_value'],owner)
                if status in ('failed','conflict'):results.append(outcome|record(cid,r['id'],status,detail,None,who,applied=False));continue
                sent=status=='ready'
                if sent and r['target_kind']=='video' and r['target_id'] in publications:
                    try:send_through_publication(publications[r['target_id']]['id'],r['field'],r['suggested_value'],resource)
                    except HTTPException as e:
                        results.append(outcome|record(cid,r['id'],'failed',str(e.detail),None,who,applied=False));continue
                elif sent:send_write(client,token,r['target_kind'],r['target_id'],r['field'],r['suggested_value'],resource)
                observed=read_field(client,token,r['target_kind'],r['target_id'],r['field'])
                if same(r['target_kind'],r['field'],observed,r['suggested_value']):
                    results.append(outcome|record(cid,r['id'],'verified','Confirmado por nova leitura do YouTube.' if sent else 'O YouTube já tinha o valor aprovado; nada foi enviado.',observed,who,applied=sent))
                else:
                    results.append(outcome|record(cid,r['id'],'unverified','O YouTube respondeu, mas a releitura não mostra o valor aprovado. Releia mais tarde.',observed,who,applied=sent))
            except YouTubeError as e:
                results.append(outcome|record(cid,r['id'],'failed',f'O YouTube recusou ({e.status}{" "+e.reason if e.reason else ""}).',None,who,applied=False))
            except httpx.HTTPError:
                results.append(outcome|record(cid,r['id'],'unverified','Sem resposta do YouTube; use “Reler no YouTube” para saber se a alteração foi salva.',None,who,applied=False))
    summary={s:sum(1 for r in results if r['state']==s) for s in ('verified','unverified','failed','conflict')}
    return {'results':results,'summary':summary,'all_verified':summary['verified']==len(results)}

def record(cid,chid,state,detail,observed,who,applied):
    with db() as c:
        c.execute('''UPDATE channel_audit_changes SET state=%s,detail=%s,observed_value=%s,applied_at=CASE WHEN %s THEN now() ELSE applied_at END,
                     verified_at=CASE WHEN %s='verified' THEN now() ELSE verified_at END,updated_at=now() WHERE id=%s AND channel_id=%s''',
                  (state,detail,observed,applied,state,chid,cid))
        event(c,chid,state,who,detail=detail,sent=applied,observed_sha256=digest(observed) if observed is not None else None)
        audit(c,'CHANNEL_AUDIT_CHANGE_'+state.upper(),str(chid),detail);c.commit()
    return {'state':state,'detail':detail,'observed_value':observed}

@router.post('/{cid}/channel-audit/changes/{chid}/verify')
def verify_change(cid:uuid.UUID,chid:uuid.UUID,request:Request):
    """Re-read YouTube: confirms manual Studio edits and settles uncertain applications."""
    ready()
    with db() as c:
        row=change_row(c,cid,chid);state=credential(c,cid) if configured() else None
    if row['state'] not in ('approved','applying','verified','unverified','failed','conflict'):raise HTTPException(409,'Aprove a alteração antes de conferi-la no YouTube.')
    if row['state']=='approved' and row['api_supported']:raise HTTPException(409,'Aplique a alteração aprovada antes de conferi-la.')
    if not state or state['youtube_channel_id']!=row['youtube_channel_id']:raise HTTPException(409,'O YouTube conectado não é o canal auditado.')
    with _client() as client:
        token=token_for(client,cid,row['youtube_channel_id'],READ_SCOPES)
        try:observed=read_field(client,token,row['target_kind'],row['target_id'],row['field'])
        except YouTubeError as e:raise HTTPException(502,f'O YouTube recusou a leitura ({e.status}).') from None
    if same(row['target_kind'],row['field'],observed,row['suggested_value']):
        result=record(cid,chid,'verified','Confirmado por nova leitura do YouTube.',observed,actor(request),applied=False)
    else:
        result=record(cid,chid,'unverified' if row['state']!='failed' else 'failed','A leitura atual do YouTube não mostra o valor aprovado.',observed,actor(request),applied=False)
    return {'id':chid,**result}
