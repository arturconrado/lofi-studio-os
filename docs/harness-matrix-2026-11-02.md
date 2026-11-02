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
