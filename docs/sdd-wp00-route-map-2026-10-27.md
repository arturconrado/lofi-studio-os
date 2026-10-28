# WP-00 — mapa estático de rotas na `main` (27/10/2026)

**Baseline:** `main` em `cb369c97e9f9fb175392f4341296b50d3f42476e`.

A extração estática registrou **223 rotas HTTP declaradas em 25 módulos**. Os prefixos dos routers foram combinados com os caminhos das funções e os routers aninhados do Creator foram expandidos. O inventário abaixo é reproduzível a partir do código; não representa uma captura dinâmica de OpenAPI nem prova que cada rota esteja ativa na imagem implantada.

Verificação estrutural read-only: a contagem AST dos decorators HTTP no baseline encontrou 223 operações em 25 módulos e coincide com as 223 linhas do inventário. Isso valida quantidade e cobertura dos decorators, mas não valida por si só os caminhos concatenados nem a imagem implantada.

## Regras de acesso encontradas no código

- O middleware HTTP global de `studio/api.py` exige sessão válida ou autenticação Basic de administrador da plataforma em rotas privadas; sem sessão, páginas web redirecionam para login e APIs respondem 401.
- A allowlist pública inclui `/health`, páginas de login, `/static/*` e rotas de autenticação de capacidade, cadastro, login, verificação e recuperação/reset de senha. Requisições mutáveis também passam pela verificação de `Origin` antes dessa allowlist.
- Nas sessões, `viewer` não pode fazer mutações (com exceção do logout e troca de workspace); `creator` tem mutações limitadas a tracks, Creator e autenticação; `operator` tem mutações limitadas às rotas de operação de canais e MiniOBS; mudanças de settings e todas as rotas de membros exigem papel administrativo.
- O fallback de Basic admin é um caminho distinto: o middleware autoriza a requisição sem definir `req.state.identity` nem o contexto de workspace e não aplica os filtros de papel/CSRF da sessão. Cada handler precisa ser revisado para confirmar como trata esse caminho; o mapa abaixo descreve só a política global, não uma garantia de autorização funcional.
- Algumas operações verificam autorização adicional dentro dos próprios handlers (por exemplo, gestão/publicação no YouTube e direitos de mídia). O middleware global não substitui a auditoria por endpoint nem demonstra isolamento de cada consulta ao banco.
- A tentativa read-only sem sessão de obter `/openapi.json` retornou 401; não foi obtido catálogo dinâmico. `GET /health` não foi chamado.
- A suíte `tests/test_authentication.py` exige `LOFI_TEST_DATABASE_URL` e executa gravações/limpeza no banco configurado. Essa variável não está disponível nesta sessão; não rodei a suíte nem apontei testes para qualquer banco compartilhado. A matriz de papéis precisa de execução em PostgreSQL descartável antes do aceite.

## Rotas declaradas

| Módulo | Método | Caminho efetivo | Linha no código | Política global estática |
|---|---|---|---|
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots` | 11 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/ambient_api.py` | `POST` | `/api/ambient/pilots/{pid}/approve` | 26 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots/{pid}/assets/{kind}` | 53 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots/{pid}/hour-plan` | 45 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots/{pid}/video` | 17 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/ambient_api.py` | `GET` | `/api/ambient/programs/{bid}/tracklist` | 33 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/` | 93 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/admin/login` | 432 | Pública pela allowlist do middleware |
| `studio/api.py` | `GET` | `/api/assets/{aid}/audio` | 194 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `POST` | `/api/assets/{aid}/qc` | 377 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `GET` | `/api/assets/{aid}/qc/history` | 393 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `POST` | `/api/assets/{aid}/qc/inspect` | 384 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `POST` | `/api/assets/{aid}/review` | 397 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `GET` | `/api/audit` | 364 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/api/budget` | 310 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/api/catalog` | 251 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/api/dashboard` | 124 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/api/jobs` | 326 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `POST` | `/api/jobs/{jid}/cancel` | 330 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `GET` | `/api/models` | 261 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/api/programs/{bid}/rights` | 213 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/api/settings` | 266 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `PUT` | `/api/settings` | 279 | Sessão: owner/admin/plataforma; Basic admin: handler pendente |
| `studio/api.py` | `GET` | `/api/status` | 105 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/api/tracks` | 132 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `POST` | `/api/tracks` | 148 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `PUT` | `/api/tracks/{tid}` | 339 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/approve` | 219 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `GET` | `/api/tracks/{tid}/assets` | 190 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/assets/{aid}/reject` | 354 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/generate` | 163 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/revoke` | 244 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/api.py` | `GET` | `/health` | 77 | Pública pela allowlist do middleware |
| `studio/api.py` | `GET` | `/legacy` | 102 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/login` | 435 | Pública pela allowlist do middleware |
| `studio/api.py` | `GET` | `/program-player.html` | 406 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/studio` | 96 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/api.py` | `GET` | `/studio/{rest:path}` | 99 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/authentication.py` | `POST` | `/api/auth/admin-login` | 235 | Pública pela allowlist do middleware |
| `studio/authentication.py` | `GET` | `/api/auth/capabilities` | 116 | Pública pela allowlist do middleware |
| `studio/authentication.py` | `POST` | `/api/auth/forgot-password` | 208 | Pública pela allowlist do middleware |
| `studio/authentication.py` | `POST` | `/api/auth/login` | 159 | Pública pela allowlist do middleware |
| `studio/authentication.py` | `POST` | `/api/auth/logout` | 195 | Sessão + CSRF; exceção aos filtros viewer/operator; Basic admin: handler pendente |
| `studio/authentication.py` | `GET` | `/api/auth/me` | 189 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/authentication.py` | `GET` | `/api/auth/members` | 278 | Sessão: owner/admin/plataforma; Basic admin: handler pendente |
| `studio/authentication.py` | `POST` | `/api/auth/members` | 316 | Sessão: owner/admin/plataforma; Basic admin: handler pendente |
| `studio/authentication.py` | `PUT` | `/api/auth/members` | 293 | Sessão: owner/admin/plataforma; Basic admin: handler pendente |
| `studio/authentication.py` | `POST` | `/api/auth/register` | 121 | Pública pela allowlist do middleware |
| `studio/authentication.py` | `POST` | `/api/auth/reset-password` | 219 | Pública pela allowlist do middleware |
| `studio/authentication.py` | `POST` | `/api/auth/verify` | 150 | Pública pela allowlist do middleware |
| `studio/authentication.py` | `POST` | `/api/auth/workspace` | 264 | Sessão + associação ao workspace no handler; Basic admin: handler pendente |
| `studio/authentication.py` | `GET` | `/api/auth/workspaces` | 251 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/autopilot.py` | `POST` | `/api/autopilot/pause` | 91 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/autopilot.py` | `PUT` | `/api/autopilot/settings` | 55 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/autopilot.py` | `POST` | `/api/autopilot/start` | 78 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/autopilot.py` | `GET` | `/api/autopilot/status` | 22 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/channels.py` | `GET` | `/api/channels/` | 60 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/channels.py` | `POST` | `/api/channels/` | 71 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/channels.py` | `PUT` | `/api/channels/{cid}` | 76 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/channels.py` | `PUT` | `/api/channels/{cid}/preferences` | 109 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/channels.py` | `PUT` | `/api/channels/{cid}/settings` | 93 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/channels.py` | `POST` | `/api/channels/{cid}/start` | 122 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/channels.py` | `GET` | `/api/channels/{cid}/status` | 81 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/channels.py` | `POST` | `/api/channels/{cid}/stop` | 151 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `GET` | `/api/creator/catalog` | 314 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/creator.py` | `GET` | `/api/creator/music-styles` | 309 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/creator.py` | `POST` | `/api/creator/plan` | 58 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `GET` | `/api/creator/plans` | 14 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/creator.py` | `GET` | `/api/creator/pose-library` | 360 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/creator.py` | `POST` | `/api/creator/produce` | 158 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `GET` | `/api/creator/programs/{bid}/metadata` | 200 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/creator.py` | `PUT` | `/api/creator/programs/{bid}/metadata` | 205 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `POST` | `/api/creator/programs/{bid}/suggest` | 215 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `POST` | `/api/creator/storyboard` | 247 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `POST` | `/api/creator/storyboard/save` | 266 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `PUT` | `/api/creator/tracks/{tid}/copy` | 233 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/creator.py` | `POST` | `/api/creator/tracks/{tid}/suggest` | 222 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/episode_api.py` | `GET` | `/api/episodes/channels/{cid}` | 37 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/episode_api.py` | `PUT` | `/api/episodes/series/{sid}/calendar` | 74 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/episode_api.py` | `PUT` | `/api/episodes/{eid}` | 48 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/episode_api.py` | `GET` | `/api/episodes/{eid}/history` | 64 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/event_proposals.py` | `POST` | `/event-proposals/` | 106 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/event_proposals.py` | `POST` | `/event-proposals/apply` | 126 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/events.py` | `GET` | `/api/events/` | 114 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/exports.py` | `GET` | `/api/exports/` | 39 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/exports.py` | `POST` | `/api/exports/` | 46 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/exports.py` | `GET` | `/api/exports/{jid}/download` | 68 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/exports.py` | `GET` | `/api/exports/{jid}/preview` | 80 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/exports.py` | `POST` | `/api/exports/{jid}/retry` | 116 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/exports.py` | `POST` | `/api/exports/{jid}/review` | 91 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/form_assistant.py` | `POST` | `/form-assist/` | 96 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/channel-observations` | 314 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/channel-observations` | 322 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/experiments` | 591 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/experiments` | 598 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/growth.py` | `PUT` | `/api/growth/{cid}/experiments/{eid}` | 607 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/metadata-context` | 446 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/opportunities` | 422 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/package-suggestion` | 458 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/projections` | 557 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/reference-comparison` | 583 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/references` | 566 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/references` | 573 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/snapshots` | 295 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/snapshots` | 302 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/harness_profiles.py` | `GET` | `/harness-profiles/{cid}` | 92 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/harness_profiles.py` | `POST` | `/harness-profiles/{cid}` | 100 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/inbox.py` | `GET` | `/inbox/` | 216 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/copy` | 79 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/live_presentation.py` | `PUT` | `/api/live-presentation/{cid}/copy` | 92 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/motion-study` | 115 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/motion-study/video` | 120 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/live_presentation.py` | `POST` | `/api/live-presentation/{cid}/scenes` | 36 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/sources` | 22 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `POST` | `/api/miniobs/preview` | 260 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs` | 125 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `POST` | `/api/miniobs/programs/{bid}/review` | 99 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs/{bid}/scenes` | 14 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs/{bid}/scenes/{sid}/{kind}` | 20 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `POST` | `/api/miniobs/programs/{bid}/start` | 120 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `PUT` | `/api/miniobs/programs/{bid}/visual` | 30 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs/{bid}/{kind}` | 169 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/scenes` | 238 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `POST` | `/api/miniobs/scenes` | 242 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/scenes/{sid}/preview` | 304 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `PUT` | `/api/miniobs/settings` | 288 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `POST` | `/api/miniobs/start` | 263 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/status` | 193 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `POST` | `/api/miniobs/stop` | 279 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/visuals` | 204 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/miniobs.py` | `POST` | `/api/miniobs/visuals` | 208 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/miniobs.py` | `GET` | `/api/miniobs/visuals/{vid}/image` | 224 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/monetization.py` | `GET` | `/api/monetization/{cid}` | 21 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/monetization.py` | `PUT` | `/api/monetization/{cid}` | 26 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/motion_validation.py` | `GET` | `/motion-validation/` | 193 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/motion_validation.py` | `POST` | `/motion-validation/` | 86 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/motion_validation.py` | `GET` | `/motion-validation/quote` | 66 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/motion_validation.py` | `GET` | `/motion-validation/sources` | 57 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/motion_validation.py` | `POST` | `/motion-validation/{tid}/refresh` | 155 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/motion_validation.py` | `POST` | `/motion-validation/{tid}/review` | 205 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/motion_validation.py` | `GET` | `/motion-validation/{tid}/video` | 185 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/productions.py` | `GET` | `/productions/` | 365 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/productions.py` | `POST` | `/productions/` | 325 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/productions.py` | `GET` | `/productions/legacy` | 374 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/productions.py` | `POST` | `/productions/quote` | 318 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/productions.py` | `GET` | `/productions/{pid}` | 393 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/productions.py` | `POST` | `/productions/{pid}/advance` | 402 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/productions.py` | `POST` | `/productions/{pid}/archive` | 448 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/productions.py` | `POST` | `/productions/{pid}/cancel` | 431 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/productions.py` | `POST` | `/productions/{pid}/permanent-delete` | 457 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/productions.py` | `POST` | `/productions/{pid}/resume` | 410 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/programming.py` | `GET` | `/api/programming/{cid}/queue` | 38 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/programming.py` | `PUT` | `/api/programming/{cid}/queue` | 51 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/recipes.py` | `GET` | `/channels/{cid}/recipes` | 462 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/recipes.py` | `PUT` | `/channels/{cid}/recipes` | 472 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/recipes.py` | `GET` | `/recipes/` | 369 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/recipes.py` | `POST` | `/recipes/` | 388 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/recipes.py` | `GET` | `/recipes/{rid}` | 378 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/archive` | 420 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/preview-copy` | 454 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/revisions` | 400 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/revisions/{revision}/approve-reference` | 432 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/jobs/{jid}/resume` | 496 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/jobs/{jid}/review` | 540 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `GET` | `/assembly/jobs/{jid}/storyboard` | 525 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/timeline_api.py` | `GET` | `/assembly/jobs/{jid}/video` | 517 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}` | 185 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/baseline-motion` | 115 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/clip-briefs` | 247 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/clips/{action}` | 273 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/clips/{cid}/masks` | 598 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/clips/{cid}/review` | 332 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/clips/{cid}/video` | 314 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/economics` | 176 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/identity` | 102 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/identity-sources/{pilot_id}/still` | 234 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/regions` | 427 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/render` | 459 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/reuse` | 57 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/soundtrack` | 352 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `GET` | `/workshop/capabilities` | 1011 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/workshop_api.py` | `GET` | `/workshop/projects` | 113 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects` | 121 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}` | 133 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/workshop_api.py` | `PUT` | `/workshop/projects/{pid}` | 170 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/continuation-image` | 1124 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/generate/{kind}` | 380 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/library` | 526 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/preview` | 651 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/clips/{cid}/quote/{kind}` | 365 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/recover` | 1092 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/review/{kind}` | 291 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/split` | 623 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/split-plan` | 601 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/duplicate` | 1017 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/jobs/{tid}/refresh` | 496 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/jobs/{tid}/retry-render` | 963 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/library/{lid}` | 540 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/media/{aid}` | 509 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/references` | 254 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/render` | 931 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/renders/{tid}` | 985 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/renders/{tid}/review` | 995 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/shorts/render` | 827 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/shorts/{tid}/review` | 885 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/shorts/{tid}/video` | 875 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/youtube.py` | `GET` | `/api/youtube/capabilities` | 44 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/youtube.py` | `GET` | `/api/youtube/channels` | 106 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/youtube.py` | `DELETE` | `/api/youtube/channels/{cid}` | 124 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube.py` | `POST` | `/api/youtube/channels/{cid}/connect` | 47 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube.py` | `GET` | `/api/youtube/oauth/callback` | 67 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/youtube_publish.py` | `GET` | `/api/youtube/publications/` | 128 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/` | 151 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `GET` | `/api/youtube/publications/pilots/candidates` | 135 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/pilots/{pid}` | 632 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `GET` | `/api/youtube/publications/pilots/{pid}/draft` | 558 | Sessão ou Basic admin; escopo do handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/pilots/{pid}/prepare` | 589 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/authorize-ready` | 203 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/delete` | 252 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/metadata` | 286 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/release` | 233 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/resume` | 350 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/retry` | 330 | Sessão + CSRF + filtros globais de papel; Basic admin: handler pendente |

## Limites e próximos passos

- A auditoria não importou o app nem chamou endpoints: o ambiente de leitura não tem a dependência FastAPI instalada. A extração usa AST da fonte e foi confrontada com as 223 declarações `app/router` encontradas por busca textual.
- Este mapa descreve a `main` baseline. A auditoria de produção confirmou múltiplas revisões de imagem; ainda é preciso verificar quais rotas cada serviço expõe e reconciliar permissões e caminhos entre portal antigo e novo.
- Para fechar WP-00, completar uma matriz por endpoint de papel/escopo/regra do handler, comparar com o runtime e registrar jornada de Revisão → Biblioteca → publicação simulada. Este mapa não fecha WP-00 nem TEST-27.
