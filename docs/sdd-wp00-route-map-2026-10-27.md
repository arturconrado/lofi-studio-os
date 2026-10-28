# WP-00 — mapa estático de rotas na `main` (27/10/2026)

**Baseline:** `main` em `cb369c97e9f9fb175392f4341296b50d3f42476e`.

A extração estática registrou **223 rotas HTTP declaradas em 25 módulos**. Os prefixos dos routers foram combinados com os caminhos das funções e os routers aninhados do Creator foram expandidos. O inventário abaixo é reproduzível a partir do código; não representa uma captura dinâmica de OpenAPI nem prova que cada rota esteja ativa na imagem implantada.

## Regras de acesso encontradas no código

- O middleware HTTP global de `studio/api.py` exige sessão válida ou autenticação Basic de administrador da plataforma em rotas privadas; sem sessão, páginas web redirecionam para login e APIs respondem 401.
- A exceção pública inclui `/health`, páginas de login, `/static/*` e rotas de autenticação de capacidade, cadastro, login, verificação e recuperação/reset de senha.
- Nas sessões, `viewer` não pode fazer mutações; `creator` tem mutações limitadas a tracks, Creator e autenticação; `operator` tem mutações limitadas às rotas de operação de canais e MiniOBS; mudanças de settings e rotas de membros exigem papel administrativo.
- Algumas operações verificam autorização adicional dentro dos próprios handlers (por exemplo, gestão/publicação no YouTube e direitos de mídia). O middleware global não substitui a auditoria por endpoint nem demonstra isolamento de cada consulta ao banco.
- `GET /health` consulta dependências; esta coleta não chamou endpoints nem alterou estado.

## Rotas declaradas

| Módulo | Método | Caminho efetivo | Linha no código |
|---|---|---|---|
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots` | 11 |
| `studio/ambient_api.py` | `POST` | `/api/ambient/pilots/{pid}/approve` | 26 |
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots/{pid}/assets/{kind}` | 53 |
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots/{pid}/hour-plan` | 45 |
| `studio/ambient_api.py` | `GET` | `/api/ambient/pilots/{pid}/video` | 17 |
| `studio/ambient_api.py` | `GET` | `/api/ambient/programs/{bid}/tracklist` | 33 |
| `studio/api.py` | `GET` | `/` | 93 |
| `studio/api.py` | `GET` | `/admin/login` | 432 |
| `studio/api.py` | `GET` | `/api/assets/{aid}/audio` | 194 |
| `studio/api.py` | `POST` | `/api/assets/{aid}/qc` | 377 |
| `studio/api.py` | `GET` | `/api/assets/{aid}/qc/history` | 393 |
| `studio/api.py` | `POST` | `/api/assets/{aid}/qc/inspect` | 384 |
| `studio/api.py` | `POST` | `/api/assets/{aid}/review` | 397 |
| `studio/api.py` | `GET` | `/api/audit` | 364 |
| `studio/api.py` | `GET` | `/api/budget` | 310 |
| `studio/api.py` | `GET` | `/api/catalog` | 251 |
| `studio/api.py` | `GET` | `/api/dashboard` | 124 |
| `studio/api.py` | `GET` | `/api/jobs` | 326 |
| `studio/api.py` | `POST` | `/api/jobs/{jid}/cancel` | 330 |
| `studio/api.py` | `GET` | `/api/models` | 261 |
| `studio/api.py` | `GET` | `/api/programs/{bid}/rights` | 213 |
| `studio/api.py` | `GET` | `/api/settings` | 266 |
| `studio/api.py` | `PUT` | `/api/settings` | 279 |
| `studio/api.py` | `GET` | `/api/status` | 105 |
| `studio/api.py` | `GET` | `/api/tracks` | 132 |
| `studio/api.py` | `POST` | `/api/tracks` | 148 |
| `studio/api.py` | `PUT` | `/api/tracks/{tid}` | 339 |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/approve` | 219 |
| `studio/api.py` | `GET` | `/api/tracks/{tid}/assets` | 190 |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/assets/{aid}/reject` | 354 |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/generate` | 163 |
| `studio/api.py` | `POST` | `/api/tracks/{tid}/revoke` | 244 |
| `studio/api.py` | `GET` | `/health` | 77 |
| `studio/api.py` | `GET` | `/legacy` | 102 |
| `studio/api.py` | `GET` | `/login` | 435 |
| `studio/api.py` | `GET` | `/program-player.html` | 406 |
| `studio/api.py` | `GET` | `/studio` | 96 |
| `studio/api.py` | `GET` | `/studio/{rest:path}` | 99 |
| `studio/authentication.py` | `POST` | `/api/auth/admin-login` | 235 |
| `studio/authentication.py` | `GET` | `/api/auth/capabilities` | 116 |
| `studio/authentication.py` | `POST` | `/api/auth/forgot-password` | 208 |
| `studio/authentication.py` | `POST` | `/api/auth/login` | 159 |
| `studio/authentication.py` | `POST` | `/api/auth/logout` | 195 |
| `studio/authentication.py` | `GET` | `/api/auth/me` | 189 |
| `studio/authentication.py` | `GET` | `/api/auth/members` | 278 |
| `studio/authentication.py` | `POST` | `/api/auth/members` | 316 |
| `studio/authentication.py` | `PUT` | `/api/auth/members` | 293 |
| `studio/authentication.py` | `POST` | `/api/auth/register` | 121 |
| `studio/authentication.py` | `POST` | `/api/auth/reset-password` | 219 |
| `studio/authentication.py` | `POST` | `/api/auth/verify` | 150 |
| `studio/authentication.py` | `POST` | `/api/auth/workspace` | 264 |
| `studio/authentication.py` | `GET` | `/api/auth/workspaces` | 251 |
| `studio/autopilot.py` | `POST` | `/api/autopilot/pause` | 91 |
| `studio/autopilot.py` | `PUT` | `/api/autopilot/settings` | 55 |
| `studio/autopilot.py` | `POST` | `/api/autopilot/start` | 78 |
| `studio/autopilot.py` | `GET` | `/api/autopilot/status` | 22 |
| `studio/channels.py` | `GET` | `/api/channels/` | 60 |
| `studio/channels.py` | `POST` | `/api/channels/` | 71 |
| `studio/channels.py` | `PUT` | `/api/channels/{cid}` | 76 |
| `studio/channels.py` | `PUT` | `/api/channels/{cid}/preferences` | 109 |
| `studio/channels.py` | `PUT` | `/api/channels/{cid}/settings` | 93 |
| `studio/channels.py` | `POST` | `/api/channels/{cid}/start` | 122 |
| `studio/channels.py` | `GET` | `/api/channels/{cid}/status` | 81 |
| `studio/channels.py` | `POST` | `/api/channels/{cid}/stop` | 151 |
| `studio/creator.py` | `GET` | `/api/creator/catalog` | 314 |
| `studio/creator.py` | `GET` | `/api/creator/music-styles` | 309 |
| `studio/creator.py` | `POST` | `/api/creator/plan` | 58 |
| `studio/creator.py` | `GET` | `/api/creator/plans` | 14 |
| `studio/creator.py` | `GET` | `/api/creator/pose-library` | 360 |
| `studio/creator.py` | `POST` | `/api/creator/produce` | 158 |
| `studio/creator.py` | `GET` | `/api/creator/programs/{bid}/metadata` | 200 |
| `studio/creator.py` | `PUT` | `/api/creator/programs/{bid}/metadata` | 205 |
| `studio/creator.py` | `POST` | `/api/creator/programs/{bid}/suggest` | 215 |
| `studio/creator.py` | `POST` | `/api/creator/storyboard` | 247 |
| `studio/creator.py` | `POST` | `/api/creator/storyboard/save` | 266 |
| `studio/creator.py` | `PUT` | `/api/creator/tracks/{tid}/copy` | 233 |
| `studio/creator.py` | `POST` | `/api/creator/tracks/{tid}/suggest` | 222 |
| `studio/episode_api.py` | `GET` | `/api/episodes/channels/{cid}` | 37 |
| `studio/episode_api.py` | `PUT` | `/api/episodes/series/{sid}/calendar` | 74 |
| `studio/episode_api.py` | `PUT` | `/api/episodes/{eid}` | 48 |
| `studio/episode_api.py` | `GET` | `/api/episodes/{eid}/history` | 64 |
| `studio/event_proposals.py` | `POST` | `/event-proposals/` | 106 |
| `studio/event_proposals.py` | `POST` | `/event-proposals/apply` | 126 |
| `studio/events.py` | `GET` | `/api/events/` | 114 |
| `studio/exports.py` | `GET` | `/api/exports/` | 39 |
| `studio/exports.py` | `POST` | `/api/exports/` | 46 |
| `studio/exports.py` | `GET` | `/api/exports/{jid}/download` | 68 |
| `studio/exports.py` | `GET` | `/api/exports/{jid}/preview` | 80 |
| `studio/exports.py` | `POST` | `/api/exports/{jid}/retry` | 116 |
| `studio/exports.py` | `POST` | `/api/exports/{jid}/review` | 91 |
| `studio/form_assistant.py` | `POST` | `/form-assist/` | 96 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/channel-observations` | 314 |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/channel-observations` | 322 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/experiments` | 591 |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/experiments` | 598 |
| `studio/growth.py` | `PUT` | `/api/growth/{cid}/experiments/{eid}` | 607 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/metadata-context` | 446 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/opportunities` | 422 |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/package-suggestion` | 458 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/projections` | 557 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/reference-comparison` | 583 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/references` | 566 |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/references` | 573 |
| `studio/growth.py` | `GET` | `/api/growth/{cid}/snapshots` | 295 |
| `studio/growth.py` | `POST` | `/api/growth/{cid}/snapshots` | 302 |
| `studio/harness_profiles.py` | `GET` | `/harness-profiles/{cid}` | 92 |
| `studio/harness_profiles.py` | `POST` | `/harness-profiles/{cid}` | 100 |
| `studio/inbox.py` | `GET` | `/inbox/` | 216 |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/copy` | 79 |
| `studio/live_presentation.py` | `PUT` | `/api/live-presentation/{cid}/copy` | 92 |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/motion-study` | 115 |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/motion-study/video` | 120 |
| `studio/live_presentation.py` | `POST` | `/api/live-presentation/{cid}/scenes` | 36 |
| `studio/live_presentation.py` | `GET` | `/api/live-presentation/{cid}/sources` | 22 |
| `studio/miniobs.py` | `POST` | `/api/miniobs/preview` | 260 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs` | 125 |
| `studio/miniobs.py` | `POST` | `/api/miniobs/programs/{bid}/review` | 99 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs/{bid}/scenes` | 14 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs/{bid}/scenes/{sid}/{kind}` | 20 |
| `studio/miniobs.py` | `POST` | `/api/miniobs/programs/{bid}/start` | 120 |
| `studio/miniobs.py` | `PUT` | `/api/miniobs/programs/{bid}/visual` | 30 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/programs/{bid}/{kind}` | 169 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/scenes` | 238 |
| `studio/miniobs.py` | `POST` | `/api/miniobs/scenes` | 242 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/scenes/{sid}/preview` | 304 |
| `studio/miniobs.py` | `PUT` | `/api/miniobs/settings` | 288 |
| `studio/miniobs.py` | `POST` | `/api/miniobs/start` | 263 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/status` | 193 |
| `studio/miniobs.py` | `POST` | `/api/miniobs/stop` | 279 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/visuals` | 204 |
| `studio/miniobs.py` | `POST` | `/api/miniobs/visuals` | 208 |
| `studio/miniobs.py` | `GET` | `/api/miniobs/visuals/{vid}/image` | 224 |
| `studio/monetization.py` | `GET` | `/api/monetization/{cid}` | 21 |
| `studio/monetization.py` | `PUT` | `/api/monetization/{cid}` | 26 |
| `studio/motion_validation.py` | `GET` | `/motion-validation/` | 193 |
| `studio/motion_validation.py` | `POST` | `/motion-validation/` | 86 |
| `studio/motion_validation.py` | `GET` | `/motion-validation/quote` | 66 |
| `studio/motion_validation.py` | `GET` | `/motion-validation/sources` | 57 |
| `studio/motion_validation.py` | `POST` | `/motion-validation/{tid}/refresh` | 155 |
| `studio/motion_validation.py` | `POST` | `/motion-validation/{tid}/review` | 205 |
| `studio/motion_validation.py` | `GET` | `/motion-validation/{tid}/video` | 185 |
| `studio/productions.py` | `GET` | `/productions/` | 365 |
| `studio/productions.py` | `POST` | `/productions/` | 325 |
| `studio/productions.py` | `GET` | `/productions/legacy` | 374 |
| `studio/productions.py` | `POST` | `/productions/quote` | 318 |
| `studio/productions.py` | `GET` | `/productions/{pid}` | 393 |
| `studio/productions.py` | `POST` | `/productions/{pid}/advance` | 402 |
| `studio/productions.py` | `POST` | `/productions/{pid}/archive` | 448 |
| `studio/productions.py` | `POST` | `/productions/{pid}/cancel` | 431 |
| `studio/productions.py` | `POST` | `/productions/{pid}/permanent-delete` | 457 |
| `studio/productions.py` | `POST` | `/productions/{pid}/resume` | 410 |
| `studio/programming.py` | `GET` | `/api/programming/{cid}/queue` | 38 |
| `studio/programming.py` | `PUT` | `/api/programming/{cid}/queue` | 51 |
| `studio/recipes.py` | `GET` | `/channels/{cid}/recipes` | 462 |
| `studio/recipes.py` | `PUT` | `/channels/{cid}/recipes` | 472 |
| `studio/recipes.py` | `GET` | `/recipes/` | 369 |
| `studio/recipes.py` | `POST` | `/recipes/` | 388 |
| `studio/recipes.py` | `GET` | `/recipes/{rid}` | 378 |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/archive` | 420 |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/preview-copy` | 454 |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/revisions` | 400 |
| `studio/recipes.py` | `POST` | `/recipes/{rid}/revisions/{revision}/approve-reference` | 432 |
| `studio/timeline_api.py` | `POST` | `/assembly/jobs/{jid}/resume` | 496 |
| `studio/timeline_api.py` | `POST` | `/assembly/jobs/{jid}/review` | 540 |
| `studio/timeline_api.py` | `GET` | `/assembly/jobs/{jid}/storyboard` | 525 |
| `studio/timeline_api.py` | `GET` | `/assembly/jobs/{jid}/video` | 517 |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}` | 185 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/baseline-motion` | 115 |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/clip-briefs` | 247 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/clips/{action}` | 273 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/clips/{cid}/masks` | 598 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/clips/{cid}/review` | 332 |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/clips/{cid}/video` | 314 |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/economics` | 176 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/identity` | 102 |
| `studio/timeline_api.py` | `GET` | `/assembly/plans/{pid}/identity-sources/{pilot_id}/still` | 234 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/regions` | 427 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/render` | 459 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/reuse` | 57 |
| `studio/timeline_api.py` | `POST` | `/assembly/plans/{pid}/soundtrack` | 352 |
| `studio/workshop_api.py` | `GET` | `/workshop/capabilities` | 1011 |
| `studio/workshop_api.py` | `GET` | `/workshop/projects` | 113 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects` | 121 |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}` | 133 |
| `studio/workshop_api.py` | `PUT` | `/workshop/projects/{pid}` | 170 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/continuation-image` | 1124 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/generate/{kind}` | 380 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/library` | 526 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/preview` | 651 |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/clips/{cid}/quote/{kind}` | 365 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/recover` | 1092 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/review/{kind}` | 291 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/split` | 623 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/clips/{cid}/split-plan` | 601 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/duplicate` | 1017 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/jobs/{tid}/refresh` | 496 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/jobs/{tid}/retry-render` | 963 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/library/{lid}` | 540 |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/media/{aid}` | 509 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/references` | 254 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/render` | 931 |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/renders/{tid}` | 985 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/renders/{tid}/review` | 995 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/shorts/render` | 827 |
| `studio/workshop_api.py` | `POST` | `/workshop/projects/{pid}/shorts/{tid}/review` | 885 |
| `studio/workshop_api.py` | `GET` | `/workshop/projects/{pid}/shorts/{tid}/video` | 875 |
| `studio/youtube.py` | `GET` | `/api/youtube/capabilities` | 44 |
| `studio/youtube.py` | `GET` | `/api/youtube/channels` | 106 |
| `studio/youtube.py` | `DELETE` | `/api/youtube/channels/{cid}` | 124 |
| `studio/youtube.py` | `POST` | `/api/youtube/channels/{cid}/connect` | 47 |
| `studio/youtube.py` | `GET` | `/api/youtube/oauth/callback` | 67 |
| `studio/youtube_publish.py` | `GET` | `/api/youtube/publications/` | 128 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/` | 151 |
| `studio/youtube_publish.py` | `GET` | `/api/youtube/publications/pilots/candidates` | 135 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/pilots/{pid}` | 632 |
| `studio/youtube_publish.py` | `GET` | `/api/youtube/publications/pilots/{pid}/draft` | 558 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/pilots/{pid}/prepare` | 589 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/authorize-ready` | 203 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/delete` | 252 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/metadata` | 286 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/release` | 233 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/resume` | 350 |
| `studio/youtube_publish.py` | `POST` | `/api/youtube/publications/{jid}/retry` | 330 |

## Limites e próximos passos

- A auditoria não importou o app nem chamou endpoints: o ambiente de leitura não tem a dependência FastAPI instalada. A extração usa AST da fonte e foi confrontada com as 223 declarações `app/router` encontradas por busca textual.
- Este mapa descreve a `main` baseline. A auditoria de produção confirmou múltiplas revisões de imagem; ainda é preciso verificar quais rotas cada serviço expõe e reconciliar permissões e caminhos entre portal antigo e novo.
- Para fechar WP-00, completar uma matriz por endpoint de papel/escopo/regra do handler, comparar com o runtime e registrar jornada de Revisão → Biblioteca → publicação simulada. Este mapa não fecha WP-00 nem TEST-27.
