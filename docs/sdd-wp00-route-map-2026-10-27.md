# WP-00 — mapa estático de rotas na `main` (27/10/2026)

**Baseline:** `main` em `cb369c97e9f9fb175392f4341296b50d3f42476e`.

A extração estática registrou **223 rotas HTTP declaradas em 25 módulos**. Os prefixos dos routers foram combinados com os caminhos das funções e os routers aninhados do Creator foram expandidos. O inventário abaixo é reproduzível a partir do código; não representa uma captura dinâmica de OpenAPI nem prova que cada rota esteja ativa na imagem implantada.

Verificação estrutural: a contagem AST dos decorators HTTP no baseline encontrou 223 operações em 25 módulos e coincide com as 223 linhas do inventário. A construção dinâmica local de `app.openapi()` também encontrou 223 operações em 199 caminhos, cobrindo os prefixos e routers montados pelo código. Isso valida o registro local da aplicação, mas não valida a imagem implantada.

## Regras de acesso encontradas no código

- O middleware HTTP global de `studio/api.py` exige sessão válida ou autenticação Basic de administrador da plataforma em rotas privadas; sem sessão, páginas web redirecionam para login e APIs respondem 401.
- A allowlist pública inclui `/health`, páginas de login, `/static/*` e rotas de autenticação de capacidade, cadastro, login, verificação e recuperação/reset de senha. Requisições mutáveis também passam pela verificação de `Origin` antes dessa allowlist.
- Nas sessões, `viewer` não pode fazer mutações (com exceção do logout e troca de workspace); `creator` tem mutações limitadas a tracks, Creator e autenticação; `operator` tem mutações limitadas às rotas de operação de canais e MiniOBS; mudanças de settings e todas as rotas de membros exigem papel administrativo.
- O fallback de Basic admin é um caminho distinto: o middleware autoriza a requisição sem definir `req.state.identity` nem o contexto de workspace e não aplica os filtros de papel/CSRF da sessão. Cada handler precisa ser revisado para confirmar como trata esse caminho; o mapa abaixo descreve só a política global, não uma garantia de autorização funcional.
- Algumas operações verificam autorização adicional dentro dos próprios handlers (por exemplo, gestão/publicação no YouTube e direitos de mídia). O middleware global não substitui a auditoria por endpoint nem demonstra isolamento de cada consulta ao banco.
- A tentativa read-only sem sessão de obter `/openapi.json` retornou 401; não foi obtido catálogo dinâmico. `GET /health` não foi chamado.
- As suítes usam `LOFI_TEST_DATABASE_URL` e gravam/limpam o banco configurado. A variável não estava configurada inicialmente; para validar sem risco apontei os testes a um PostgreSQL temporário local, isolado e descartável em `127.0.0.1:55439`, sem usar banco compartilhado. A suíte de autenticação passou (23 testes), a de publicação YouTube passou (11) e a execução completa de `tests/` passou (282 testes, 3 avisos de depreciação). Isso não equivale a concluir os aceites TEST-01…TEST-41 nem prova paridade com produção ou homologação visual.

## Revisão estática dos handlers de YouTube/publicação

Escopo desta revisão: `studio/youtube.py` e `studio/youtube_publish.py` no baseline identificado no cabeçalho. São fatos extraídos do código; não confirmam que o mesmo conteúdo esteja em todas as imagens nem substituem teste de autorização no runtime.

| Rotas | Verificação no handler | Escopo do dado e efeito | Lacuna de evidência |
|---|---|---|---|
| `GET /api/youtube/capabilities` | Sem checagem própria de ator | Retorna capacidade/configuração; depende integralmente do middleware | Verificar papel/sessão no runtime; não é rota pública na allowlist atual. |
| `POST /api/youtube/channels/{cid}/connect` | `user_ref(request)` exige identidade de sessão; `profile(c,cid)` localiza o canal; bloqueia reconexão durante fila/envio | Grava estado OAuth ligado ao usuário e canal; não inicia publicação | Não há matriz executada de papéis/workspace para OAuth. Basic admin não passa por `user_ref` com identidade de sessão. |
| `GET /api/youtube/oauth/callback` | Exige sessão; compara usuário do callback com estado OAuth de uso único, não expirado | Troca código OAuth e grava credencial criptografada | Requer confirmação dinâmica de retorno com sessão/workspace; o teste de papéis não foi executado. |
| `GET /api/youtube/channels` | Sem `profile` por canal | Consulta credenciais na conexão/schema corrente e devolve metadados/flags, não token | A separação depende da seleção de schema pelo middleware; falta teste explícito de isolamento para este endpoint e do fallback Basic. |
| `DELETE /api/youtube/channels/{cid}` | Exige confirmação e `profile(c,cid)`; bloqueia fila/envio ativos | Remove credencial e estado OAuth local; não revoga permissão no Google | Testar papéis e workspace em PostgreSQL descartável; preservar a distinção entre desconectar e revogar no provedor. |
| `GET /api/youtube/publications` | Sem checagem própria por canal/ator | Lista até 100 publicações na conexão/schema corrente; não seleciona `session_encrypted` | O isolamento é implícito em `db()`/workspace; confirmar cross-workspace e Basic admin no runtime. |
| `GET /api/youtube/publications/pilots/candidates` | `profile(c,channel_id)` e filtros de aprovação, prontidão técnica e ausência de publicação | Só consulta pilotos aprovados daquele canal | Falta matriz de papéis e teste autenticado contra imagem implantada. |
| `POST /api/youtube/publications` | `profile`; confirma canal do export; requer revisão/direitos, recibo Growth, hash de snapshot/revisão, proveniência, deduplicação e escopo OAuth de upload | Registra fila; não faz upload síncrono na rota | Há testes de criação/idempotência e isolamento entre usuários, mas não uma matriz completa de papéis nem runtime autenticado. |
| `POST /api/youtube/publications/{jid}/authorize-ready` | Consulta o ID dentro da conexão corrente; exige estado `ready`, piloto aprovado/pronto, hash igual, recibo Growth, proveniência, deduplicação e escopo de upload | Confirma metadados/visibilidade e muda para fila | Não há checagem `profile` explícita; depende do escopo de schema. Falta cobertura de cross-workspace/Basic. |
| `POST /api/youtube/publications/{jid}/release` | Exige confirmação, estado `held` e validação de duplicata | Apenas muda estado para `queued`; não chama YouTube nesse handler | Sem `profile` explícito; provar isolamento e autorização de papel. Upload posterior depende do worker. |
| `POST /api/youtube/publications/{jid}/delete` | Exige confirmação, estado `uploaded`, ID externo e escopo OAuth de gerenciamento | Faz DELETE remoto no YouTube; só atualiza estado local após resposta de sucesso ou vídeo já ausente | Sem `profile` explícito; o acesso depende do workspace na conexão. Teste cobre confirmação e escopo de gerenciamento; falta matriz completa de papéis/Basic. |
| `POST /api/youtube/publications/{jid}/metadata` | Exige confirmação, vídeo `uploaded`, escopo OAuth de gerenciamento; preserva os campos existentes do snippet que não altera | Faz GET/PUT remoto do snippet e depois grava metadados locais | Sem `profile` explícito; falta matriz de papéis/Basic e validação na imagem instalada. |
| `POST /api/youtube/publications/{jid}/retry` | Só falha sem ID de vídeo, sessão e bytes enviados; exige mesma conta do YouTube reconectada depois da tentativa e escopo de upload | Reenfileira uma tentativa segura | Sem `profile` explícito; política depende do escopo workspace. Falta teste de papéis e isolamento por endpoint. |
| `POST /api/youtube/publications/{jid}/resume` | Só estado `interrupted` com sessão resumível | Reenfileira; o worker valida credencial/escopo novamente antes do envio | Sem checagem explícita de perfil no handler. O worker protege o acesso externo, mas a autorização da rota precisa de teste cross-workspace e por papel. |
| `GET /api/youtube/publications/pilots/{pid}/draft` | Se encontra o piloto, exige `profile`, aprovação e prontidão técnica | Produz rascunho de metadados usando os dados do piloto/canal | Verificar respostas e escopo no runtime; o teste atual cobre leitura por outro workspace apenas com resposta 409. |
| `POST /api/youtube/publications/pilots/{pid}/prepare` | `profile` do canal informado, piloto vinculado ao mesmo canal, aprovação e prontidão | Cria entrada `ready` revisável; audit declara `upload_started: false` | Há teste de preparação de entrada, mas não cobertura completa de papéis/Basic. |
| `POST /api/youtube/publications/pilots/{pid}` | `profile`, vínculo piloto/canal, aprovação, confirmação explícita, recibo Growth, frase/contexto, proveniência, deduplicação e escopo OAuth de upload | Registra autorização e enfileira publicação do arquivo aprovado | Testes cobrem criação/idempotência e tentativa por outro workspace; falta matriz de papéis/runtime e provar paridade com a imagem ativa. |

### Interpretação do middleware para estas rotas

Todas as rotas acima estão fora da allowlist pública e, portanto, dependem da sessão ou Basic admin do middleware. Em uma sessão com `workspace_id`, `WORKSPACE` vem da identidade autenticada e `db()` restringe `search_path` ao schema daquele workspace, sem fallback a `public`. Sessões sem workspace usam `LOFI_WORKSPACE_ID` se configurado; caso contrário, a conexão fica no schema padrão (`public`). O middleware também aplica papéis às mutações e verifica CSRF. No fallback Basic, ele não define identidade/workspace e não aplica os filtros de papel/CSRF da sessão; a conexão usa o mesmo escopo padrão, que pode vir de `LOFI_WORKSPACE_ID` ou `public`. Isso é um caminho privilegiado distinto e precisa ser coberto explicitamente, endpoint a endpoint, antes de declarar G4-02/G4-11 atendidos.

### Cobertura estática identificada nos testes

`tests/test_authentication.py` passou (23 testes) e cobre lista privada por workspace, tentativas com IDs de outro workspace e leitura de rascunho de piloto entre workspaces. A nova regressão `test_approved_pilot_reappears_as_library_candidate_and_prepare_is_recoverable` usa TestClient, usuário autenticado, CSRF e PostgreSQL descartável para percorrer aprovação explícita → endpoint de candidatos da Biblioteca → preparação repetida; confirma candidato único, mesma publicação `ready`, hash do piloto preservado, zero bytes enviados e sem ID remoto. Ela comprova integração entre endpoints, mas não valida a renderização visual da Biblioteca em navegador nem falha/reinício entre etapas. `tests/test_youtube_publish.py` passou (11 testes), incluindo regressão unitária complementar de retry. A suíte completa em `tests/` passou (282 testes, 3 avisos de depreciação). A regressão `test_workspace_admin_cannot_manage_members_or_touch_other_workspace` cobre listagem permitida ao workspace admin, mutações negadas para esse papel e para Basic admin, além de alvo fora do workspace. Ainda não há matriz abrangente `viewer`/`creator`/`operator`/`workspace_admin`/Basic para cada rota listada nem paridade autenticada com a imagem implantada.

**Resultado WP-00:** a análise estática avançou nos handlers de YouTube/publicação e autenticação/membros; paridade de imagem, autorização dinâmica por endpoint, cobertura completa de papéis, Basic admin e isolamento runtime continuam pendentes. A presença de `profile()`, `management_identity()` ou do middleware não prova sozinha cada autorização em execução.

## Revisão estática de autenticação, workspaces e membros

Escopo desta revisão: handlers de `studio/authentication.py` e testes correspondentes em `tests/test_authentication.py`, na mesma baseline indicada no cabeçalho. Esta leitura não executa endpoints nem confirma qual revisão está ativa em cada serviço.

| Grupo de rotas | Checagem do handler | Escopo/efeito | Cobertura encontrada e lacuna |
|---|---|---|---|
| `/capabilities`, `/register`, `/verify`, `/login`, `/forgot-password`, `/reset-password` | Públicas pela allowlist; limites por IP em operações sensíveis; tokens de uso único/expiração; recuperação responde de modo não enumerável | Criam/verificam conta, emitem instruções de e-mail, atualizam senha e revogam sessões do usuário | Há teste de cadastro indisponível e fluxo de recuperação/verificação/replay; não há matriz dinâmica contra runtime implantado nem teste de limites concorrentes. |
| `/admin-login` | Pública pela allowlist e compara usuário/senha administrativos em tempo constante | Cria sessão de `platform_admin`, separada da sessão de usuário | `test_platform_cookie_keeps_legacy_workspace_and_logout` verifica login/cookie e acesso legado; falta validação na imagem ativa e matriz de tentativa/limite. |
| `/me`, `/workspaces` | Exigem cookie de sessão válido; plataforma recebe lista vazia de workspaces; sessão comum lista somente associações daquele usuário | Expõe identidade mínima e memberships | Testes exercitam workspace switch e páginas/login sem conceder API; não há teste de enumeração entre contas em cada handler nem validação no runtime. |
| `POST /workspace` | Exige sessão não-plataforma e membership explícito no workspace de destino | Atualiza o workspace da sessão | `test_membership_last_owner_and_workspace_switch` cobre destino sem associação e troca para workspace em que o usuário é membro; falta comprovar resolução de schema e sessão atualizada em execução. |
| `GET /members` | `management_identity` aceita somente `workspace_owner` ou `workspace_admin`; consulta memberships pelo `workspace_id` da identidade | Lista membros do workspace corrente | `test_workspace_admin_cannot_manage_members_or_touch_other_workspace` confirma leitura para admin; `test_membership_last_owner_and_workspace_switch` confirma bloqueio para viewer. Falta cenário de troca e leitura em imagem ativa. |
| `PUT /members`, `POST /members` | Exigem sessão owner; `workspace_admin` é barrado no próprio handler. Edição serializa por advisory lock e impede remover o último owner. Novo membro precisa ter conta verificada; não permite atribuir `workspace_owner` pelo endpoint de inclusão | Altera papel ou adiciona membership no workspace corrente; registra auditoria | `test_membership_last_owner_and_workspace_switch` cobre proteção do último owner e inclusão por owner; `test_workspace_admin_cannot_manage_members_or_touch_other_workspace` confirma admin/Basic negados e alvo sem membership retorna 404. Concorrência simultânea do último owner e papéis inválidos continuam sem teste dedicado. |
| `POST /logout` | O handler apaga sessões de usuário e plataforma pelo hash do cookie; CSRF/origin mutável são aplicados pelo middleware de sessão | Encerra a sessão e apaga cookies | Testes cobrem logout de plataforma e recusa de origem não confiável para viewer; faltam casos de logout de sessão workspace e confirmação com a imagem implantada. |

### Limite entre a identidade da aplicação e Basic admin

`management_identity()` exige objeto de sessão com papel `workspace_owner` ou `workspace_admin`; por isso, a sessão `platform_admin` e a autenticação HTTP Basic não recebem gestão de membros por esse helper. `workspaces()` trata explicitamente sessão de plataforma como lista vazia, enquanto `/workspace` rejeita sessão de plataforma. O Basic admin continua no caminho privilegiado legado do middleware para rotas que não exigem identidade dentro do handler. Essa distinção não substitui auditoria de cada handler nem estabelece que o comportamento observado no código corresponda às imagens implantadas.

### Resultado desta fatia

A leitura estática identificou checagens de ator e workspace em autenticação/membros; as 280 verificações automatizadas de `tests/` passaram no PostgreSQL temporário. Isso ainda não fecha autorização dinâmica em toda a superfície nem paridade com produção. Próxima validação: cobrir concorrência simultânea do último owner, papel inválido, schema e identidade após troca de workspace, e comparar a matriz por handler com cada imagem/runtime.

## Revisão estática do caminho de revisão até biblioteca/publicação

Escopo: rotas de `studio/workshop_api.py`, `studio/ambient_api.py`, `studio/youtube_publish.py` e `studio/exports.py`, componentes versionados em `frontend/src/features/` e testes relacionados. O mapa descreve o contrato no código; a jornada ainda precisa de reprodução autenticada na aplicação implantada.

| Etapa | Comportamento encontrado | Evidência / lacuna em relação ao SDD |
|---|---|---|
| Revisar asset do clipe | `POST /api/creator/workshop/projects/{pid}/clips/{cid}/review/{kind}` valida hash/assinatura, identidade e, para vídeo, prévias de emenda; grava aprovação no registro do asset | Testes cobrem aprovação/revisão de variantes e integridade. Isso aprova asset intermediário, não promove o render final à biblioteca de publicação. |
| Revisar render final do projeto | `POST /api/creator/workshop/projects/{pid}/renders/{tid}/review` confirma que o job completo, hash e snapshot do projeto ainda correspondem; atualiza `factory_tasks.payload.approved/review_sha256/review_note` | Não cria nem atualiza `visual_library`, `export_jobs` ou `youtube_publications`. A transação registra a revisão somente no job de render. |
| Incluir clipe na biblioteca visual | `POST /api/creator/workshop/projects/{pid}/clips/{cid}/library` exige vídeo aprovado e insere cópia imutável em `visual_library`; `/library/{lid}` reutiliza material compatível dentro de projeto do mesmo canal | A inclusão é um endpoint separado da aprovação. O `INSERT` sempre usa novo UUID; tabela sem chave natural/única e handler sem idempotency key. `tests/test_visual_workshop.py` e `tests/test_workshop_variants.py` cobrem salvar/reutilizar uma vez, não repetição, recuperação de falha ou promoção do render completo. |
| Aprovar piloto ambiental | `POST /api/ambient/pilots/{pid}/approve` atualiza `status`, `approved_at` e sinais de revisão humana; a interface de episódios diz que a ação não publica | A aprovação separa revisão visual de publicação. A tela Biblioteca consulta candidatos aprovados via API de publicações; a preparação cria uma entrada `ready`, sem envio. |
| Revisar export tradicional | `POST /api/exports/{jid}/review` valida bytes/hash e snapshot atual, grava `export_reviews` e `program_reviews`; `GET /api/exports` lista jobs | É outro fluxo de exportação. Não compartilha a promoção de `visual_library`; a paridade entre essa lista e a “Biblioteca” visual da UI permanece a descobrir. |
| Aprovar piloto ambiental e encontrá-lo na Biblioteca | A Caixa de Revisão envia `POST /api/ambient/pilots/{pid}/approve`; a Biblioteca consulta `GET /api/youtube/publications/pilots/candidates?channel_id=…`, que lista pilotos aprovados sem publicação vinculada e filtra por `ready_pilot`. “Preparar para publicar” chama `POST /api/youtube/publications/pilots/{pid}/prepare` | A UI versionada confirma a ligação Revisão → candidato na Biblioteca. `test_approved_pilot_reappears_as_library_candidate_and_prepare_is_recoverable` percorre os endpoints autenticados com PostgreSQL descartável; verifica candidato único após aprovação explícita e reconsulta, hash preservado, entrada `ready` idempotente, sem bytes enviados/ID remoto. Ainda falta verificar no navegador a renderização visual após reload, recuperação após reinício/falha entre aprovação e listagem e paridade com a imagem implantada. |

**Achado WP-00 / G1-02 (revisado):** para pilotos ambientais, o código versionado e a regressão integrada confirmam o caminho de API Revisão → candidato único na Biblioteca → entrada `ready` idempotente. O hash do arquivo permanece vinculado à publicação e não há upload antes da autorização posterior. A prova não cobre a tela renderizada em navegador, interrupção/reinício entre etapas ou paridade com a imagem implantada. O render completo do Visual Workshop e a `visual_library` são fluxos de edição/reuso separados, não a Biblioteca de publicação. Próximo gate WP-00/WP-03: completar a checagem visual autenticada e testar recuperação após falha/reinício sem novo upload; então decidir se alguma correção funcional é necessária. Isso alimenta TEST-01/02/33 sem declarar esses cenários completos.

## Reprodução somente de leitura: vídeo de Halloween

Em 27/10/2026, a Biblioteca autenticada mostrou um registro de publicação para o vídeo de Halloween ligado a um ID do YouTube. No YouTube Studio, o vídeo correspondente estava **Público**, com duração de **1:01:01** e os indicadores de qualidade **SD e HD concluídos**. A tela da plataforma indicava que o YouTube recebeu o arquivo; a inspeção remota confirmou que o processamento de HD também terminou. Não houve edição, salvamento ou novo envio.

Essa evidência encerra a dúvida sobre o estado atual desse vídeo específico: ele está publicado e processado no YouTube. Ela não prova o histórico do percentual de envio, a correção dos estados dos outros vídeos, nem o comportamento de recuperação entre a API da plataforma e o YouTube. Esses pontos continuam sujeitos aos cenários G1-03/04 e TEST-02/34.

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
