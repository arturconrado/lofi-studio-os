"""Recipes: versioned music + visual + cadence + copy bundles an operator picks per production.

Revisions are immutable and bound by sha256, like channel harness profiles. A recipe never
authorizes spending; the production that uses it carries its own cost ceiling. A visual
variant other than the canonical illustration stays unusable until a person approves its
reference as the same girl and cat (docs/audit-2026-10-15/08-DECISOES_E_LIMITES.md).
"""
import hashlib,json,string,uuid
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field,ConfigDict,field_validator,model_validator
from .core import db,audit,ensure_once
from .channels import profile
from .music_styles import STYLES,MusicStyle
from .scene_profiles import SCENES,LEGACY,Scenario
from .action_states import SequenceName,ContextualAction
from .harness_profiles import NichePolicy,enforce

router=APIRouter(prefix='/recipes')
channel_router=APIRouter(prefix='/channels')
SHA=r'^[a-f0-9]{64}$'
TEMPLATE_FIELDS={'scene_title','hours','hours_label','style_title','idea','mood','hashtags'}
SCENE_TITLES={'city_sunset':'City Sunset Window','mountain_stars':'Mountain Stars Window','balcony_dawn':'Balcony Dawn',
              'snowy_night_studio':'Snowy Night Studio','greenhouse_rain_study':'Greenhouse Rain Study','autumn_bookshop':'Autumn Bookshop'}
PAINTERLY='Original painterly lo-fi illustration, 16:9, fictional adult person, no text or watermark.'


class Marker(BaseModel):
    model_config=ConfigDict(extra='forbid')
    minute:int=Field(ge=1,le=59)
    sequence:SequenceName


class MusicBible(BaseModel):
    model_config=ConfigDict(extra='forbid')
    style_id:MusicStyle='jazz_lofi'
    bible:str=Field(default='',max_length=1500)
    bpm_range:tuple[int,int]|None=None
    instruments:list[str]=Field(default_factory=list,max_length=12)
    moods:list[str]=Field(default_factory=list,max_length=12)
    keys:list[str]=Field(default_factory=list,max_length=12)
    avoid:list[str]=Field(default_factory=list,max_length=12)
    crossfade_seconds:float=Field(default=1.5,ge=0,le=5)
    ambient_bed:Literal['none','rain','fireplace']='none'
    ambient_gain_db:float=Field(default=-26,ge=-40,le=-12)

    @field_validator('instruments','moods','keys','avoid')
    @classmethod
    def short(cls,v):
        if any(not x.strip() or len(x)>80 for x in v):raise ValueError('Cada item precisa ter de 1 a 80 caracteres')
        return [x.strip() for x in v]

    @field_validator('bpm_range')
    @classmethod
    def tempo(cls,v):
        if v and not 35<=v[0]<=v[1]<=180:raise ValueError('BPM entre 35 e 180, mínimo antes do máximo')
        return v


class VisualBible(BaseModel):
    model_config=ConfigDict(extra='forbid')
    variant:Literal['canonical_illustrated','pixel_art_reviewed']='canonical_illustrated'
    reference_pilot_ids:list[uuid.UUID]=Field(default_factory=list,max_length=6)
    reference_asset_sha256:list[str]=Field(default_factory=list,max_length=6)
    allowed_scenarios:list[Scenario]=Field(default_factory=list,max_length=6)
    default_scenario:Scenario='snowy_night_studio'
    shirt_color:Literal['violet','pink','orange','green','royal blue']='violet'
    weather:Literal['scene_default','clear','rain','snow','fog']='scene_default'
    time_of_day:Literal['scene_default','static','sunset_to_night','night_stars','night_to_dawn','day_to_dusk']='scene_default'
    image_prompt_suffix:str=Field(default=PAINTERLY,max_length=400)

    @field_validator('reference_asset_sha256')
    @classmethod
    def digests(cls,v):
        import re
        if any(not re.fullmatch(SHA,x) for x in v):raise ValueError('Hash de referência inválido')
        return v

    @model_validator(mode='after')
    def coherent(self):
        if self.allowed_scenarios and self.default_scenario not in self.allowed_scenarios:raise ValueError('O cenário padrão precisa estar entre os permitidos')
        if self.variant!='canonical_illustrated' and not (self.reference_pilot_ids or self.reference_asset_sha256):
            raise ValueError('Uma variante visual precisa de referência revisável da mesma garota e gato')
        return self


class Cadence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    preset:Literal['legacy_10_25_45','quarter_hour_v2','custom_markers']='custom_markers'
    markers:list[Marker]=Field(default_factory=lambda:[Marker(minute=15,sequence='breath_pet'),Marker(minute=30,sequence='window_glance'),Marker(minute=45,sequence='breath_pet')],max_length=12)
    occasional_variations:bool=False
    contextual_actions:list[ContextualAction]=Field(default_factory=list,max_length=3)


class Copy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    style_title:str=Field(default='Lo-Fi',min_length=1,max_length=60)
    title_template:str=Field(default='{scene_title} | {hours_label} of {style_title} for Coding',max_length=200)
    description_template:str=Field(default_factory=lambda:__import__('studio.copywriting',fromlist=['DEFAULT_TEMPLATE']).DEFAULT_TEMPLATE,max_length=3000)
    live_title_template:str=Field(default='{style_title} Radio · {scene_title} | Music for Coding',max_length=200)
    alt_title_templates:list[str]=Field(default_factory=list,max_length=3)
    hashtags:list[str]=Field(default_factory=lambda:['#lofi','#codingmusic','#studymusic'],max_length=3)
    keywords:list[str]=Field(default_factory=list,max_length=12)

    @model_validator(mode='after')
    def fields(self):
        for template in [self.title_template,self.description_template,self.live_title_template,*self.alt_title_templates]:
            try:names={f for _,f,_,_ in string.Formatter().parse(template) if f is not None}
            except ValueError:raise ValueError('Modelo de texto com chaves inválidas') from None
            if not names<=TEMPLATE_FIELDS:raise ValueError('Variáveis permitidas: '+', '.join(sorted(TEMPLATE_FIELDS)))
        return self


class Cost(BaseModel):
    model_config=ConfigDict(extra='forbid')
    default_ceiling_usd_per_hour:float=Field(default=3,ge=0,le=12)


class RecipeData(BaseModel):
    model_config=ConfigDict(extra='forbid',populate_by_name=True)
    version:Literal[1]=1
    music:MusicBible=Field(default_factory=MusicBible)
    visual:VisualBible=Field(default_factory=VisualBible)
    cadence:Cadence=Field(default_factory=Cadence)
    copy_:Copy=Field(default_factory=Copy,alias='copy')
    policy:NichePolicy|None=None
    cost:Cost=Field(default_factory=Cost)

    @model_validator(mode='after')
    def renderable(self):
        spec_from(self,1,'',sha='')  # same validator as a production; fails early with its message
        if self.policy:
            failures=enforce(self.policy.model_dump(),spec_from(self,1,'',sha=''))
            if failures:raise ValueError('A receita viola a própria política: '+' · '.join(failures))
        return self


def dump(data):
    return data.model_dump(mode='json',by_alias=True)


def digest(data):
    return hashlib.sha256(json.dumps(dump(data),sort_keys=True).encode()).hexdigest()


def spec_from(data,hours,idea,sha,scenario=None,overrides=None):
    """ProductionSpec for one block of a production; the harness validator stays the authority."""
    from .production_harness import ProductionSpec
    v=data.visual;cad=data.cadence
    fields=dict(hours=hours,music_style=data.music.style_id,music_brief=(idea or '')[:2000],scenario=scenario or v.default_scenario,
                shirt_color=v.shirt_color,cadence=cad.preset,markers=[m.model_dump() for m in cad.markers] if cad.preset=='custom_markers' else [],
                weather=v.weather,time_of_day=v.time_of_day,occasional_variations=cad.occasional_variations,
                contextual_actions=list(cad.contextual_actions),recipe_sha256=sha,visual_variant=v.variant)
    fields.update(overrides or {})
    try:return ProductionSpec(**fields)
    except ValueError as e:raise ValueError(str(e).split('\n')[-1].split('[type=')[0].replace('Value error, ','').strip()) from None


def render_copy(data,scenario,hours,idea='',mood=''):
    c=data.copy_
    values={'scene_title':SCENE_TITLES.get(scenario,scenario),'hours':hours,'hours_label':f'{hours} Hour'+('s' if hours!=1 else ''),
            'style_title':c.style_title,'idea':idea.strip(),'mood':mood,'hashtags':' '.join(c.hashtags)}
    fill=lambda t:' '.join(t.format(**values).split(' ')).strip()
    description='\n\n'.join(p for p in fill(c.description_template).split('\n\n') if p.strip())
    return {'title':fill(c.title_template)[:100],'description':description[:5000],'live_title':fill(c.live_title_template)[:100],
            'alternatives':[fill(t)[:100] for t in c.alt_title_templates],'keywords':c.keywords}


# Built-in starting points; operators duplicate and adjust them.
SEED={'lofi_hiphop':('autumn_bookshop','Lo-Fi Hip Hop'),'chillhop':('greenhouse_rain_study','Chillhop'),'jazz_lofi':('autumn_bookshop','Lo-Fi Jazzhop'),
      'sleep_lofi':('snowy_night_studio','Sleepy Lo-Fi'),'piano_lofi':('snowy_night_studio','Piano Lo-Fi'),'guitar_lofi':('greenhouse_rain_study','Guitar Lo-Fi'),
      'bossa_lofi':('greenhouse_rain_study','Bossa Lo-Fi'),'8bit_lofi':('snowy_night_studio','8-Bit Lo-Fi'),'synth_lofi':('snowy_night_studio','Synth Lo-Fi')}


def builtin(style):
    scene,title=SEED[style];meta=next(s for s in STYLES if s['id']==style)
    return RecipeData(music=MusicBible(style_id=style,bpm_range=tuple(meta['bpm']) if meta['bpm'] else None),
                      visual=VisualBible(default_scenario=scene),copy=Copy(style_title=title))


def ensure(c):
    c.execute('SELECT pg_advisory_xact_lock(192837491)')
    c.execute('''CREATE TABLE IF NOT EXISTS recipes(
      id UUID PRIMARY KEY,slug TEXT UNIQUE NOT NULL,name TEXT NOT NULL,origin TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'active',current_revision INTEGER NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    c.execute('''CREATE TABLE IF NOT EXISTS recipe_revisions(
      recipe_id UUID NOT NULL REFERENCES recipes(id),revision INTEGER NOT NULL,sha256 TEXT UNIQUE NOT NULL,
      data JSONB NOT NULL,visual_review JSONB,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(recipe_id,revision))''')
    c.execute('''CREATE TABLE IF NOT EXISTS channel_recipes(
      channel_id UUID NOT NULL REFERENCES radio_channels(id),recipe_id UUID NOT NULL REFERENCES recipes(id),
      pinned_sha256 TEXT,is_default BOOLEAN NOT NULL DEFAULT false,position INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(channel_id,recipe_id))''')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS channel_recipes_one_default ON channel_recipes(channel_id) WHERE is_default')
    for style,(_,title) in SEED.items():
        if not c.execute('SELECT 1 FROM recipes WHERE slug=%s',(style.replace('_','-'),)).fetchone():
            insert(c,style.replace('_','-'),title,'builtin',builtin(style))
    import_profiles(c)
    refresh_builtin_copy(c)


def refresh_builtin_copy(c):
    """Untouched built-in recipes move to the viewer-first description, as a new revision."""
    from .copywriting import OLD_TEMPLATE,DEFAULT_TEMPLATE
    rows=c.execute('''SELECT r.id,v.data FROM recipes r JOIN recipe_revisions v ON v.recipe_id=r.id AND v.revision=r.current_revision
      WHERE r.origin='builtin' AND v.data->'copy'->>'description_template'=%s''',(OLD_TEMPLATE,)).fetchall()
    for row in rows:
        data=row['data'];data['copy']=data['copy']|{'description_template':DEFAULT_TEMPLATE,'hashtags':['#lofi','#codingmusic','#studymusic']}
        model=RecipeData.model_validate(data);sha=digest(model)
        if c.execute('SELECT 1 FROM recipe_revisions WHERE sha256=%s',(sha,)).fetchone():continue
        revision=c.execute('SELECT max(revision)+1 n FROM recipe_revisions WHERE recipe_id=%s',(row['id'],)).fetchone()['n']
        c.execute('INSERT INTO recipe_revisions(recipe_id,revision,sha256,data) VALUES(%s,%s,%s,%s)',(row['id'],revision,sha,json.dumps(dump(model))))
        c.execute('UPDATE recipes SET current_revision=%s,updated_at=now() WHERE id=%s',(revision,row['id']))


def insert(c,slug,name,origin,data,review=None):
    rid=uuid.uuid4();sha=digest(data)
    c.execute('INSERT INTO recipes(id,slug,name,origin) VALUES(%s,%s,%s,%s)',(rid,slug,name,origin))
    c.execute('INSERT INTO recipe_revisions(recipe_id,revision,sha256,data,visual_review) VALUES(%s,1,%s,%s,%s)',(rid,sha,json.dumps(dump(data)),json.dumps(review) if review else None))
    return rid,sha


def import_profiles(c):
    """Latest channel harness profile becomes that channel's default recipe, once."""
    if not c.execute("SELECT to_regclass('channel_harness_profiles') t").fetchone()['t']:return
    rows=c.execute('''SELECT DISTINCT ON (channel_id) channel_id,sha256,data FROM channel_harness_profiles
      WHERE NOT EXISTS(SELECT 1 FROM channel_recipes r WHERE r.channel_id=channel_harness_profiles.channel_id)
      ORDER BY channel_id,revision DESC''').fetchall()
    for row in rows:
        d=row['data']['defaults']
        try:
            data=RecipeData(music=MusicBible(style_id=d['music_style'],bible=d.get('music_brief','')[:1500]),
                            visual=VisualBible(default_scenario=d['scenario'],shirt_color=d['shirt_color'],weather=d.get('weather','scene_default'),time_of_day=d.get('time_of_day','scene_default')),
                            cadence=Cadence(preset=d['cadence'],markers=d.get('markers',[]) if d['cadence']=='custom_markers' else [],occasional_variations=d.get('occasional_variations',False),contextual_actions=d.get('contextual_actions',[])),
                            copy=Copy(style_title=next(t for s,(_,t) in SEED.items() if s==d['music_style']) if d['music_style'] in SEED else 'Lo-Fi'),
                            policy=row['data'].get('policy'))
        except ValueError:continue  # Profiles that never compiled stay legacy-only.
        rid,_=insert(c,'profile-'+row['sha256'][:12],row['data']['name'][:100],'imported_profile',data)
        c.execute('INSERT INTO channel_recipes(channel_id,recipe_id,is_default) VALUES(%s,%s,true)',(row['channel_id'],rid))


def ready():
    ensure_once('recipes',ensure)


def ensure_autopilot(c):
    c.execute('CREATE TABLE IF NOT EXISTS autopilot_recipe(id INTEGER PRIMARY KEY CHECK(id=1),recipe_id UUID REFERENCES recipes(id),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())')


def autopilot_music(c):
    """Music bible the autopilot follows; None keeps its original jazzhop rotation."""
    if not c.execute("SELECT to_regclass('autopilot_recipe') t").fetchone()['t']:return None
    row=c.execute('SELECT v.data FROM autopilot_recipe a JOIN recipes r ON r.id=a.recipe_id JOIN recipe_revisions v ON v.recipe_id=r.id AND v.revision=r.current_revision WHERE a.id=1').fetchone()
    return row['data']['music'] if row else None


def autopilot_prompt(music,n):
    from .music_styles import DIRECTIONS
    instruments=music.get('instruments') or ['the style\'s signature instrumentation']
    moods=music.get('moods') or ['rainy window','midnight skyline','warm morning cafe','quiet library','snowy night']
    low,high=music.get('bpm_range') or (66,84)
    bpm=low+n%(high-low+1)
    direction=music.get('bible') or DIRECTIONS[music['style_id']]
    prompt=f'Create an original three-minute instrumental composition. {direction} {instruments[n%len(instruments)]}, {moods[n%len(moods)]}, {bpm} BPM. Detailed coherent arrangement and subtle variation. Clean stereo production, no vocals, no imitation of named artists, no samples of existing music. Smooth intro and natural outro. Theme number {n}.'
    if music.get('avoid'):prompt+=' Avoid: '+', '.join(music['avoid'])+'.'
    return prompt,bpm


def current(c,rid):
    row=c.execute('''SELECT r.*,v.sha256,v.data,v.visual_review FROM recipes r JOIN recipe_revisions v
      ON v.recipe_id=r.id AND v.revision=r.current_revision WHERE r.id=%s''',(rid,)).fetchone()
    if not row:raise HTTPException(404,'Receita não encontrada')
    return row


def usable(row):
    return row['data']['visual']['variant']=='canonical_illustrated' or bool(row['visual_review'])


def public(row):
    out={k:row[k] for k in ('id','slug','name','origin','state','current_revision','sha256','data','visual_review','updated_at') if k in row}
    out['usable']=usable(row);out['pending_reference_review']=not out['usable']
    return out


def for_channel(c,cid,rid=None):
    """Recipe revision a production on this channel may use; default when none is named."""
    ready()
    allowed=c.execute('SELECT recipe_id,pinned_sha256,is_default FROM channel_recipes WHERE channel_id=%s',(cid,)).fetchall()
    if rid is None:
        chosen=next((a for a in allowed if a['is_default']),None)
        if not chosen:raise HTTPException(409,'Escolha uma receita padrão para este canal em Canais')
        rid=chosen['recipe_id']
    elif allowed and not any(str(a['recipe_id'])==str(rid) for a in allowed):
        raise HTTPException(422,'Receita não permitida neste canal')
    row=current(c,rid)
    pin=next((a['pinned_sha256'] for a in allowed if str(a['recipe_id'])==str(rid) and a['pinned_sha256']),None)
    if pin:row=c.execute('SELECT r.*,v.sha256,v.data,v.visual_review FROM recipes r JOIN recipe_revisions v ON v.recipe_id=r.id WHERE r.id=%s AND v.sha256=%s',(rid,pin)).fetchone()
    if row['state']=='archived':raise HTTPException(409,'Receita arquivada')
    if not usable(row):raise HTTPException(409,'A referência visual desta receita ainda aguarda revisão na Caixa de Revisão')
    return row


def require(c,cid,sha,spec):
    """Specs bound to a recipe must use an allowed, reviewed revision and respect its policy."""
    if not sha:return
    ready()
    row=c.execute('SELECT r.id,r.state,v.data,v.visual_review FROM recipe_revisions v JOIN recipes r ON r.id=v.recipe_id WHERE v.sha256=%s',(sha,)).fetchone()
    if not row:raise HTTPException(409,'Versão de receita indisponível')
    allowed=c.execute('SELECT recipe_id FROM channel_recipes WHERE channel_id=%s',(cid,)).fetchall()
    if allowed and not any(a['recipe_id']==row['id'] for a in allowed):raise HTTPException(409,'Receita não permitida neste canal')
    if not usable(row):raise HTTPException(409,'A referência visual desta receita ainda aguarda revisão')
    data=RecipeData.model_validate(row['data']);failures=[]
    if spec.music_style!=data.music.style_id:failures.append('Estilo musical diferente da receita')
    if spec.visual_variant!=data.visual.variant:failures.append('Variante visual diferente da receita')
    if data.visual.allowed_scenarios and spec.scenario not in data.visual.allowed_scenarios:failures.append('Cenário fora da receita')
    failures+=enforce(data.policy.model_dump() if data.policy else None,spec)
    if failures:raise HTTPException(422,'Roteiro fora da receita: '+' · '.join(failures))


class RecipeBody(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    data:RecipeData


class ReferenceReview(BaseModel):
    confirm_same_character:bool=False
    confirm_same_cat:bool=False
    confirm_framing:bool=False
    note:str=Field(default='',max_length=600)


class ChannelRecipe(BaseModel):
    recipe_id:uuid.UUID
    is_default:bool=False
    pinned_sha256:str|None=Field(default=None,pattern=SHA)


class ChannelRecipes(BaseModel):
    recipes:list[ChannelRecipe]=Field(min_length=1,max_length=30)


def validated(raw):
    try:return RecipeData.model_validate(raw)
    except ValueError as e:raise HTTPException(422,str(e).split('\n')[-1].split('[type=')[0].replace('Value error, ','').strip()) from None


@router.get('')
def list_recipes(include_archived:bool=False):
    ready()
    with db() as c:
        rows=c.execute('''SELECT r.*,v.sha256,v.data,v.visual_review FROM recipes r JOIN recipe_revisions v
          ON v.recipe_id=r.id AND v.revision=r.current_revision WHERE %s OR r.state<>'archived' ORDER BY r.origin<>'user',r.name''',(include_archived,)).fetchall()
    return {'recipes':[public(r) for r in rows]}


@router.get('/{rid}')
def get_recipe(rid:uuid.UUID):
    ready()
    with db() as c:
        row=current(c,rid)
        revisions=c.execute('SELECT revision,sha256,visual_review IS NOT NULL reviewed,created_at FROM recipe_revisions WHERE recipe_id=%s ORDER BY revision DESC',(rid,)).fetchall()
        channels=c.execute('SELECT channel_id,is_default FROM channel_recipes WHERE recipe_id=%s',(rid,)).fetchall()
    return {'recipe':public(row),'revisions':revisions,'channels':channels}


@router.post('')
def create_recipe(body:RecipeBody):
    ready();data=body.data
    with db() as c:
        slug=''.join(ch if ch.isalnum() else '-' for ch in body.name.lower()).strip('-')[:40] or 'receita'
        if c.execute('SELECT 1 FROM recipes WHERE slug=%s',(slug,)).fetchone():slug+='-'+uuid.uuid4().hex[:6]
        rid,sha=insert(c,slug,body.name.strip(),'user',data)
        audit(c,'RECIPE_CREATED',str(rid),sha);c.commit()
        row=current(c,rid)
    return {'recipe':public(row)}


@router.post('/{rid}/revisions')
def revise_recipe(rid:uuid.UUID,body:RecipeBody):
    ready();data=body.data;sha=digest(data)
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('recipe:'+str(rid),))
        row=current(c,rid)
        prior=c.execute('SELECT revision FROM recipe_revisions WHERE recipe_id=%s AND sha256=%s',(rid,sha)).fetchone()
        if prior:
            # Re-selecting an earlier revision makes it current again; approvals stay with its sha.
            c.execute('UPDATE recipes SET current_revision=%s,name=%s,updated_at=now() WHERE id=%s',(prior['revision'],body.name.strip(),rid))
            audit(c,'RECIPE_REVISION_RESTORED',str(rid),sha);c.commit()
            return {'recipe':public(current(c,rid)),'reused':True}
        if c.execute('SELECT 1 FROM recipe_revisions WHERE sha256=%s',(sha,)).fetchone():raise HTTPException(409,'Outra receita já tem exatamente esta versão; duplique-a em vez disso')
        revision=c.execute('SELECT max(revision)+1 n FROM recipe_revisions WHERE recipe_id=%s',(rid,)).fetchone()['n']
        c.execute('INSERT INTO recipe_revisions(recipe_id,revision,sha256,data) VALUES(%s,%s,%s,%s)',(rid,revision,sha,json.dumps(dump(data))))
        c.execute("UPDATE recipes SET current_revision=%s,name=%s,origin=CASE WHEN origin='builtin' THEN 'builtin_edited' ELSE origin END,updated_at=now() WHERE id=%s",(revision,body.name.strip(),rid))
        audit(c,'RECIPE_REVISED',str(rid),sha);c.commit()
        return {'recipe':public(current(c,rid)),'reused':False}


@router.post('/{rid}/archive')
def archive_recipe(rid:uuid.UUID):
    ready()
    with db() as c:
        current(c,rid)
        if c.execute('SELECT 1 FROM channel_recipes WHERE recipe_id=%s AND is_default',(rid,)).fetchone():raise HTTPException(409,'Troque a receita padrão dos canais antes de arquivar')
        c.execute("UPDATE recipes SET state='archived',updated_at=now() WHERE id=%s",(rid,))
        c.execute('DELETE FROM channel_recipes WHERE recipe_id=%s',(rid,))
        audit(c,'RECIPE_ARCHIVED',str(rid));c.commit()
    return {'archived':True}


@router.post('/{rid}/revisions/{revision}/approve-reference')
def approve_reference(rid:uuid.UUID,revision:int,body:ReferenceReview,request:Request):
    if not (body.confirm_same_character and body.confirm_same_cat and body.confirm_framing):
        raise HTTPException(422,'Confirme mesma garota, mesmo gato e mesmo enquadramento depois de comparar com o episódio aprovado')
    if len(body.note.strip())<12:raise HTTPException(422,'Descreva o que foi comparado (mínimo 12 caracteres)')
    ready()
    identity=getattr(request.state,'identity',None) or {}
    with db() as c:
        row=c.execute('SELECT sha256,data,visual_review FROM recipe_revisions WHERE recipe_id=%s AND revision=%s FOR UPDATE',(rid,revision)).fetchone()
        if not row:raise HTTPException(404,'Versão não encontrada')
        if row['data']['visual']['variant']=='canonical_illustrated':raise HTTPException(409,'A ilustração canônica já é a referência aprovada')
        if row['visual_review']:return {'visual_review':row['visual_review'],'reused':True}
        from .visual_identity import assert_usable
        for sha in row['data']['visual']['reference_asset_sha256']:assert_usable('',sha)
        review={'by':str(identity.get('user_id') or identity.get('email') or 'admin'),'note':body.note.strip(),'recipe_sha256':row['sha256'],
                'reference_pilot_ids':row['data']['visual']['reference_pilot_ids'],'reference_asset_sha256':row['data']['visual']['reference_asset_sha256'],
                'same_character':True,'same_cat':True,'framing':True}
        c.execute('UPDATE recipe_revisions SET visual_review=%s WHERE recipe_id=%s AND revision=%s',(json.dumps(review),rid,revision))
        audit(c,'RECIPE_REFERENCE_APPROVED',str(rid),row['sha256']);c.commit()
    return {'visual_review':review}


@router.post('/{rid}/preview-copy')
def preview_copy(rid:uuid.UUID,hours:int=1,idea:str='',scenario:str|None=None):
    ready()
    with db() as c:row=current(c,rid)
    data=RecipeData.model_validate(row['data'])
    return render_copy(data,scenario or data.visual.default_scenario,hours,idea[:500])


@channel_router.get('/{cid}/recipes')
def channel_recipes(cid:uuid.UUID):
    ready()
    with db() as c:
        profile(c,cid)
        rows=c.execute('''SELECT cr.recipe_id,cr.is_default,cr.pinned_sha256,cr.position,r.name,r.slug,r.state FROM channel_recipes cr
          JOIN recipes r ON r.id=cr.recipe_id WHERE cr.channel_id=%s ORDER BY cr.position,r.name''',(cid,)).fetchall()
    return {'recipes':rows}


@channel_router.put('/{cid}/recipes')
def set_channel_recipes(cid:uuid.UUID,body:ChannelRecipes):
    if sum(r.is_default for r in body.recipes)!=1:raise HTTPException(422,'Escolha exatamente uma receita padrão')
    if len({r.recipe_id for r in body.recipes})!=len(body.recipes):raise HTTPException(422,'Receita repetida')
    ready()
    with db() as c:
        profile(c,cid)
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('channel-recipes:'+str(cid),))
        for r in body.recipes:
            row=current(c,r.recipe_id)
            if row['state']=='archived':raise HTTPException(409,'Receita arquivada: '+row['name'])
            if r.pinned_sha256 and not c.execute('SELECT 1 FROM recipe_revisions WHERE recipe_id=%s AND sha256=%s',(r.recipe_id,r.pinned_sha256)).fetchone():
                raise HTTPException(422,'Versão fixada não pertence à receita')
        c.execute('DELETE FROM channel_recipes WHERE channel_id=%s',(cid,))
        for i,r in enumerate(body.recipes):
            c.execute('INSERT INTO channel_recipes(channel_id,recipe_id,pinned_sha256,is_default,position) VALUES(%s,%s,%s,%s,%s)',(cid,r.recipe_id,r.pinned_sha256,r.is_default,i))
        audit(c,'CHANNEL_RECIPES_SET',str(cid),','.join(str(r.recipe_id) for r in body.recipes));c.commit()
    return channel_recipes(cid)
