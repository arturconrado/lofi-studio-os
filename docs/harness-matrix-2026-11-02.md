# Harness completo — matriz de cobertura e etapa 1 (2026-11-02)

Escopo: documento consolidado "Mandato para implementação" (10 áreas, 5 etapas).
Estados: **Existente** (comportamento efetivo e testado), **Parcial** (existe, mas incompleto ou restrito a LoFi), **Ausente**.
"Implementado" significa código nesta árvore. "Validado localmente" significa testes locais com PostgreSQL descartável. Nada aqui foi **implantado**.

## Conciliação

- **Branches e PRs:** os PRs relevantes já estão na `main`: #34 referências textuais, #46/#59/#60/#62 Growth nativo, #61 orçamento único, #66 versionamento, #70 memória do canal, #81 brief conversacional, #83/#84 identidade, #100 continuidade e reedição, #101 revisão semântica, #103 primeiro vídeo de canal novo. Não há PR aberto. Os worktrees ativos estão limpos.
- **Prompts 1 e 2 do proprietário:** foram implementados nesta árvore, ainda sem commit: auditoria do canal e catálogo de vídeos existentes com revisão, aprovação, aplicação e releitura. Ver `docs/channel-optimization/channel-audit.md`. O documento consolidado prevalece. A única mudança de comportamento foi tornar as regras de metadados dependentes do perfil (item 4).
- O anexo "Estado atual do harness — integração e lacunas — 02/11/2026 (1)" citado no mandato não chegou a esta sessão. A matriz abaixo foi feita a partir do código.

## Matriz

| # | Requisito | Estado | Evidência (arquivo · comportamento) |
|---|---|---|---|
| 1 | Perfil versionado por canal com nicho, público, idioma, intenção, promessa, formatos, áudio, visual, qualidade e limites | **Parcial → etapa 1 entregue** | `studio/niche_profiles.py` (novo) dentro de `RecipeData.profile` (`studio/recipes.py`): versionado pelo SHA da receita e vinculado ao canal por `channel_recipes`. Receitas sem perfil mantêm o SHA e o comportamento LoFi atuais (teste de igualdade byte a byte). `studio/harness_profiles.py` continua como legado, importado para receitas. |
| 1 | Regras LoFi (inglês, instrumental, garota/gato, câmera travada) só no perfil LoFi | **Parcial → etapa 1 entregue** | Condicionados ao perfil: prompt musical (`music_direction.py`, `production_harness.audio_prompt`), prompt visual (`visual_workshop.prompt`), direção visual da receita (`workshop_api.recipe_visual_direction`), revisor semântico (`semantic_review.system_prompt`) e regras de metadados (`youtube_metadata.metadata_issues`). Criador e Produções legados, fixos em LoFi/inglês, **recusam** perfis de outro nicho (409) em vez de impor LoFi. |
| 1 | Segundo nicho real | **Parcial** | `examples/niche-profiles/piano-natureza-pt-br.json`: pt-BR, piano ambiente, sem personagens, regras editoriais próprias. Teste com Postgres: o pedido pago real do Workshop carrega o perfil e não carrega termos LoFi. Faltam o aceite com geração paga (precisa de autorização) e a remoção dos campos legados obrigatórios da receita (cena do catálogo LoFi, cadência de ações). Hoje esses campos só validam o caminho Produções. |
| 1 | Restrição obrigatória verificada; campos informativos identificados | **Parcial** | `ENFORCEMENT` em `niche_profiles.py` diz onde cada campo atua, e a tela de receitas mostra esse mapa. Verificados: formatos e narração no preflight, coerência perfil × política na validação da receita, regras de metadados. `loudness_target_lufs` e `quality[]` ainda são **informativos** (gate na etapa 3). `NichePolicy.instrumentals_only/protected_zones/ambient_beds/visual_style` seguem só armazenados. |
| 2 | Busca de referências com fonte, motivo e cota | **Ausente** | Não há `search.list` nem outra busca. Existe registro manual (`growth.reference_observations`) e a auditoria do próprio canal (Data API). |
| 2 | Distinguir metadados, imagem, audição humana e mídia analisada | **Ausente** | `reference_observations` não registra o tipo de observação. |
| 3 | Briefing criativo versionado com transformação de referências | **Parcial** | PR #34 e #81: brief de cena revisado. `audiovisual_director.contract` registra evidência editorial e identidade. Não há "referência → princípio → escolha própria" estruturado. |
| 4 | Diagnósticos de crescimento por gargalo (CTR, retenção, impressões, busca, retorno) | **Parcial** | `growth._growth_opportunities` (CTR interno, mix de tráfego, retorno) e `channel_audit.analyze_analytics`. Faltam a matriz de gargalos completa, confiança, esforço e critério de avaliação por recomendação. As regras de frase inicial e 450 caracteres agora dependem do perfil. |
| 5 | Direção resolvida única com versões e hashes até o provedor | **Parcial** | O Workshop vincula `recipe_id + recipe_sha256` (`project_recipe`), e o template musical inclui a receita, agora com o perfil, no hash. Não existe objeto único "direção resolvida" agregando perfil, receita, referências, brief, política e orçamento. |
| 5 | Preflight antes de chamada paga, sem troca silenciosa | **Parcial → etapa 1 ampliada** | Orçamento e reservas: `financial.check_available`, `runtime.reserve`, tetos do projeto. Novo: `require_generation_capabilities` em quote/generate/música do Workshop (409 "Nada foi gerado nem cobrado"). |
| 5 | Amostras proporcionais, retomada e reaproveitamento | **Existente (visual)** | Prova de continuidade antes da montagem longa (`reedit`, `director_proof`), assinaturas por unidade criativa (`creative_spec_signature`) e reaproveitamento de variantes. |
| 6 | Qualidade técnica de áudio e vídeo | **Existente** | `quality_gate.py`, `audio_analysis.py`, `video_guardrails.py`, `calibration.py`, `timeline_compositor.preflight`. |
| 6 | Critérios derivados de referências, por nicho, com estado aprovado/reprovado/pendente/não aplicável | **Ausente** | Os critérios do perfil (`quality[]`) existem, mas ainda não alimentam gates. |
| 6 | Revisão visual da saída real | **Existente** | `semantic_review` com quadros reais e bloqueio na montagem (`require_semantic_segments`). Agora neutro quanto ao elenco fora da identidade canônica. |
| 7 | Edição com impacto: o que muda, o que se mantém, aprovações perdidas e custo | **Parcial** | Reedição sem nova música (#100), assinaturas que invalidam só o trecho afetado e edição de metadados sem tocar mídia. Não há relatório de impacto antes da edição. |
| 8 | Catálogo e publicação de vídeos existentes | **Implementado (prompts 1/2)** | `channel_audit.py`: catálogo, regras por perfil, propriedade validada no servidor, confirmação explícita e releitura. A miniatura ainda é só revisão manual. O caso "nova mídia exige nova publicação" está documentado, sem fluxo dedicado. |
| 9 | Memória ligando referência, perfil, escolhas, revisões, publicação e resultados | **Parcial** | `channel_memory.py` (snapshots, referências e experimentos por canal), `channel_audit_events` e `audit`. Falta ligar a revisão produzida ao resultado observado. |
| 10 | Jornada única com próximo passo, impedimento e custo | **Parcial** | Telas existentes por área (#102 jornada do portal). Falta o painel do projeto com referências, versões, pendências e decisões. |

## Etapa 1 — o que foi implementado agora

1. **Perfil de nicho na receita** (`studio/niche_profiles.py`, `RecipeData.profile`). Ele é opcional e, quando ausente, não altera SHA, prompt nem aprovação. O perfil resolvido, o mapa de aplicação e os bloqueios aparecem em `GET /api/creator/recipes/*` (`niche_profile`) e na tela de receitas (seção "Perfil do canal").
2. **Ligações efetivas:** pedido musical, rodapé do prompt de áudio, pedido visual do Workshop (câmera, ritmo, elenco), direção visual da receita, revisor semântico, regras de metadados da auditoria do catálogo e heurísticas LoFi da auditoria (só para o perfil LoFi).
3. **Preflight de capacidade** antes de cotação, geração de imagem/vídeo e música no Workshop. Formatos sem compositor aparecem como impedimento, sem bloquear o vídeo longo.
4. **Guardas dos fluxos legados:** o Criador (`/creator/plan`) e as Produções recusam perfis de outro nicho antes de reservar custo.
5. **Validação de coerência:** política instrumental × voz no perfil, variante pixel art × elenco não canônico e idioma do perfil × idioma dos metadados.
6. **Marca na auditoria do catálogo:** `LoFi Vibe Coding`/`Tração` só vêm pré-preenchidos no canal principal.

Garantias de compatibilidade testadas: prompts musical e visual sem perfil são idênticos aos da `main` (comparação byte a byte) e a receita LoFi embutida mantém o SHA.

## Base da etapa 2 — orquestração colaborativa (implementada)

Pedido do proprietário: uma camada de orquestração entre os agentes e o harness, cobrindo os agentes de IA do produto e os agentes de desenvolvimento.

- **Produto** (`studio/orchestration.py`, `GET /api/creator/workshop/projects/{id}/orchestration`, painel "Agentes e etapas deste episódio" no projeto):
  - Registro dos 11 agentes e etapas: perfil, pesquisa de referências, briefing, identidade, gerador visual, revisor visual, composição e montagem, revisão final, metadados, publicação e aprendizado. Cada um aponta para o módulo que já executa o trabalho e informa o tipo (agente de IA, harness ou decisão humana) e a classe de custo.
  - **Direção resolvida única** por projeto: canal, receita e SHA, perfil e SHA, identidade e referências, hash do brief, teto do projeto. Ela é versionada em `orchestration_directions`.
  - Cada pedido pago de imagem ou vídeo do Workshop grava `direction_sha256`, e o painel mostra as passagens de bastão (direção × operação).
  - O plano de etapas é calculado no servidor a partir do mesmo estado que a tela lê. Status: concluído, pronto, aguardando você, em andamento, bloqueado, recomendado e ainda não disponível. Cada etapa mostra o próximo agente, o motivo e o resultado esperado. **A camada não inicia, aprova nem publica nada.**
  - Pendente: gravar `direction_sha256` também em revisão semântica, música/montagem e publicação; ligar a pesquisa de referências (etapa 2) à `direction.references`.
- **Desenvolvimento** (`AGENTS.md`, importado por `CLAUDE.md`): fonte de verdade, reivindicação de tarefa por PR em rascunho, uma branch e um worktree por tarefa, regras de commit, validação obrigatória, modelo de passagem de bastão e checklist para novo agente no produto.

## Validação

### Complemento editorial e idioma (PR #106)

- `studio/editorial.py` resolve a política da receita do canal e verifica o texto final com identificação estatística local (`langid`, sem chamada paga). Inglês do LoFi independe do idioma do operador; texto curto, nome próprio ou resultado inconclusivo requer a revisão humana existente. Não é certificação linguística universal.
- Tom, exemplos aprovados/rejeitados e nomes preservados ficam em `MetadataRules`, na receita versionada, com edição na tela de receitas. Campos novos vazios não mudam a serialização de perfis antigos. Feedback editorial não é métrica de audiência.
- Growth e Criador recebem o contrato; auditoria verifica na aprovação e antes de aplicar. Publicação/edição verificam o texto e guardam recibo ligado ao conteúdo e à política; o worker confere novamente antes de enviar/retomar. Mudança da política invalida essa revisão sem regenerar mídia.
- Corpo editorial separado de capítulos, CTA e hashtags. A descrição pode começar com um convite contextual em vez de repetir obrigatoriamente a frase principal. Notas de render e alegações de produtividade sem fundamento são recusadas.
- A inicialização de receitas pela consulta de canal usa a transação do chamador, evitando espera circular entre DDL e publicação no primeiro uso.
- Migração aditiva: `channel_audit_changes.approved_editorial_sha256`, criada sob demanda. Propostas antigas precisam de nova aprovação editorial antes de aplicar. Nenhum texto publicado é traduzido em lote.
- Casos de regressão em `tests/test_editorial.py`; fluxos existentes de auditoria/publicação, Growth e perfis incluídos na validação. Integração da escolha de mensagem, briefing e OCR fica no PR #107.
- Estado: implementado localmente; suíte completa com 399 testes Python, 47 de interface, TypeScript e build aprovados; teste adicional da API de idioma/aprovação desatualizada também aprovado. Implantado: não; nenhuma chamada paga ou publicação real nesta implementação.

- `tests/test_orchestration.py` (4) e `frontend/src/__tests__/orchestration.test.tsx` (1): plano, próximo passo, bloqueios e painel somente leitura.
- `tests/test_niche_profiles.py`: 8 testes. Inclui um teste com PostgreSQL em que um canal com o perfil "Piano e Natureza" é bloqueado por capacidade ausente (narração) sem chamada nem reserva, e depois gera um pedido pago real (mock do provedor) contendo a linguagem do perfil e sem termos LoFi.
- Suítes existentes de receitas, música, Workshop, produções, Growth, Criador e auditoria seguem passando. Os números finais estão no relatório da sessão.
- Frontend: `tsc`, `vitest` e `vite build`.

## Migrações

Nenhuma migração de banco. O perfil vive no JSON das revisões de receita (`recipe_revisions.data`). As tabelas da auditoria do catálogo são criadas sob demanda por `ensure_once`.

## Próximas etapas

2. Busca de referências pela YouTube Data API (`search.list`, 100 unidades de cota por chamada, reaproveitando resultados salvos), com tipo de observação explícito. Briefing de transformação referência → princípio → escolha própria. Memória com origem.
3. Direção resolvida única (perfil, receita, referências, brief, política e orçamento com hashes) usada por todos os caminhos. Critérios `quality[]` e `loudness_target_lufs` como gates da saída real.
4. Relatório de impacto da edição antes de aplicar, com invalidação apenas das dependências afetadas.
5. Diagnósticos de crescimento por gargalo com confiança, esforço e critério de avaliação. Retorno dos resultados à memória.

Impedimentos externos: aceite com geração paga e publicação real dependem de autorização explícita. Narração/voz e formatos 9:16 nativos por perfil não existem no estúdio e aparecem como impedimento, não como suporte.

## Complementos: motores, ambiência, abertura e apresentação (branch `claude/motores-entrega-verificada`)

Fontes: "Melhorias dos motores" (prompt integral), adendo de ambiência/abertura/apresentação e Prompt V2. Os scripts do anexo **não** foram copiados: os problemas que eles evidenciam viraram regressões.

| Requisito | Estado | Evidência |
|---|---|---|
| Crossfades descontados, cobertura medida pelo PCM, insuficiência bloqueada | **Existente → testado** | `audio_mix.mix/coverage`. `tests/test_delivery.py` prova que acrescentar segundos ao alvo não cria cobertura. |
| Arquivo final verificado, não só o código de saída do FFmpeg | **Implementado e testado** | `delivery.verify_delivery`: streams esperados, codecs, fps, sample rate, canais, início dos streams, diferença áudio×vídeo e silêncio final. Aplicado em `workshop_worker.render_segments` (montagem e prévias) e na entrega só de áudio. Um vídeo com áudio mais curto ou sem áudio é rejeitado. |
| Análise de programa separada da análise de faixa | **Implementado e testado** | `delivery.program_audio`: loudness, true peak, LRA e silêncio inicial/final sem o limite de 600 s do `quality_gate`. Não normaliza e compara com a política de masterização existente. Aplicado na trilha do Workshop e da entrega só de áudio. |
| Ambiência aplicada em todos os caminhos suportados | **Parcial → implementado no Workshop e no áudio** | Antes só o Criador legado (`creator_service.apply_ambience`) aplicava `ambient_bed`. Agora `workshop_worker.apply_recipe_ambience` aplica a camada, preserva e envia a mixagem só com música e registra o relatório. |
| Ganho aplicado × relação medida com a música | **Implementado e testado** | `ambient_audio.layer` registra `applied_gain_db` e `measured_relation_lu` (LUFS da camada no ganho aplicado menos LUFS da música). |
| Proveniência por camada (fonte, autorização, hash, nível, fades, posição, relação com a cena) | **Implementado** | Relatório da camada: `source`, `authorization`, `bed_sha256`, `placement`, `fade_*`, `scene_relation_review=required`. Os fades de entrada e saída ainda são fixos em 0, e configurá-los fica pendente com a decisão de abertura. |
| Café e digitação | **Ausente (declarado)** | `ambient_audio.CATALOG`: sem fonte própria ou licenciada. Aparecem desabilitados com o motivo na tela de receitas, e a receita não aceita salvá-los. |
| Efeitos pontuais sincronizados com ações | **Ausente** | Não há fonte nem ligação com os eventos da timeline. |
| Tracklist pelos offsets reais e capítulos só quando válidos | **Implementado e testado** | `delivery.tracklist/chapters`, gravados no relatório da montagem e da entrega só de áudio. Defeito corrigido: `ambient_api.tracklist` somava durações nominais e ignorava os crossfades; agora usa os offsets do manifesto. |
| Revisão da abertura (15/30/60/90 s e primeira transição) | **Parcial → medição implementada e testada** | `delivery.opening_review` mede, na mídia entregue, silêncio, saltos de nível em 1 s e true peak, e grava `opening_review` (status `review_required`). **Pendente:** a decisão de abertura no briefing (faixa inicial, entrada da ambiência, vinheta, imagem inicial) e uma aprovação específica vinculada a ela. |
| Apresentação do canal (nome, promessa, idioma, avatar, banner, playlists, trailer, destaque) | **Implementado** | `channel_audit.presentation_checklist` mostra o que a API lê e o que vira tarefa manual no Studio. Trailer e vinheta são opcionais e nunca produzidos automaticamente. |
| Metadados conciliados com a mídia final | **Parcial** | Tracklist, capítulos e duração medida estão no relatório da montagem. Falta usá-los no pacote do Growth e na publicação. |
| Miniatura com decisão explícita (texto, idioma, hierarquia) | **Ausente** | Pendente na etapa 4. |
| Impacto de edição; corrigir só o áudio preservando o visual | **Parcial** | Reedição sem nova música (#100) e retomada da trilha sem nova chamada paga existem. Falta um relatório de impacto antes de editar. |
| Regressões dos exemplos do anexo | **Implementado e testado** | Teste estático: rótulos de filtergraph `[1:a]`, `eq` com `t` exige `eval=frame`, nenhuma janela fixa de 300 quadros e nenhum `-shortest` nos motores de arquivo. O `-shortest` permanece só na transmissão RTMP ao vivo (`program_radio`), onde o vídeo é infinito e o fim do programa encerra a transmissão. |
| Garantias algorítmicas do anexo (3601 s, ruído, hashes, Content ID) | **Não incorporadas por decisão** | Nenhuma regra ou mensagem do produto promete desbloqueio por ruído, hash ou duração. |

Validação deste complemento: `tests/test_delivery.py` (10 testes com FFmpeg real) e a extensão de `tests/test_channel_audit.py`, além das suítes completas. Implantado: não.

## Pendências atacadas nesta rodada (mesma branch)

| Pendência | Estado | Evidência |
|---|---|---|
| Busca de referências pela API do YouTube | **Implementado e testado** | `studio/reference_research.py`: `POST /api/growth/{canal}/reference-search` com confirmação de cota (`search.list`: 1 unidade do balde de buscas, até 100 por dia segundo a documentação consultada em 2026-11-02). Buscas iguais em 7 dias reutilizam o resultado salvo sem nova chamada. Resultados registram só metadados públicos, e vídeos do próprio canal não viram referência externa. Tela: Análises → Referências. |
| Tipo de observação de cada referência | **Implementado e testado** | `reference_observations` ganhou `source`, `observation_type`, `fit_reason`, `observed_features`, `observed_timestamp`, `search_result_id` e `reference_role` (colunas novas com padrão compatível). Observação perceptiva exige descrição do que foi ouvido ou visto. A memória do canal já lê essa tabela. |
| Briefing versionado (referência → princípio → escolha própria → critério) | **Implementado e testado** | `studio/episode_brief.py`: `PUT/GET /workshop/projects/{id}/brief`, uma versão por mudança, só com referências do mesmo canal. Critério perceptivo citando referência só de metadados é recusado. Tela: painel "Briefing do episódio" no projeto. |
| O briefing chega aos pedidos reais | **Implementado e testado** | Música: `composition_request` inclui o conceito, a direção temporária, a experiência da faixa de abertura (só na primeira) e os princípios transformados. Imagem e vídeo: `visual_workshop.prompt` inclui conceito, direção, imagem e movimento iniciais (só na base) e princípios. A tarefa paga grava `episode_brief_sha256`. Sem briefing, os prompts são idênticos aos da `main` (comparação byte a byte). |
| Decisão de abertura → motores e revisão | **Implementado e testado** | A entrada e o fade da ambiência seguem o briefing (`ambient_audio.layer` com atraso e fade; `none` dispensa a camada do canal neste episódio). A montagem grava a versão do briefing. `POST .../renders/{id}/opening-review` registra a revisão humana presa aos bytes e à versão do briefing, e a aprovação final passa a exigi-la quando o briefing decide a abertura. |
| Vinheta | **Ausente (bloqueio declarado)** | Pedir vinheta bloqueia a montagem antes de reservar custo, porque não existe gerador de vinheta. |
| Decisão de miniatura | **Parcial** | A decisão fica registrada no briefing: texto ou não, mensagem, idioma, hierarquia e relação com o título; a arte da cena nunca leva texto. Ainda não há geração nem avaliação reduzida da miniatura. |
| Relatório de impacto antes de editar | **Implementado e testado** | `studio/edit_impact.py`: `POST /workshop/projects/{id}/impact` usa o mesmo `status()` do Workshop no rascunho atual e no proposto. Mostra o que se mantém, as aprovações perdidas, o que regenerar com cotação, a trilha (nova ou reaproveitável) e a aprovação final perdida. Mudar só a música preserva todo o visual; mudar uma ação invalida só aquele trecho; editar só o texto não refaz nada. Tela: "Ver impacto antes de salvar". |
| Metadados conciliados com a mídia entregue | **Implementado e testado** | `delivery.reconcile_metadata`: afirmações de duração (inglês e português) e carimbos de capítulo são conferidos contra a duração medida e a tracklist real. Aplicado ao criar a publicação, ao editar metadados de vídeo publicado e na auditoria do catálogo (`duration_claim_mismatch`). O rascunho padrão deixou de afirmar "One hour" sem medição. |
| Rastreio da direção até a publicação | **Implementado** | `direction_sha256` na geração, na revisão visual e na montagem. A publicação de vídeo vindo do Workshop registra direção, briefing e a conciliação em `publication_metadata.trace`. |
| Efeitos pontuais, café e digitação | **Ausente** | Continuam sem fonte e aparecem como indisponíveis. |
| Diagnóstico de crescimento por gargalo (etapa 5) | **Pendente** | Não iniciado nesta rodada. |

## Pendências finais incorporadas ao desenvolvimento (PR #107)

### Complemento nativo: apresentação, idioma e revisão editorial

- A tela de briefing reaproveita `growth.package_suggestion` para propor título, descrição, mensagem exata da thumb, hierarquia, relação com o título e justificativa. A proposta usa o projeto do próprio canal, perfil, referências/memória e feedback humano de thumbs aprovadas/rejeitadas. Não salva o briefing nem gera imagem automaticamente.
- A sugestão exige a confirmação de até US$ 0,10, permissão de gasto e reserva do gerador existente. `project_id` e `direction_sha256` acompanham a tarefa; a reserva também respeita o teto do projeto sob lock. Repetir um ID não dispara nova cobrança. Nenhuma chamada paga foi executada nesta implementação.
- `Thumbnail.text_policy` começa sem decisão, e a interface exige escolher texto/sem texto. O idioma vazio herda o perfil; um conflito explícito ou texto claramente fora do idioma é recusado antes do custo. Não há inglês nem slogan universal imposto a outros perfis.
- O texto efetivamente lido da imagem passa pela triagem linguística local, além da fidelidade OCR e leitura reduzida já existentes. Idioma incorreto bloqueia; texto curto, nome próprio ou resultado incerto requer confirmação humana específica do idioma na imagem. Legibilidade não aprova automaticamente a pertinência da mensagem.
- Aprovação de thumb guarda recibo do texto e da política. A publicação/reentrada confere briefing, perfil e arte-base atuais **antes** de iniciar o upload. Se o briefing exige thumb e não há uma aprovada, não usa silenciosamente a capa padrão.
- Revisão editorial não é resultado de audiência. O feedback é isolado por canal; exemplos de slogans anteriores não são vencedores. Duração e capítulos não são inventados na proposta anterior à montagem; o gate de mídia continua a conciliar a publicação final.
- Mudança só da descrição preserva a aprovação da imagem e a revisão da abertura; mudança só do título exige nova revisão de coerência, podendo reaproveitar os mesmos bytes. Mudança da direção de produção continua a invalidar a abertura. Não é necessário refazer áudio/vídeo por uma revisão textual.
- Testes de backend: proposta nativa, consentimento/canal/direção, capítulos/duração fictícios, OCR fiel em idioma errado, herança/conflito de idioma, falta de thumb aprovada, alteração de perfil e reuso de mídia em edição textual. Teste de interface: consentimento e prévia antes de salvar/gerar imagem. Resultados finais registrados no PR.
- Estado: implementado; validação final em execução na sessão. Implantado: não. Revisão com provedores pagos e aplicação no YouTube real permanecem sem execução nesta implementação. Testes A/B do YouTube Studio continuam manuais; esta alteração não cria nem exclui experimentos externos.

| Pendência | Estado | Evidência |
|---|---|---|
| Diagnóstico de crescimento por gargalo (etapa 5) | **Implementado e testado** | `studio/growth_diagnostics.py`, `GET /api/growth/{canal}/diagnostics`: gargalos de CTR, retenção após o clique, alcance, alinhamento com a busca e retorno, contra quartis de vídeos próprios do mesmo formato e janela (mínimo de 3). Cada diagnóstico tem alvo, evidência ou hipótese, ação, confiança com motivo, esforço e critério de avaliação; métricas ausentes geram "evidência insuficiente", sem quartis inventados. Tela: Análises → Visão geral. |
| Efeitos pontuais gerados com a ação (ex.: digitação) | **Implementado e testado** | Campo `sound_effect` no trecho. O vídeo daquele trecho passa a ser pedido ao Veo com `generate_audio` e uma direção sonora restrita (sem música e sem voz). A assinatura muda só quando há efeito, então clipes antigos ficam intactos e a prévia de impacto acusa a regeneração necessária. A cotação usa o SKU com áudio publicado pelo OpenRouter; se ele não existir, a geração é recusada. A montagem bloqueia trechos cujo vídeo veio sem áudio e `sound_design.apply` posiciona o efeito em cada horário real da ação. |
| Ambiência gerada (ex.: café) | **Implementado e testado** | Campo `generated_ambience` no projeto. O vídeo-base é gerado com áudio; a montagem extrai o som, emenda em loop com crossfade, aplica volume, entrada e fade da abertura, mede a relação com a música e mistura. Neste projeto, ela substitui a cama procedural da receita. |
| Café e digitação no catálogo | **Implementado** | Disponíveis via gerador (`generated_with_base_video` / `generated_with_action_video`), com fonte, custo e escuta declarados. Não são selecionáveis como cama procedural da receita. |
| Miniatura gerada completa e conferida | **Implementado e testado** | `studio/thumbnails.py`. O modelo de imagem gera a **miniatura completa** (composição, identidade e o texto exato do briefing, no idioma decidido) a partir da imagem-base aprovada. O harness não desenha nada por cima: só recorta para 1280×720 e codifica em até 2 MB. Em seguida, o avaliador visual do estúdio (`gemini-2.5-flash-lite`) lê o texto em tamanho normal e em 320×180. Texto diferente do briefing, ou texto não pedido, reprova a miniatura; leitura inconclusiva exige confirmação humana do texto. A cotação soma imagem e duas leituras. São até 3 tentativas por versão do briefing, cada uma com confirmação de custo. A aprovação humana fica presa ao SHA e ao briefing, e a publicação usa a miniatura aprovada. |
| Orquestração | **Atualizado** | Novo agente `thumbnail_designer` e etapa no plano. |

Limites declarados: o áudio gerado pelo Veo pode conter música ou fala apesar da direção, e só a escuta descarta isso (revisão obrigatória registrada). A ambiência gerada vem de um clipe de 4 a 8 s em loop, e a repetição precisa ser ouvida. O preço do vídeo com áudio vem do SKU publicado; nenhum valor é estimado.

## Implantação da entrega editorial — build completo

- Implementado: `deploy-full.yml` constrói a imagem completa do Dockerfile e guarda artifact antes da aprovação do ambiente protegido. O deploy verifica CI do commit, atualização da main, checksums, ocupação e espaço.
- `ops/auto-deploy.sh` reaproveita backup, ativação, saúde e rollback para imagem previamente construída. Valida label/requirements; o caminho incremental segue bloqueando mudanças de dependência. Chave restrita e políticas de aprovação preservadas.
- Validado: testes de gates e workflow em `tests/test_workshop_deploy.py`, actionlint, shellcheck e suíte do PR.
- Implantado: aguarda a execução protegida; evidências e resultado no PR/Notion. Nenhuma geração paga é parte desta entrega.

## Som planejado por vídeo a partir do ambiente (PR seguinte ao #107)

| Requisito | Estado | Evidência |
|---|---|---|
| O harness entende o ambiente de cada vídeo antes de pedir o som | **Implementado e testado** | `studio/sound_planner.py`, `POST /workshop/projects/{id}/sound-plan`. A leitura determinística e gratuita de cena, movimento do cenário, tema, briefing e ações de cada trecho cita a palavra que justifica cada som. A leitura da imagem-base aprovada pelo avaliador visual (`gemini-2.5-flash-lite`) é opcional, paga em centavos e confirmada. Ações inventadas pelo modelo são descartadas. |
| Plano aceito por uma pessoa vira a direção sonora do vídeo | **Implementado e testado** | `POST .../sound-plan/{id}/apply` com controle de versão. Os itens aceitos viram `generated_ambience` e o `sound_effect` de cada trecho, e o relatório de impacto mostra o que precisa ser gerado de novo com som. Um plano feito para outra versão do projeto é recusado. |
| Conferência do som gerado | **Implementado e testado** | `POST .../media/{id}/audio-check`: o avaliador ouve o áudio do clipe (entrada de áudio, confirmada no catálogo do OpenRouter) e aponta música, fala ou canto, ou som diferente do pedido. Um clipe sinalizado bloqueia a montagem até uma pessoa ouvir e aceitar aqueles bytes. |
| Orquestração | **Atualizado** | Agente `sound_designer` com etapa própria no plano do projeto. |

## Vinheta de abertura única por canal

| Requisito | Estado | Evidência |
|---|---|---|
| O harness do canal continua sendo a base | **Mantido** | Perfil, receita, identidade e política editorial são do canal; briefing, plano de som e miniatura são decisões por vídeo dentro dele. |
| Uma vinheta única por canal, com características próprias | **Implementado e testado** | `studio/channel_vignette.py`. Definição versionada por canal: conceito, motivo visual, assinatura sonora, 4, 6 ou 8 s e nome opcional. Gerada pelo Veo com áudio, partindo do still de identidade aprovado do canal, com cotação pelo preço com áudio, confirmação e envio único. |
| Não repetir a abertura de outro canal | **Implementado e testado** | Assinatura de quadros (average hash em três pontos) comparada com as vinhetas aprovadas dos outros canais do workspace. Uma vinheta parecida demais fica "too_similar" e não pode ser aprovada. Sem áudio, também não. |
| Aprovação e uso por vídeo | **Implementado e testado** | Aprovação humana presa aos bytes e à definição atual, depois de assistir e ouvir. O briefing escolhe "vinheta do canal"; sem vinheta aprovada, a montagem e o plano de agentes acusam o bloqueio antes de qualquer custo. A montagem coloca a vinheta antes do programa, normalizando resolução, fps e áudio. A união é feita por cópia de streams, com conferência de decodificação na junção; se falhar, há recodificação. O arquivo final é verificado e a tracklist e os capítulos são deslocados, com o primeiro capítulo em 0:00. |

### Correções da revisão do PR #109

- Leitura paga de imagem e conferência de áudio exigem permissão de gasto; o plano gratuito por texto permanece disponível ao criador.
- As duas leituras usam a reserva durável compartilhada, respeitam saldo global e teto do projeto, conciliam o custo confirmado e registram modelo, mídia e `direction_sha256`.
- O mesmo identificador reaproveita o resultado. Falha de resultado incerto mantém a reserva e bloqueia reenvio automático; a interface envia o identificador e confirma o teto conservador de US$ 0,20.
- Testes cobrem permissões reais da API, conciliação, reaproveitamento, geração desativada, saldo global, orçamento do projeto e resultado incerto. Provedores simulados; sem geração paga nem implantação nesta correção.
