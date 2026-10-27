import json, sys, uuid
from pathlib import Path
ROOT=Path('/cache/fresh-hd-test-20261023');sys.path.insert(0,str(ROOT))
from studio.core import db
from studio import workshop_api as api
from studio.visual_workshop import Draft,Clip,Insertion
OLD=uuid.UUID('c813a7bd-d321-4eed-8d3d-a46221a37410')
PID=uuid.uuid5(OLD,'halloween-61min-plan-v1')
scene='''A mesma cafeteria aconchegante do projeto anterior, com a mesma garota e o mesmo gato, preservando rosto, cabelo, proporções, pelagem, mesa, notebook e enquadramento fixo. Noite chuvosa de Halloween; interior com iluminação âmbar baixa, sombras suaves, detalhes em cobre, lilás e verde-musgo. Ao fundo a cafeteria continua visível, decorada com pequenas abóboras de cerâmica iluminadas, um esqueleto simpático sentado numa cadeira com um livrinho, livros antigos, folhagem de outono, fios de luz âmbar e guirlanda de morcegos de papel. Pequenos fantasmas de tecido pendurados perto da janela. Decoração charmosa, artesanal, rica em textura, sem terror ou excesso visual. Janela com chuva, reflexos discretos e uma folha entreaberta pela qual o vapor mágico pode sair. A mesma garota usa um vestido de bruxinha em tecido realista preto ameixa, cardigan lilás e chapéu pontudo de feltro com fita de veludo, sem esconder o rosto nem os olhos. Mesmo gato malhado realista, com coleira confortável e pequeno pingente de abóbora sem luz piscante. Caneca sobre a mesa com café fumegante e um único pequeno emblema circular preto com as chaves e símbolo musical em ciano, violeta e magenta, sem texto adicional. A mesa mantém espaço livre para teclado e caneca. Nenhuma legenda, nome de personagem ou marca nova.'''
motion='''Câmera completamente fixa. A garota digita com o mesmo ritmo e a mesma postura natural do teste anterior, satisfeita com sorriso muito discreto de lábios fechados, nunca mostrando dentes. Respiração, piscadas e mãos naturais. O gato acompanha com pequenos movimentos dos olhos e orelhas o balanço lento da guirlanda e dos fantasminhas; permanece sentado no mesmo lugar. Vapor suave e contínuo na caneca, chuva no vidro, luz estável e tecidos levemente balançando. Sem sustos nem aparições na base. Todos os movimentos da base são periódicos, com estados e velocidades compatíveis na junção. O gato retorna suavemente ao olhar inicial; a digitação nunca congela.'''
join='''Entrada e saída devem acompanhar o estado e a fase exatos do vídeo base no instante agendado, com primeiro e último segundo compatíveis com a base. Voltar à postura de digitação, posição da caneca e posição original do gato. Preservar câmera, identidade, roupa, iluminação e geometria. Manter chuva, respiração e decorações em movimento durante toda a ação; não congelar nem inverter a ação. Sorriso sempre de lábios fechados, sem dentes. Sem legendas, sem texto novo, sem diálogo e sem vocalização audível. O harness deve preparar interpolação cíclica e pontes móveis nas duas junções, preservando os horários absolutos e a duração final.'''
ghost='''0–1s: entrada em continuidade com a base. 1–3s: a fumacinha do café se enrola e forma um pequeno fantasminha translúcido simpático, feito somente de vapor. 3–5s: ele flutua numa curva delicada acima da mesa e sai pela folha entreaberta da janela; o gato acompanha o percurso com olhos e cabeça, sem sair do lugar. 5–7s: o vapor se dissipa lá fora, o gato retorna ao olhar original e a garota continua digitando satisfeita. 7–8s: retorno exato à base, a caneca permanece sobre a mesa soltando vapor normal. Não criar outro gato ou mover a caneca. '''+join
kid='''0–1s: entrada em continuidade. 1–2s: aparece do lado de fora da janela somente a cabeça de um menino com fantasia infantil de abóbora, rosto simpático dentro do capuz laranja; corpo e mãos ficam totalmente fora do enquadramento. Sem invadir a cafeteria. 2–4s: a garota olha para a janela levemente surpresa, sobrancelhas discretamente erguidas, mantendo sorriso pequeno com lábios fechados e sem dentes. O gato também olha e faz um único miado visual silencioso. 4–5s: ela balança a cabeça suavemente de um lado para outro, divertida; a cabeça do menino se abaixa e desaparece por completo. 5–7s: ela volta à posição original e retoma a digitação; o gato fecha a boca e retorna à pose inicial. 7–8s: continuidade com a base. Expressões sutis, sem susto exagerado, sem fala ou riso. '''+join
bat='''0–1s: continuidade da base. 1–3s: um pequeno morcego de papel da guirlanda se solta magicamente e dá uma volta lenta acima do notebook, com aparência artesanal e sem parecer um animal real. 3–5s: ele paira perto do gato; o gato toca delicadamente o morceguinho com uma pata, enquanto a garota percebe e oferece um dedo para ele pousar, sorrindo somente de lábios fechados. 5–6s: ela indica a guirlanda com o dedo e o morcego voa de volta para seu lugar original. 6–7s: ela recoloca ambas as mãos no teclado e retoma a digitação; o gato recolhe a pata e volta à pose inicial. 7–8s: alinhamento exato com a base; a guirlanda volta ao balanço habitual. Nenhum objeto extra permanece sobre a mesa. '''+join
with db() as c:
 if c.execute('SELECT id FROM visual_projects WHERE id=%s',(PID,)).fetchone():
  print(json.dumps({'project_id':str(PID),'already_exists':True}));sys.exit()
 row=api.project(c,OLD);d=Draft.model_validate(row['data']).model_copy(deep=True);media=api.assets(c,OLD)
 # Copy only identity/reference assets. No video, no previous approved scenery.
 keep={k:a for k,a in media.items() if a['kind']=='reference'}
 mapping={k:str(uuid.uuid5(PID,k)) for k in keep}
 for ch in d.characters:
  ch.references=[uuid.UUID(mapping[str(r)]) for r in ch.references if str(r) in mapping]
  if 'gato' in ch.name.lower():ch.description+=' Neste projeto: mesma identidade e pelagem; coleira delicada com pequeno pingente de abóbora.'
  else:ch.description+=' Neste projeto: preservar rigorosamente identidade, rosto e cabelo; fantasia de bruxinha com chapéu de feltro e cardigan lilás. Sorriso discreto, lábios fechados, sem dentes.'
 d.name='Halloween na cafeteria — plano de teste 61 min'
 d.minutes=61;d.theme='Halloween acolhedor e divertido — Lo-fi Jazzhop, Full HD nativo'
 d.scene=scene;d.scene_motion=motion
 d.scene_references=[uuid.UUID(mapping[str(r)]) for r in d.scene_references if str(r) in mapping]
 d.base=Clip(id=uuid.uuid5(PID,'base'),name='Bruxinha digitando — base Halloween',motion=motion+' '+join,seconds=8)
 d.clips=[Clip(id=uuid.uuid5(PID,key),name=name,motion=m,action_goal=goal,seconds=8) for key,name,m,goal in [
  ('ghost','Fantasminha do café',ghost,'Vapor forma fantasma, sai pela janela e gato acompanha.'),
  ('kid','Visitante abóbora na janela',kid,'Somente cabeça do menino; surpresa suave, miado silencioso e retorno.'),
  ('bat','Morceguinho de papel brincalhão',bat,'Gato toca morcego mágico de papel, garota participa e ele volta à guirlanda.')]]
 d.insertions=[]
 for cl,times in zip(d.clips,[[28/60,28,56],[5,20,45,60],[3,15,40]]):
  for minute in times:d.insertions.append(Insertion(id=uuid.uuid5(PID,f'{cl.id}:{minute}'),clip_id=cl.id,minute=minute))
 d.music_program_id='CAFE4H-20261013'
 raw=d.model_dump(mode='json',exclude={'automatic_motion'})
 Draft.model_validate(raw)
 c.execute('INSERT INTO visual_projects(id,channel_id,data) VALUES(%s,%s,%s)',(PID,row['channel_id'],json.dumps(raw)))
 for aid,a in keep.items():
  data={k:v for k,v in a.items() if k not in ('id','url')}
  c.execute('INSERT INTO visual_media(id,project_id,data) VALUES(%s,%s,%s)',(uuid.UUID(mapping[aid]),PID,json.dumps(data)))
 c.commit()
 plan={'project_id':str(PID),'minutes':61,'resolution':'1080p native; final 1920x1080 at 24fps','encoding':{'crf':15,'preset':'medium','cpu_limit':2},'paid_generation_started':False,'scenario_approved':False,'draft':raw}
 (ROOT/'halloween-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
 print(json.dumps({'project_id':str(PID),'insertions':len(d.insertions),'minutes':d.minutes,'paid_generation_started':False}))
