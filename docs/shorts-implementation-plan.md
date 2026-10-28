# Plano de integração de Shorts narrativos

**Estado:** implementação do piloto em `feat/narrative-shorts`; Short ainda não renderizado nem publicado. Nenhuma migração de tabela é necessária: a entrega deriva do `visual_media` existente e do job `factory_tasks`.
**Base examinada:** `origin/main` (`ed85886`) e a produção anteriormente confirmada nessa mesma imagem.
**Referência de produto:** SDD Lo-Fi Studio v1.0, seção 8/G5 e pacote WP-08.
**Princípio do canal:** usar YouTube Studio para evidência e comparação; não depender de vidIQ. Ver `docs/youtube-growth-playbook.md` e o playbook específico do canal no projeto lo-fi-project.

## Objetivo

Criar Shorts que funcionem como pequenas histórias de foco e conduzam, quando fizer sentido, a um vídeo longo específico do Lo-Fi Vibe Coding. Reutilizar os movimentos e materiais realmente existentes, preservar o áudio original e a identidade visual, e submeter cada entrega a uma revisão própria antes de ela entrar na Biblioteca ou seguir para publicação.

O primeiro marco é um Short narrativo derivado de acervo compatível. Só depois de fechar esse fluxo serão produzidas duas histórias distintas. O número e a cadência da campanha ficam para uma etapa posterior.

## Estado real do código

| Área existente | O que já faz | Limite para Shorts |
|---|---|---|
| Visual Workshop — `studio/visual_workshop.py`, `studio/workshop_api.py`, `studio/workshop_worker.py` | Guarda projetos e mídia imutável, organiza base e ações com tempos/continuações, usa o compositor local, valida emendas, vincula música aprovada e preserva jobs retomáveis. Jobs usam `factory_tasks` (`visual_workshop_v1`). | A proposta é uma linha do tempo de longa duração: `Draft.minutes` começa em 1 minuto, posições usam minutos e não há roteiro por história, faixa de legenda nem perfil 9:16. O prompt de vídeo proíbe texto e legendas no material gerado, portanto o texto deve continuar sendo composição posterior controlada. |
| Compositor compartilhado — `studio/timeline_compositor.py` e `studio/workshop_continuity.py` | Renderiza os clipes aprovados e mantém uma única faixa de áudio. Recebe largura, altura e FPS. A continuidade protege o movimento original. | `workshop_worker.render_segments()` fixa a saída em 1280×720 ou 1920×1080. Apenas passar 1080×1920 não basta: a normalização atual reduz e preenche o quadro. Faltam enquadramento vertical com área segura e composição de fundo desfocado sincronizado. |
| Montagem avançada — `studio/production_harness.py`, `studio/timeline_api.py`, `studio/timeline_preview.py` | Compila agenda absoluta, verifica materiais e hashes, monta trechos reais e exige aprovação humana do episódio completo. | Seu estado e gates representam episódios longos. Não reduzir duração ou ignorar ações obrigatórias para transformar um episódio aprovado em Short. A derivação precisa ter seu próprio roteiro, arquivo e aprovação. |
| Revisão — `studio/inbox.py` e `frontend/src/features/inbox.tsx` | Reúne decisões humanas de faixas, clipes, pilotos e montagens avançadas. | O render final do Visual Workshop hoje é aprovado na própria página de edição; não há tipo de revisão de Short na Caixa de Revisão. Aprovar um longo não pode aprovar automaticamente seu derivado. |
| Biblioteca — `frontend/src/features/library.tsx` e `studio/productions.py` | Mostra produções, exports legados e publicações do YouTube. | Projetos/renders do Visual Workshop não aparecem como entregas publicáveis da Biblioteca. É preciso encaminhar o artefato Short aprovado ao fluxo existente, sem criar uma segunda biblioteca. |
| Exportação — `studio/exports.py`, `studio/video_export.py` | Cria exportações idempotentes de 1h e protege o fluxo dos programas longos. A mídia temporária pode ser purgada após confirmação de upload; o endpoint então retorna 410. | `export_jobs.seconds` é deliberadamente limitado a 3600/14400/28800 e `/api/exports` não é um exportador de Shorts. Manter essas restrições; o Short deve ser uma entrega derivada identificada, não um `export_job` com duração curta. Reutilizar as fontes originais por hash/objeto, não depender do MP4 longo purgado. |
| Publicação — `studio/youtube_publish.py` | Usa envio resumível, Growth nativo, checagem de direitos, aprovação, duplicidade e autorização explícita. | O modelo associa uma publicação a `export_id` ou `pilot_id`; a rota de export exige programa longo revisado. Falta associar com segurança o artefato Short e validar seu hash, canal, versão, direitos e aprovação. Não contornar o gate de vídeo longo para encaixar Shorts. |
| Growth — `studio/growth.py` | Já aceita `content_format='short'` em snapshots, referências, contexto, embalagem e projeções históricas. Analytics é inserido manualmente a partir do YouTube Studio. | O snapshot não tem campos próprios para “mostrado no feed”, “escolheu assistir/continuou”, views engajadas e percentual médio visto. A publicação ainda não guarda `content_format` para separar o histórico de Shorts e longos de ponta a ponta. |

### Consequência de integração

Reaproveitar a fonte de jobs e o compositor locais, estendendo os componentes existentes. A proposta de Short deve ser filha/versionada do conteúdo longo que promove, usar os objetos originais já armazenados e produzir um novo arquivo com hash próprio. Não usar `export_jobs` como registro do Short, não criar uma segunda tela de revisão/biblioteca e não alterar ou substituir o longo.

Na descoberta WP-00, confirmar como vincular o derivado ao projeto, ao job de montagem e à publicação sem duplicar autoridade. Só então escolher os campos/migração necessários em `visual_projects`/`visual_media`, `factory_tasks` e `youtube_publications`. O SDD orienta a extensão de estruturas existentes quando elas servirem ao contrato; nomes e migrações físicas não devem ser presumidos antes desse mapeamento.

### Decisão de integração após inspeção do código

O inventário confirmou que o banco já aceita `visual_media.data` como JSON e que `factory_tasks` já identifica o projeto e guarda o recibo do render. O piloto usa esses contratos: um job `visual_workshop_v1` com operação `short_render`, um asset `visual_media` com `kind=short` e um hash novo. Não criar tabela nem alterar migração para o piloto. A relação com o vídeo longo fica explícita no payload do job e no asset por `parent_video_id`; a fonte do longo é comprovada pelo `youtube_publications` + `ambient_pilots` aprovado, pelo recibo do render e pelos objetos originais. O fluxo é separado da publicação para que a entrega atual termine em revisão humana.

O código do piloto estende o Visual Workshop, o worker FFmpeg local e a Caixa de Revisão existente. O vídeo final do Workshop permanece intacto; o Short usa novamente os objetos fonte e a trilha do mesmo projeto, com hash verificado. A aprovação do Short fica vinculada ao hash exato. Não há chamada de geração paga.

## Objetivos executáveis e ordem de trabalho

| Objetivo | Ações concretas | Saída verificável | Estado |
|---|---|---|---|
| O0 — Preservar e provar a origem | Ler o projeto, o job completo aprovado, a publicação, o pilot e os hashes dos arquivos originais; confirmar que os arquivos existem no object storage. | Relação fonte → instante → publicação, sem depender do MP4 longo temporário. | Inventário feito para o piloto Rainy Night Café; API implementa os gates, ainda falta executar em produção. |
| O1 — Escolher uma história existente | Usar a base curta imediatamente anterior à ação, os dois trechos contínuos da pausa com o gato e a trilha original. Cortes de 8 s + 8 s + 8 s; abertura, virada e resolução. | Arco de 24 s, sem trecho inventado, sem ação contínua interrompida e sem música substituta. | História e cópia rascunhadas; revisão humana pendente. |
| O2 — Gerar sem danificar o longo | Criar `ShortSpec` versionado; validar origem, hashes, agenda, duração e trilha; compor canvas 9:16 com o mesmo quadro ao fundo desfocado e quadro inteiro à frente; colocar legendas temporizadas depois do vídeo. | MP4 novo, 1080×1920, duração igual à história, decodificação integral e recibo com hashes. | Código implementado; testes locais do render pendentes. |
| O3 — Revisar no fluxo da plataforma | Criar um item `workshop_short_review` na Caixa de Revisão; reproduzir o vídeo, mostrar título/descrição/cópia/legendas e exigir confirmações humanas separadas. Gravar decisão no job e no asset, ligada ao hash. | Aprovação ou devolução com nota, sem propagar decisão ao longo ou a outros Shorts. | Código implementado; integração de interface e rejeição em validação. |
| O4 — Colocar em produção pelo caminho normal | Consolidar correções, abrir PR, aguardar CI, mergear na `main`; usar o deploy automático existente; verificar imagem, saúde e rota no ambiente publicado. | Versão publicada a partir da `main`, com health check e sem alteração manual na VPS. | Pendente. |
| O5 — Criar e avaliar o piloto na plataforma | Entrar no projeto do piloto, enviar o `ShortSpec`, esperar worker, assistir o arquivo na Caixa de Revisão e ajustar até ficar pronto para avaliação. | Short pronto e acessível na plataforma, sem envio ao YouTube. | Bloqueado até o deploy e uma sessão autenticada no portal Lo-Fi Studio. |
| O6 — Completar etapas posteriores só com decisão e evidência | Depois do piloto, planejar integração com Biblioteca/Publicação e métricas do Studio como pacotes próprios; preservar confirmação de publicação e métricas nativas. | Contrato explícito para o derivado aprovado, relacionado, publicado e comparado por coorte Short. | Não implementado no escopo de deixar este piloto pronto para revisão. |

**Critério de encerramento do trabalho atual:** o O5 termina com o MP4 aberto e revisável na plataforma, ligado ao vídeo longo correto. Isso não equivale a aprovação editorial nem a publicação no YouTube.

## Objetivos e entregas

### O1 — Encontrar material que sustente uma história

Inventariar os vídeos longos e fontes realmente disponíveis no canal: clipes aprovados, cena/base, áudio aprovado, proveniência, direitos, hashes, intervalos e estado de publicação do longo. Para cada candidato, registrar o que existe, o que precisa ser planejado e o que falta. MP4 longo já purgado não será tratado como fonte; localizar os assets originais correspondentes.

**Entrega:** inventário de candidatos e indicação do primeiro longo, apoiada por fontes/intervalos verificáveis. Sem geração paga nesta etapa.

### O2 — Criar um contrato editorial próprio para cada Short

Representar no projeto existente uma versão de entrega Short que registre:

- intenção, público e vídeo longo de referência;
- cena/personagens e hashes dos materiais usados;
- intervalos exatos, ordem dos cortes e papel de cada trecho;
- abertura, acontecimento e desfecho/expectativa — todos compreensíveis sem o longo;
- perfil de destino, estratégia de quadro, duração escolhida pela história;
- direção sonora, texto/legenda temporizados, desfecho e convite para continuar;
- custo/proveniência, versão dos inputs, estado e hash do arquivo final.

Fontes viram intervalos exatos apenas depois de o material ser encontrado. Uma ação incompleta não pode ser apresentada como cliffhanger. Cada peça deve funcionar sozinha e ter uma história distinta das demais.

### O3 — Reutilizar o mesmo movimento e montar um vertical legível

Usar primeiro os movimentos aprovados do Visual Workshop ou da montagem avançada que correspondam à cena e ao longo selecionado. Estender o pipeline local para compor um derivado em perfil 9:16 consultado no perfil vigente do destino:

1. propor recorte/re-enquadramento que preserve os elementos e trajetórias essenciais;
2. quando o recorte cortar personagem, rosto, mãos, gato ou objeto narrativo, permitir composição da cena inteira sobre uma cópia desfocada do mesmo quadro;
3. compor o fundo a partir do mesmo instante, com uma única trilha de áudio;
4. adicionar legenda como camada editorial local, com texto, início/fim e posição revisáveis — nunca pedir ao gerador de imagem/vídeo que escreva texto;
5. manter o material fonte imutável; alterar roteiro, movimento, quadro, som ou texto cria nova versão do Short e invalida a revisão do artefato anterior.

Não fixar a duração em 15–25 s. O harness propõe a duração a partir dos acontecimentos; o perfil atual do destino valida os limites. Na primeira peça, preferir música instrumental do próprio programa, editada como mix separado e com fade/corte intencional. Voz fica opcional e não é padrão do canal.

### O4 — Levar a entrega pelas mesmas etapas humanas do produto

Encaminhar o render concluído à Caixa de Revisão existente com prévia vertical, áudio e evidências. A revisão individual deve confirmar história completa, identidade/estilo, quadro seguro, movimento, legibilidade das legendas, áudio, direitos e correspondência com o longo. Aprovação precisa apontar para o hash exato.

Depois de aprovado, mostrar o Short na Biblioteca existente como derivado do longo, com seu estado próprio. A aprovação do longo não se herda; reprovação/edição de uma peça não altera outras entregas.

### O5 — Publicar e medir sem misturar formatos

Usar o fluxo nativo de Growth em `content_format='short'`, guardar esse formato no registro de publicação e preservar as validações de título/descrição, direitos, canal, versão, duplicidade e consentimento. O endpoint deve enviar exatamente os bytes aprovados, em upload resumível, sem usar o gate de duração de 1h para autorizar o Short.

Após o upload, associar no YouTube Studio o longo correspondente em **Related video**, se o acesso a Recursos avançados permitir. Até existir integração oficial verificável, essa associação é uma etapa manual registrada; não afirmar que URLs em descrição/comentário são um link clicável no feed.

Registrar no Growth, a partir do YouTube Studio, formato, vídeo, idade, janela e quando disponíveis: shown in feed, stayed to watch / chose to view, engaged views, média e percentual assistidos, likes, comentários, inscritos e continuação pelo relacionado. Dados indisponíveis ficam vazios. Comparar Shorts por idade/duração semelhantes; não comparar CTR/retention de Short com vídeo longo como a mesma métrica.

### O6 — Só então escalar para campanha

Depois de o piloto atravessar criação → render → Revisão → Biblioteca → publicação autorizada → Analytics, produzir mais duas histórias realmente diferentes. Só ampliar frequência/calendário depois de ver suficiência de fontes, resposta no Studio e custo operacional. Convites “em breve”/“já disponível” têm de corresponder ao estado real do vídeo longo; mudança de estreia invalida ou revalida apenas as entregas afetadas.

## Ações por pacote

| Pacote | Ação | Componentes do código | Saída / condição de conclusão |
|---|---|---|---|
| S0 — Descoberta WP-00 | Inventariar fluxo implantado, assets por canal/hash, jobs, origens, direitos, rendições purgadas e estados de aprovação. Comparar arquivos de código com a versão-alvo antes de migrar. | `studio/core.py`, `studio/creator.py`, `studio/productions.py`, `studio/workshop_api.py`, `studio/timeline_api.py`, `studio/youtube_publish.py` | Mapa fonte → trecho → áudio → longo → publicação; um candidato utilizável; lacunas explícitas. Nenhuma geração/publicação real. |
| S1 — Especificação/roteiro | Definir o `ShortSpec` como versão do projeto existente; registrar intenção e arco narrativo, fontes e estados. Harness propõe alternativas só quando acervo não sustenta a história. | `studio/visual_workshop.py`, `studio/production_harness.py`, `studio/growth.py` | Um roteiro com começo/acontecimento/desfecho e intervalos reais; ausência de fonte impede render final. |
| S2 — Perfil 9:16/legenda | Estender o montador existente com layout selecionável, recorte/focal point ou fundo sincronizado, áreas seguras e overlays de legenda. | `studio/workshop_worker.py`, `studio/timeline_compositor.py`, `studio/workshop_continuity.py`, `frontend/src/features/workshop.tsx` | Render vertical não deforma nem perde elementos essenciais; legenda é temporizada e legível; áudio não duplica; Longo continua idêntico. |
| S3 — Som e validação | Adicionar direção de som própria ao derivado, com fonte, mix/nível, fade, versão e QC. Validar duração, stream único, decode completo e sync entre imagem/legenda/som; requer inspeção humana integral. | `studio/workshop_api.py`, `studio/workshop_worker.py`, `studio/timeline_compositor.py` | Artefato com hash, recibo e inspeção técnica/humana pendente de aprovação. Sem nova trilha paga por padrão. |
| S4 — Revisão/Biblioteca | Exibir o Short na Caixa de Revisão e encaminhar só os hashes aprovados à Biblioteca como derivados independentes. Preservar os estados atuais dos longos. | `studio/inbox.py`, `frontend/src/features/inbox.tsx`, `frontend/src/features/library.tsx`, `studio/productions.py` | Rejeição/aprovação registrada por artefato e canal; hash em Revisão igual ao disponibilizado na Biblioteca. |
| S5 — Publicação | Estender a origem tipada de `youtube_publications` para o artefato Short; reaproveitar transporte resumível, idempotência, direitos e Growth. Preservar exatamente o gate dos exports longos e pilotos. | `studio/youtube_publish.py`, `studio/provenance.py`, `frontend/src/features/library.tsx` | Envio exige autorização de publicação separada; upload corresponde aos bytes aprovados; Related video associado/registrado depois no Studio. |
| S6 — Medição | Persistir métricas próprias de Shorts e mostrar comparação por coorte/idade. Usar dados inseridos do YouTube Studio, sem promessa de alcance. | `studio/growth.py`, `frontend/src/features/diagnostics.tsx` ou tela Growth integrada já existente | Captura reproduzível com fonte, data, janela, idade, amostra e lacunas; decisão explícita de repetir/ajustar/parar. |
| S7 — Campanha | Habilitar sequência, quantidade, frequência, estreia e calendário relativo no fuso do canal. | `studio/episode_api.py`, `studio/youtube_publish.py`, `frontend/src/features/library.tsx` | Só iniciar depois de S0–S6; alteração de estreia mostra impacto e não muda envio autorizado silenciosamente. |

## História escolhida para o piloto

O piloto é o longo publicado **Rainy Night Café**, YouTube `8WPZo1LrRbc`, do projeto “Teste 62 min Full HD - novos clipes - boca fechada”. O projeto retém os assets originais mesmo que o MP4 final de 62 minutos tenha sido purgado. Os dois clipes contínuos “Pausa para acariciar o gato” e “Pausa para acariciar o gato — parte 2” são comprovados no render aprovado aos 55:00–55:08 e 55:08–55:16. A abertura proposta usa os 8 segundos da base imediatamente anteriores (54:52–55:00); a trilha começa no mesmo ponto 54:52. O worker deve provar isso novamente com os dados atuais e hashes antes de enfileirar.

Arco: **“One more line of code…” → “The sleepiest coworker needed a break.” → “A little kindness later…” → “Back to the next line. Settle into the full session.”** A última frase só segue se o vínculo ao longo continuar válido. O rascunho do título é “Rainy Café Coding Focus | A Break with the Sleepiest Cat”; a descrição inicia “Rainy café coding focus…” e aponta para o longo. A interface mantém título, descrição e legendas editáveis. O usuário deve ouvir/verificar a música e confirmar que cafeteria, chuva e a cena correspondem ao vídeo real antes de aprovar a redação; isso ainda é revisão, não metadado aplicado ao canal.

Texto no quadro: poucas frases curtas, uma ideia por trecho, início/fim sincronizados ao movimento e CTA final dentro da área segura. Não usar claim de sono, efeito clínico, timer, chuva audível ou “assista agora” sem correspondência factual.

## Gates de qualidade e aceitação

1. **Fonte:** cada intervalo, movimento e trilha tem origem, canal, hash, direitos e ligação ao vídeo longo demonstráveis. Assets preservados; um MP4 final purgado é refeito a partir das fontes originais.
2. **História:** abre, acontece e conclui; entende-se sem o longo. Não esconde erro/truncamento como gancho.
3. **Quadro:** revisar em resolução final 9:16; nenhum elemento essencial sai da tela; fundo desfocado é o mesmo instante; tipografia não invade interface/rosto.
4. **Som:** uma trilha audível, mix do Short independente; origem e direitos preservados; inspeção de início/fim e sincronização.
5. **Arquivo:** duração e dimensões conferem com perfil vigente, vídeo/áudio decodificam integralmente, hash imutável ligado às entradas e versão.
6. **Fluxo:** artefato completo chega à Revisão; aprovação individual não promove campanha inteira; somente hash aprovado chega à Biblioteca e publicação.
7. **Medição:** captura do YouTube Studio separada por formato e idade; dados faltantes permanecem faltantes; uma variável editorial por experimento.

Os cenários do SDD a cobrir na implementação são TEST-18 (história/fontes), TEST-19 (recorte/fundo sincronizado), TEST-20 (duração/perfil/calendário), TEST-38 (som/aprovações por entrega) e TEST-39 (falha incompleta). Estes são critérios planejados, não testes executados nesta etapa.

## Fora do primeiro marco

- Campanha fixa de sete Shorts ou calendário D−7/D−1.
- Geração paga de novas cenas antes de esgotar o inventário de material compatível.
- Publicação, agendamento ou aprovação automática.
- Alterar/excluir qualquer vídeo longo ou asset já existente.
- Criar uma segunda biblioteca, revisão ou rota de export que duplique a atual.
- Usar o MP4 de 1h como única fonte, porque saídas confirmadas podem ser purgadas da VPS.
- Integrar WayinVideo/OpusClip antes da pesquisa de WP-08/G5-09 comparar ferramentas oficiais, alternativa local, custo e controle.

## Próxima ação

Finalizar os testes do render, aprovação/rejeição e interface; atualizar o bundle entregue pela plataforma; abrir PR e deixar o CI/deploy existentes fazerem o caminho até produção. Após health check, autenticar no portal e preparar o piloto na UI. Nada neste marco autoriza chamadas pagas nem envio ao YouTube.

## Rastreamento do SDD

G5-01 → campanha/intenção e público; G5-02 → inventário/proveniência; G5-03 → história completa; G5-04 → enquadramento; G5-05 → duração pelo perfil; G5-06 → som próprio; G5-07 → Revisão/Biblioteca por entrega; G5-08 → calendário/estado do longo; G5-09 → decisão de dependência. O primeiro marco WP-08 é um Short de acervo; depois duas histórias distintas. Campanhas ficam no WP-09.

## Implementação S4 — Revisão → Biblioteca de Shorts

O endpoint de leitura `/api/creator/workshop/shorts/library` expõe apenas Shorts concluídos, aprovados para o hash atual, pertencentes ao canal e ainda compatíveis com o projeto e o manifesto da história. A tela Biblioteca os apresenta em uma seção própria, com player, duração, hash e vínculo ao longo. Uma edição do projeto ou alteração do manifesto remove a versão antiga da lista de publicação; a fonte continua registrada no projeto.

Esta fatia fecha a apresentação do derivado aprovado na Biblioteca (G5-07/G1-02) e não autoriza nem inicia envio. A preparação da publicação como `content_format='short'`, o transporte resumível ligado ao hash aprovado e a exibição do estado de upload pertencem ao S5 e continuam pendentes. Revisão visual/humana na aplicação e verificação com a versão implantada também seguem necessárias.

Fontes oficiais relevantes: [métricas de Shorts](https://support.google.com/youtube/answer/12942217?co=YOUTUBE._YTVideoType%3Dshorts&hl=en), [Related video em Shorts](https://support.google.com/youtube/answer/14075157?hl=pt-BR), [busca e descoberta de Shorts](https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=pt-BR).
