# Auditoria e otimização de um canal existente

Fluxo nativo do Growth (`/analises` → **Canal no YouTube**) para auditar o canal do YouTube já conectado ao estúdio, revisar propostas de metadados e publicar somente o que foi aprovado e confirmado.
Código: `studio/channel_audit.py`, `frontend/src/features/channel-audit.tsx`. Testes: `tests/test_channel_audit.py`, `frontend/src/__tests__/channel-audit.test.tsx`.

O fluxo usa somente as APIs oficiais do Google e as capturas manuais do YouTube Studio que o Growth já guarda. Não consulta o vidIQ nem gasta créditos dele, não usa LLM, não gera vídeos ou miniaturas e não altera nada sem aprovação.

## Etapas

1. **Identificar o canal.** O usuário informa a URL (`youtube.com/@handle`, `youtube.com/channel/UC…`), o `@handle` ou o ID. O servidor resolve o canal com `channels.list` (`id`, `forHandle` ou `forUsername`) e mostra nome, handle e ID. A auditoria só continua se esse ID for o mesmo da credencial OAuth do estúdio. Endereços `/c/…` e de vídeo são recusados porque a API não os resolve para um canal.
2. **Importar (somente leitura).** O servidor lê o canal (`channels.list`), os envios (`playlistItems.list` na playlist de uploads, até 200 vídeos), os detalhes dos vídeos (`videos.list`) e as playlists (`playlists.list` e `playlistItems.list`, até 25 playlists e 50 itens por playlist). Nada é criado no YouTube.
3. **Auditar.** Os achados são determinísticos:
   - **Marca:** grafias do nome oficial diferentes de `LoFi Vibe Coding` (por exemplo `Lo-Fi Vibe Coding`, `lofi vibe coding`) e termos proibidos (`Tração`) em nome, “Sobre”, palavras-chave, títulos e descrições de vídeos e playlists. Handles e URLs não contam como grafia errada.
   - **Títulos e descrições:** palavras repetidas, separadores empilhados, ausência de gênero ou de uso, descrições vazias ou curtas, abertura que não retoma o tema, repetição excessiva de termos, títulos duplicados e links sem HTTPS.
   - **Regras do canal:** cada vídeo é conferido contra `metadata_issues` (o mesmo contrato de `validate_metadata` em `studio/youtube_metadata.py`). As regras da frase principal só são avaliadas quando a frase está registrada em `youtube_publications`.
   - **Buscas:** termos observados (Analytics `YT_SEARCH` ou capturas do Studio) e buscas pretendidas informadas pelo usuário são comparados só quanto à presença das palavras nos títulos. Isso não mede volume de busca nem promete posição.
   - **Playlists e miniaturas:** canal sem playlists, playlists sem descrição, vídeos públicos fora das playlists lidas. As miniaturas aparecem para revisão visual: a API não diz se são personalizadas nem avalia legibilidade.
4. **Catálogo por vídeo.** Cada vídeo mostra se foi enviado pelo estúdio (`youtube_publications`) ou não, as observações salvas em `analytics_snapshots` associadas pelo ID do vídeo (aceita `watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/`), as métricas ausentes marcadas como **Ausente** (nunca zero), a intenção registrada ou inferida (inferida = hipótese), o resultado das regras e as recomendações.
5. **Propostas.** Correções de grafia viram propostas automáticas (`origin=brand_rule`). Outras propostas são escritas pelo usuário para título ou descrição. O valor atual vem sempre do snapshot importado pelo servidor, e o item precisa existir nesse snapshot: IDs enviados pela interface não são confiáveis.
6. **Aprovação.** Só administradores do workspace aprovam. A aprovação inclui o SHA-256 do texto revisado: se o texto mudou, a aprovação é recusada. Editar uma proposta a devolve para revisão. Sugestões que ainda contenham grafia proibida não podem ser aprovadas.
7. **Publicação.** O usuário seleciona alterações aprovadas, revisa a lista com o antes e o depois e marca “Confirmo publicar estas N alterações”. O servidor exige `confirm_apply=true` e `confirmed_count` igual ao número de IDs. Para cada alteração:
   - relê o item no YouTube; recusa se `snippet.channelId` não for o canal conectado ou se o valor mudou desde a auditoria (`conflict`, nada é enviado);
   - vídeo enviado pelo estúdio: usa a edição existente `POST /api/youtube/publications/{id}/metadata`, que mantém `youtube_publications` sincronizada;
   - demais vídeos e playlists: `videos.update`/`playlists.update` com `part=snippet`, reenviando todos os campos mutáveis lidos (a API apaga os omitidos);
   - descrição/palavras-chave do canal: `channels.update` com `part=brandingSettings`.
8. **Confirmação.** Depois do envio, o servidor relê o campo. Só registra `verified` se o YouTube devolver o valor aprovado; senão registra `unverified`, `failed` ou `conflict`, com o motivo. **Reler no YouTube** repete a leitura a qualquer momento.

## Persistência e proveniência

Tabelas criadas sob demanda (`ensure_once`, por workspace):

- `channel_audit_runs`: cada importação/auditoria, com snapshot completo e SHA-256, regras de marca, dados do Analytics, achados, diagnóstico, proveniência (fontes, endpoints, data da leitura, data da captura manual) e autor. É histórico: nunca é sobrescrita.
- `channel_audit_changes`: propostas com valor atual e sugerido, origem, estado, aprovador, SHA aprovado, valor relido e detalhe do resultado.
- `channel_audit_events`: linha do tempo de cada proposta (`proposed`, `edited`, `approved`, `rejected`, `apply_requested`, `verified`, `unverified`, `failed`, `conflict`).

Eventos relevantes também vão para a tabela `audit` (`CHANNEL_AUDIT_CREATED`, `CHANNEL_AUDIT_CHANGE_*`). Tokens continuam cifrados em `channel_credentials` e nunca aparecem em respostas, eventos ou logs. Erros do Google são guardados só como código HTTP e `reason`.

## Permissões OAuth

| Recurso | Escopo | Quando é pedido |
|---|---|---|
| Identificar, importar e auditar | `youtube.readonly` | Já faz parte da conexão padrão |
| Tráfego, retenção e termos de busca | `yt-analytics.readonly` | Botão “Autorizar leitura do Analytics” (opcional) |
| Publicar alterações aprovadas | `youtube.force-ssl` | Botão “Autorizar edição de metadados”; não inclui upload |

Ao pedir uma permissão nova, a tela repete na URL de consentimento as permissões que o canal já tem (upload/exclusão), porque o estúdio guarda só o token mais recente. A edição de metadados de publicações registradas (`/api/youtube/publications/{id}/metadata`) passou a exigir apenas o escopo de gerenciamento, sem exigir upload. Reconectar pela tela Canais continua pedindo upload e, se escolhido, exclusão. Nesse caso, Analytics e edição precisam ser autorizados de novo na aba Canal no YouTube.

O projeto do Google Cloud precisa ter a **YouTube Data API v3** e a **YouTube Analytics API** ativadas, e os escopos acima declarados na tela de consentimento OAuth. Escopos sensíveis podem exigir verificação do app pelo Google antes do uso fora do modo de teste.

## Limitações das APIs (verificadas na documentação oficial em 2026-11-02)

- **Nome do canal e handle:** `channels.update` só altera `brandingSettings` (descrição, palavras-chave, país, idioma, trailer), `invideoPromotion` e `localizations`. O título precisa ser mantido. O handle não é editável. O fluxo gera instruções para o YouTube Studio e confirma relendo o canal.
- **Links da seção Sobre:** não são expostos nem editáveis pela API de Dados. O fluxo registra a limitação e indica o caminho no Studio.
- **Impressões e CTR de miniatura:** não constam nas métricas documentadas da YouTube Analytics API. O fluxo usa a última captura manual de Análises → Sinais do canal, rotulada como manual, ou declara a ausência.
- **Termos de busca:** relatório `insightTrafficSourceDetail` com filtro `insightTrafficSourceType==YT_SEARCH`, no máximo 25 linhas e ordenado por `-views`. Retenção por vídeo usa `averageViewPercentage`. A curva `audienceWatchRatio` exige uma consulta por vídeo e não é lida aqui.
- **Miniaturas:** a API devolve URLs, mas não informa se são personalizadas nem avalia conteúdo. Este fluxo não envia miniaturas.
- **Limites de texto:** título de vídeo até 100 caracteres e descrição até 5000 bytes, sem `<` nem `>`. Descrição do canal até 1000 caracteres, palavras-chave até 500 e nome do canal até 30. A documentação de playlists não informa limite: só há uma trava local de 5000 bytes, e o YouTube valida o resto.
- **Volume:** a importação lê até 200 vídeos recentes e 25 playlists. A tela avisa quando o catálogo foi truncado.
- **Cota:** leituras `*.list` e escritas `*.update` consomem a cota diária do projeto Google. As escritas custam bem mais que as leituras; consulte a calculadora de cota oficial antes de publicar em volume.
- **Analytics:** a janela é de 28 dias terminando dois dias antes de hoje, porque os dados chegam com atraso. Cada seção falha de forma independente e o erro fica registrado. Sem Analytics autorizado, o diagnóstico declara que não aponta causa para a baixa visibilidade.

## Fora do escopo desta etapa

- Sugestões geradas por IA para vídeos existentes (o endpoint pago `/package-suggestion` continua separado e exige confirmação de custo).
- Outras grafias antigas da marca fora do YouTube, como o seed `radio_channels` e a sobreposição da rádio em `studio/autostream.py`, que continuam com `Lo-Fi Vibe Coding`. O prompt editorial compartilhado em `studio/youtube_metadata.py` passou a usar `LoFi Vibe Coding`.
