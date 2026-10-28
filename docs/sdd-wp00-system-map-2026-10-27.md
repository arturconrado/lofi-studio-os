# WP-00 — mapa estático de sistema e dados (27/10/2026)

**Baseline do código:** `main` em `cb369c97e9f9fb175392f4341296b50d3f42476e`. Este mapa foi extraído de código e documentos versionados; é uma referência para a descoberta, não uma declaração de que todos os componentes estão ativos ou equivalentes no host.

## Componentes e responsabilidades

| Camada | Código observado | Responsabilidade | Evidência/limite |
|---|---|---|---|
| Aplicação/API | `studio/api.py` e routers `studio/*.py` | Interface web, API, middleware de sessão/CSRF e regras globais por papel | Mapa de rotas em [sdd-wp00-route-map-2026-10-27.md](sdd-wp00-route-map-2026-10-27.md). Regras específicas de handler ainda exigem matriz por endpoint e verificação contra o runtime. |
| Banco | PostgreSQL via `studio/core.py`; DDL distribuído por módulos de domínio | Estado de produção, filas, catálogo, usuários, tenants, revisões e aprovações | `init_db` aplica DDL e registra hash de revisão; inicializadores de domínio podem executar DDL próprio. Lista abaixo é a fonte no código, não o catálogo SQL atual do servidor. |
| Isolamento por workspace | `studio/tenancy.py` | `search_path` exclusivo `ws_<uuid>`, prefixo S3 `workspaces/<uuid>/` e prefixo Redis por workspace | `db()` não adiciona `public` ao `search_path` do workspace. Isso precisa ser levado em conta em qualquer consulta a tabelas legadas. |
| Fila/cache | Redis via `core.queue()` e `ScopedQueue` | Heartbeats e sinais de worker; nomes são prefixados quando há workspace | A consulta confirma conexão/configuração usada pelo código, não a cobertura/ACL instalada em produção. |
| Mídia/objetos | S3 compatível via `core.storage()` e `ScopedStorage` | Assets, fontes, renders e relatórios | Prefixo de workspace é aplicado pela camada de aplicação; backup/versionamento e retenção dos objetos ainda requerem prova operacional. |
| Geração musical | `studio/provider.py`, `studio/runtime.py`, `studio/worker.py` | Stream de áudio, allowlist de modelos, custo/recibo e validação do arquivo | Integração externa requer autorização/cobertura financeira; esta auditoria não chamou provedores nem leu chaves. |
| Geração visual | `studio/workshop_provider.py`, `studio/workshop_worker.py` | Cotação e envio de imagem/vídeo; controle de tarefa e conclusão | Revisar compatibilidade, custos e comportamento de reserva em WP-02/04; nenhuma geração foi feita. |
| Montagem | `studio/timeline_compositor.py`, `studio/timeline_worker.py`, `studio/workshop_worker.py`, `studio/video_export.py`, `studio/audio_mix.py` | Prévia, montagem temporal, montagem de segmentos, exportação e mixagem | Há caminhos distintos no código. WP-00/WP-03 precisam demonstrar quais fluxos os chamam e decidir se compartilham o contrato/compositor, em vez de presumir que sejam um motor único. |
| Publicação | `studio/youtube.py`, `studio/youtube_publish.py` | OAuth, autorizações, fila/upload, metadados, reconciliação e operações de gestão | Requer revisão por escopo e teste com publicador simulado; não foi feito upload, edição ou exclusão. |
| Processos de apoio | `studio/exports.py`, `studio/email_worker.py`, `studio/radio.py`, `studio/channel_radio.py`, `studio/program_radio.py` | Exportação, outbox de email, rádio e transmissão | O `compose.yaml` declara Studio e music-worker; `compose.git.yaml` acrescenta rádio. O runtime observado tem serviços adicionais; a origem e o arquivo Compose efetivamente usados precisam ser reconciliados. |

## Entidades declaradas no código

O parser de DDL encontrou 57 tabelas distintas em 19 módulos; `production_batches` tem uma declaração idempotente adicional. A localização e a lista abaixo são úteis para orientar comparação com o schema de produção; não afirmam que todos os objetos existem ou estão no mesmo schema.

| Módulo | Tabelas declaradas |
|---|---|
| `studio/core.py` | `assets`, `audit`, `broadcast_control`, `factory_control`, `factory_tasks`, `jobs`, `production_batches`, `program_members`, `program_reviews`, `program_scenes`, `qc_runs`, `scenes`, `studio_config`, `studio_schema_state`, `tracks`, `visuals` |
| `studio/authentication.py` | `os_auth_audit`, `os_email_outbox`, `os_memberships`, `os_platform_sessions`, `os_rate_limits`, `os_sessions`, `os_tokens`, `os_users`, `os_workspaces` |
| `studio/creator.py` | `creator_plans`, `program_metadata` |
| `studio/productions.py` | `production_blocks`, `productions` |
| `studio/batch_factory.py` | `production_batches` (declaração idempotente adicional) |
| `studio/channels.py` | `radio_channels` |
| `studio/ambient_api.py` | `ambient_pilots` |
| `studio/episode_api.py` | `publication_episode_history`, `publication_episodes`, `publication_series` |
| `studio/events.py` | `studio_events` |
| `studio/exports.py` | `export_control`, `export_jobs`, `export_reviews` |
| `studio/growth.py` | `analytics_snapshots`, `channel_growth_observations`, `growth_experiments`, `reference_observations` |
| `studio/harness_profiles.py` | `channel_harness_profiles` |
| `studio/live_presentation.py` | `live_copy` |
| `studio/monetization.py` | `monetization_progress` |
| `studio/programming.py` | `channel_programming`, `program_queue` |
| `studio/recipes.py` | `autopilot_recipe`, `channel_recipes`, `recipe_revisions`, `recipes` |
| `studio/workshop_api.py` | `visual_library`, `visual_media`, `visual_projects` |
| `studio/youtube.py` | `channel_credentials`, `youtube_oauth_states` |
| `studio/youtube_publish.py` | `youtube_publications` |

As nove tabelas de autenticação são criadas explicitamente em `public`; o catálogo legado continua no schema público. Os demais objetos dependem do `search_path` da conexão que executa o inicializador. A comparação com `information_schema` no servidor ainda é necessária para distinguir objetos atuais, antigos e fora do código.

### Comparação read-only com o schema observado

Em 27/10/2026, a consulta de catálogo executada pelo container Studio foi marcada como transação read-only e retornou somente nomes/contagens de objetos: **57 tabelas no schema `public`, nenhum schema `ws_*`**. Comparadas com as 57 tabelas declaradas na `main`, **55 nomes coincidem**. O schema observado também contém `live_motion_studies` e `visual_project_budgets`, sem declaração `CREATE TABLE` correspondente na `main`; por outro lado, `autopilot_recipe` e `channel_harness_profiles` existem no código mas não aparecem no schema observado. Ambos têm inicialização tardia sob demanda (`ready()`/`ensure()`), então sua ausência pode ser legítima enquanto os fluxos não foram chamados.

`visual_project_budgets` está presente em `public` e é consultada condicionalmente em `workshop_api.py`. A busca no histórico do código não encontrou declaração DDL/migração versionada; a origem, finalidade, retenção e dono continuam sem evidência. `live_motion_studies` também não tem DDL no código atual. Seu uso na API apareceu no commit `9847087` (estudo temporal); o teste de autenticação cria uma tabela temporária para fixture, o que não demonstra provisionamento de produção. Os snapshots de código registram a rota que consulta a tabela, mas não identificam sua criação. Não foram consultados registros de tabelas nem valores de configuração.

**Rechecagem dos snapshots em 28/10:** busquei os nomes das duas tabelas em 15 arquivos Python/SQL/shell capturados nos snapshots de 24/10 e 27/10. A busca não encontrou instruções `CREATE`, `ALTER`, `INSERT`, `UPDATE` ou `DELETE` para esses objetos. Isso amplia a evidência negativa do repositório atual para o código recuperado, mas não prova que os objetos não sejam criados por SQL dinâmico, migração externa, console administrativo ou versão ainda não capturada. Continuam sem evidência a origem, os escritores, o responsável e a política de retenção; não consultar conteúdo de linhas nem alterar o schema até identificar esses pontos.

| Objeto observado | Evidência atual | Classificação WP-00 | Próximo passo seguro |
|---|---|---|---|
| `live_motion_studies` | Existe no catálogo de produção; a API faz leitura condicional; não há DDL/migração no código atual. O commit `9847087` introduz o consumidor, e o teste cria somente uma fixture efêmera. | Contrato de schema sem provisionamento rastreado; não presumir que a tabela possa ser removida ou recriada. | Localizar evidência da criação sem ler linhas de usuário, atribuir proprietário/retenção e definir migração reversível antes de tocar no schema. |
| `visual_project_budgets` | Existe no catálogo de produção; `workshop_api.py` lê `limit_usd` quando a tabela existe; não há DDL/migração versionada localizada. | Configuração financeira fora do contrato versionado; vínculo e retenção dos limites precisam ser protegidos. | Identificar a origem e o processo que grava os limites; decidir se deve virar migração versionada e cobrir o comportamento com teste isolado. |

Até esses passos, ambos são dependências de segurança do WP-00/WP-01/WP-02. A evidência de catálogo prova existência e nomes/colunas observados, mas não prova quem os criou, quais fluxos os escrevem, nem que uma migração seja segura.

## Finanças — risco reproduzido; WP-02 continua parcial

`studio/financial.py` consolida reservas de `jobs`, `factory_tasks`, `creator_plans`, `production_batches` e `productions`, sob o teto lido de `studio_config`. A conexão de workspace configura `search_path` apenas para o schema `ws_<uuid>`. Antes da correção proposta neste PR, a rotina condicionava a leitura de `creator_plans`/`production_batches` a `to_regclass('public.creator_plans')`, embora as consultas seguintes usassem nomes não qualificados.

Em banco descartável recém-criado, a regressão reproduziu o erro: dois schemas de workspace tinham reservas e tetos diferentes (US$ 8,40 e US$ 3,20), mas a implementação anterior reportava US$ 0 quando `public.creator_plans` não existia. O código da branch agora resolve a existência das tabelas pelo `search_path` ativo. O teste preserva dois workspaces simultâneos e exige os dois totais exatos, sem vazamento entre eles.

Ao reexecutar a suíte, essa correção também revelou que `productions.cost_ceiling_usd` podia ser contado uma segunda vez quando o sistema convertia parte do teto autorizado em um `production_batch`. A autorização agora informa qual produção cobre o novo bloco; `authorize_batch` credita somente o saldo ainda não convertido dessa reserva, mantendo o limite global e a transação sob o advisory lock já usado pelos chamadores. A suíte focal de finanças e produções passou, e um teste com duas sessões concorrentes confirmou que apenas uma reserva de US$ 0,08 cabe num saldo de US$ 0,10.

O código de `studio/workshop_api.py` também consulta `visual_project_budgets` apenas se ela existir; a tabela está no schema observado, embora não haja `CREATE TABLE` correspondente na `main` baseline. Pode ser estrutura legada/out-of-band ou caminho criado por outro release. A correção financeira não altera essa tabela; sua origem e retenção continuam por identificar no WP-00.

**Estado de WP-02:** além do cenário de dois schemas e concorrência, o PR #71 inclui callback terminal autenticado por token aleatório, assinatura HMAC opcional, deduplicação por chave do evento e recuperação do ID do trabalho aceito sem reenviar a geração. A simulação PostgreSQL ponta a ponta cobre resposta perdida após aceitação, tentativa de consulta sem segundo POST, callback, polling do ID original, associação do resultado e reserva preservada. TEST-22 está coberto no adaptador simulado. TEST-23 tem prova parcial: processo novo reencontra a reserva incerta e bloqueia uma segunda reserva acima do teto; faltam limite de tentativas/reavaliações e orientação completa ao usuário. O TEST-24 cobre retomada pela API e worker locais, fontes/duração/tarefa preservadas, sem segunda chamada paga, e bloqueio após mudança de configuração; segue simulado sem mídia real. Um teste isolado adicional cobre callback terminal `cancelled`, preservando ID original e reserva. TEST-41 segue parcial: não há evidência de operação de cancelamento remoto nem reconciliação final do custo. Não houve chamada paga a provedor. A suíte completa precisa ser repetida antes do novo push; CI/code review também precisam ser atualizados. No schema da VPS observado não há schemas `ws_*`; não há evidência de que o caminho workspace seja usado em produção.

## Lacunas que continuam em WP-00

- Obter lista read-only de tabelas/schema efetivamente instalados e reconciliar com os 57 identificadores do código; mapear migrações, chaves/foreign keys, soft delete e dados que não podem ser removidos.
- Mapear qual imagem/processo atende cada rota e qual arquivo Compose/release configura os workers ativos, com atenção especial a publisher, rádio e music-worker.
- Resolver o caminho real de cada compositor (criação, prévia, render, Shorts e exportação) e os contratos que compartilham.
- Atualizar o inventário do corpus de mídia com proveniência/acesso em armazenamento privado; referências visuais históricas não substituem inspeção dos objetos atuais.
- Reproduzir em staging/simuladores os relatos e jornadas do SDD. O snapshot de 24/10 ainda não foi restaurado de forma isolada; TEST-27 segue aberto.

Este mapa é aditivo e não altera o SDD original, banco, configuração, produção ou mídia.
