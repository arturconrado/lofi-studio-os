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

## Finanças — risco a reproduzir antes de declarar WP-02 coberto

`studio/financial.py` consolida reservas de `jobs`, `factory_tasks`, `creator_plans`, `production_batches` e `productions`, sob o teto lido de `studio_config`. A conexão de workspace, porém, configura `search_path` apenas para o schema `ws_<uuid>`. A rotina condiciona a leitura de `creator_plans`/`production_batches` a `to_regclass('public.creator_plans')` e depois soma nomes não qualificados.

Isso cria uma **lacuna potencial de cobertura**: se a tabela só existir no schema do workspace, o teste `to_regclass('public.creator_plans')` não a reconhece e a reserva do tenant pode ficar fora do total consultado. Se existir em `public`, consultas não qualificadas dentro do schema exclusivo também precisam ser validadas cuidadosamente. Não tratamos isso como bug reproduzido: `tests/test_financial.py` atual verifica a guarda com `total_usage` substituído por mock, não testa esse SQL contra schemas separados.

O código de `studio/workshop_api.py` também consulta `visual_project_budgets` apenas se ela existir; não encontramos `CREATE TABLE` correspondente na `main` baseline. Pode ser estrutura legada/out-of-band ou caminho morto. Comparar com schema real sem ler conteúdo de usuário e cobrir com teste isolado antes de alterar.

**Próximo gate WP-02:** adicionar um cenário de dois schemas isolados com `studio_config`, `creator_plans`, reservas e produção pendente; demonstrar que o teto é correto no mesmo workspace, que outro tenant não vaza saldo e que transações concorrentes não excedem o limite. Só então corrigir o caminho necessário em branch/PR. Não executar geração paga.

## Lacunas que continuam em WP-00

- Obter lista read-only de tabelas/schema efetivamente instalados e reconciliar com os 57 identificadores do código; mapear migrações, chaves/foreign keys, soft delete e dados que não podem ser removidos.
- Mapear qual imagem/processo atende cada rota e qual arquivo Compose/release configura os workers ativos, com atenção especial a publisher, rádio e music-worker.
- Resolver o caminho real de cada compositor (criação, prévia, render, Shorts e exportação) e os contratos que compartilham.
- Atualizar o inventário do corpus de mídia com proveniência/acesso em armazenamento privado; referências visuais históricas não substituem inspeção dos objetos atuais.
- Reproduzir em staging/simuladores os relatos e jornadas do SDD. O snapshot de 24/10 ainda não foi restaurado de forma isolada; TEST-27 segue aberto.

Este mapa é aditivo e não altera o SDD original, banco, configuração, produção ou mídia.
