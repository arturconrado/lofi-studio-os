"""Per-video growth diagnosis against the channel's own comparable videos.

Each diagnosis names a target, the bottleneck, the evidence (or that it is a hypothesis), a
concrete action, a confidence with its reason, the effort/cost class and how to evaluate the
change afterwards. Comparisons use only the same format and window; missing metrics stay
unknown and limit confidence instead of being inferred. External popularity and traffic-source
guesses (for example views minus impressions × CTR) are never used.
"""
import json,statistics,uuid
from collections import defaultdict
from fastapi import APIRouter
from .core import db
from .channels import profile

router=APIRouter(prefix='/api/growth')
MIN_COMPARABLES=3
MIN_IMPRESSIONS=100
CAUTION=('Diagnósticos comparam o vídeo com vídeos próprios do mesmo formato e janela. São hipóteses de trabalho: '
         'não garantem alcance, posição na busca nem crescimento, e amostras pequenas limitam a confiança.')


def _metrics(row):
    m=row.get('metrics') or {}
    return json.loads(m) if isinstance(m,str) else m


def latest_per_video(rows,window='28d'):
    out={}
    for row in sorted(rows,key=lambda r:(str(r.get('observed_date')),str(r.get('created_at') or '')),reverse=True):
        if row.get('window')!=window or not row.get('video_url'):continue
        out.setdefault((row['video_url'],row.get('content_format','long_form')),row)
    return list(out.values())


def quartiles(values):
    values=sorted(v for v in values if v is not None)
    if len(values)<MIN_COMPARABLES:return None
    q=statistics.quantiles(values,n=4,method='inclusive')
    return {'p25':q[0],'median':statistics.median(values),'p75':q[2],'n':len(values)}


def retention(m):
    """Early retention read in Studio; average view duration only as a same-format fallback."""
    if m.get('retention_15_percent') is not None:return m['retention_15_percent'],'retenção no minuto 15 (%)'
    if m.get('average_view_duration_seconds') is not None:return m['average_view_duration_seconds'],'duração média (s)'
    return None,None


def confidence(n,impressions):
    if n>=8 and (impressions or 0)>=1000:return 'média','amostra interna de {} vídeos e {} impressões'.format(n,impressions)
    return 'baixa','amostra interna de {} vídeos{}'.format(n,'' if impressions is None else f' e {impressions} impressões')


def diagnose(rows,window='28d'):
    latest=latest_per_video(rows,window)
    by_format=defaultdict(list)
    for row in latest:by_format[row.get('content_format','long_form')].append(row)
    out=[]
    for fmt,group in by_format.items():
        ms=[(r,_metrics(r)) for r in group]
        ctr=quartiles([m.get('ctr_percent') for _,m in ms if (m.get('impressions') or 0)>=MIN_IMPRESSIONS])
        imp=quartiles([m.get('impressions') for _,m in ms])
        ret_values=defaultdict(list)
        for _,m in ms:
            value,label=retention(m)
            if value is not None:ret_values[label].append(value)
        ret={label:quartiles(values) for label,values in ret_values.items()}
        for row,m in ms:
            target={'video_url':row['video_url'],'title':m.get('video_title') or row['video_url'],'format':fmt,'window':window,
                    'observed_date':str(row.get('observed_date'))}
            missing=[k for k in ('impressions','ctr_percent','retention_15_percent','returning_viewers') if m.get(k) is None]
            found=[]
            value,label=retention(m);r_q=ret.get(label) if label else None
            impressions=m.get('impressions');ctr_value=m.get('ctr_percent')
            if ctr and impressions is not None and impressions>=MIN_IMPRESSIONS and ctr_value is not None and ctr_value<ctr['p25']:
                level,why=confidence(ctr['n'],impressions)
                found.append({'bottleneck':'ctr','label':'Muitas impressões e CTR baixo perante vídeos próprios','basis':'observed',
                    'evidence':f"{impressions} impressões e CTR {ctr_value:g}% abaixo do quartil inferior interno ({ctr['p25']:.1f}%, {ctr['n']} vídeos).",
                    'action':'Teste uma variável por vez: título ou miniatura, mantendo a promessa fiel ao conteúdo. Considere a origem do tráfego antes de concluir.',
                    'confidence':level,'confidence_reason':why,'effort':'baixo; sem custo de geração se a miniatura vier da arte aprovada',
                    'evaluation':'Compare CTR por origem do tráfego na mesma janela depois da mudança, com impressões comparáveis.'})
            if ctr and r_q and ctr_value is not None and ctr_value>=ctr['median'] and value<r_q['p25']:
                level,why=confidence(min(ctr['n'],r_q['n']),impressions)
                found.append({'bottleneck':'retention_after_click','label':'Clique forte e pouca permanência','basis':'observed',
                    'evidence':f"CTR {ctr_value:g}% acima da mediana interna e {label} {value:g} abaixo do quartil inferior ({r_q['p25']:.1f}).",
                    'action':'Confira se a abertura entrega a promessa do título e da miniatura (revisão da abertura). Não aumente a promessa.',
                    'confidence':level,'confidence_reason':why,'effort':'médio; pode exigir nova montagem da abertura',
                    'evaluation':f'Acompanhe {label} em vídeos novos da mesma série e janela; não compare com outros formatos.'})
            if imp and r_q and impressions is not None and impressions<imp['p25'] and value is not None and value>=r_q['median']:
                level,why=confidence(min(imp['n'],r_q['n']),impressions)
                found.append({'bottleneck':'reach','label':'Poucas impressões e boa permanência','basis':'hypothesis',
                    'evidence':f"{impressions} impressões abaixo do quartil inferior interno ({imp['p25']:.0f}) com {label} {value:g} acima da mediana.",
                    'action':'Investigue adequação do tema ao público, interesse e concorrência antes de mexer em metadados; não troque metadados automaticamente.',
                    'confidence':'baixa','confidence_reason':why+'; impressões dependem de fatores fora do vídeo','effort':'médio (pesquisa e pauta)',
                    'evaluation':'Compare impressões de um próximo vídeo com tema ajustado na mesma janela e formato.'})
            terms=m.get('search_terms') or []
            title=str(m.get('video_title') or '')
            if terms and title:
                from .channel_audit import phrase_covered
                uncovered=[t for t in terms if not phrase_covered(t,title)]
                if len(uncovered)==len(terms):
                    found.append({'bottleneck':'search_alignment','label':'Termos de busca observados não aparecem no título','basis':'hypothesis',
                        'evidence':'Termos do Studio: '+', '.join(terms[:5])+'. Nenhum aparece no título atual.',
                        'action':'Se o vídeo realmente atende a esses termos, deixe isso claro no título ou na primeira linha, uma vez e sem repetir palavras-chave.',
                        'confidence':'baixa','confidence_reason':'termos observados não medem volume de busca','effort':'baixo (texto)',
                        'evaluation':'Na mesma janela, compare a participação de Pesquisa do YouTube e os termos registrados.'})
            returning=m.get('returning_viewers');views=m.get('views')
            if returning is not None and views and returning/views<.02:
                found.append({'bottleneck':'continuity','label':'Consumo sem retorno','basis':'hypothesis',
                    'evidence':f'{returning} espectadores recorrentes para {views} visualizações.',
                    'action':'Avalie série reconhecível, playlist do uso principal e tela final apontando para o próximo episódio.',
                    'confidence':'baixa','confidence_reason':'recorrentes por vídeo são pequenos e variam com a idade do vídeo','effort':'baixo (playlists e telas finais)',
                    'evaluation':'Compare espectadores recorrentes e inscritos por mil visualizações na mesma janela.'})
            if not found:
                found.append({'bottleneck':'insufficient_evidence','label':'Evidência insuficiente para diagnosticar','basis':'limitation',
                    'evidence':('Faltam: '+', '.join(missing)+'.') if missing else 'Métricas dentro da faixa interna; sem gargalo destacado.',
                    'action':'Registre as métricas que faltam em Métricas por vídeo, na mesma janela.' if missing else 'Mantenha o acompanhamento; nenhuma mudança é recomendada pelos dados atuais.',
                    'confidence':'—','confidence_reason':'sem base comparável suficiente' if missing else 'sem desvio interno','effort':'baixo',
                    'evaluation':'Nova captura na mesma janela.'})
            out.append({'target':target,'diagnoses':found,'missing_metrics':missing,
                        'comparables':{'ctr':ctr,'impressions':imp,'retention':ret}})
    return out


@router.get('/{cid}/diagnostics')
def diagnostics(cid:uuid.UUID,window:str='28d'):
    with db() as c:
        profile(c,cid)
        rows=c.execute('''SELECT video_url,observed_date,"window",content_format,metrics,created_at FROM analytics_snapshots
                          WHERE channel_id=%s ORDER BY observed_date DESC,created_at DESC LIMIT 2000''',(cid,)).fetchall()
    return {'videos':diagnose(rows,window),'window':window,'source':'manual_youtube_studio','interpretation_note':CAUTION}
