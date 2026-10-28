# WP-00 — candidatos a escritores de `factory_tasks` no cache (2026-10-28)

## Escopo e método

Consulta estática e somente de leitura dos 383 arquivos de código preservados em `ops/production-server-snapshot/2026-10-27/cache-code/`. A busca textual, sem importar nem executar os arquivos, procurou instruções SQL `INSERT INTO`, `UPDATE` e `DELETE FROM factory_tasks`, sem diferenciar maiúsculas/minúsculas.

O resultado é um inventário de **52 caminhos por cópia/grupo** em seis diretórios de captura. Ele não demonstra que qualquer script foi executado, que qualquer caminho estava montado em um serviço executável ou que esses arquivos criaram as três tarefas `UNCERTAIN` vistas no runtime.

## Resultados por grupo

| Diretório capturado | Caminhos com escrita textual em `factory_tasks` | Interpretação estática |
|---|---:|---|
| `continuity-test-20261023` | 9 | Cópia de módulos da aplicação: `creator_service.py`, `exports.py`, `form_assistant.py`, `motion_validation.py`, `timeline_api.py`, `timeline_worker.py`, `workshop_api.py`, `workshop_provider.py`, `workshop_worker.py`. Inclui criação, transições de estado e conclusão de tarefa. |
| `continuity-test-v2-20261023` | 9 | Mesmo conjunto de módulos da variante anterior, preservado em outra pasta. A existência de duas cópias não prova que ambas foram usadas. |
| `validation45-20261023` | 9 | Mesmo conjunto de nove módulos de aplicação; continua classificado como variante arquivada sem atribuição de execução. |
| `fresh-hd-test-20261023` | 13 | Os nove módulos de aplicação acima mais `monitor_portal.py`, `progress_detail.py`, `recover_hd_upload.py` e `run.py`. Os nomes e o texto de algumas operações apontam para fluxo de teste/recuperação; não foram executados nem validados contra o estado atual. |
| `library-catalog-fix-20261023` | 10 | Variantes Halloween: pares `workshop_api.py`/`workshop_worker.py` em `halloween-bounded-encoder` e `halloween-flow-v4`; `workshop_api.py` em `halloween-recovery-ui` e `halloween-ui-v2`; trio `workshop_api.py`, `workshop_provider.py`, `workshop_worker.py` em `halloween-release`; e `monitor_halloween_render.py`. São variantes preservadas, não fontes canônicas. |
| `seven-hours` | 2 | `generate_visual.py` e `generate_wide.py`; scripts de geração/validação preservados no cache. A busca textual encontrou escritas, mas não determina se seus efeitos remotos ainda são possíveis ou se foram executados. |

Os 52 caminhos são contagens de caminhos dentro de grupos, não 52 componentes independentes. Os módulos repetidos entre variantes precisam ser comparados por hash e revisão antes de qualquer conclusão de autoria.

## Relação com a evidência de runtime

- Uma nova consulta read-only em 28/10 leu somente fingerprint MD5 truncado, `kind`, modelo, estado, timestamps, reserva, estágio/operação e presença de identificadores de callback/provedor/solicitação. As três tarefas em `UNCERTAIN` são do tipo `growth_packaging_20261024`, usam `google/gemini-2.5-flash-lite` e somam US$ 0,05 em reservas (duas de US$ 0,02 e uma de US$ 0,01). Os fingerprints registrados são `36da2b2822`, `b270db3b8a` e `7251ac53eb`; UUIDs e conteúdo do payload não foram selecionados nem preservados.
- Na consulta, nenhuma das três tinha `operation`, `attempt_stage`, token de callback, ID de tarefa do provedor ou `request_id` no payload. Isso restringe a família funcional à geração de embalagem de Growth, mas não identifica a sessão/endpoint que iniciou cada tarefa, nem comprova se o provedor concluiu ou cobrou uma chamada.

| Fingerprint pseudônimo | Criada (UTC) | Atualizada (UTC) | Reserva USD |
|---|---|---|---:|
| `36da2b2822` | 2026-10-27 01:52:28.690502 | 2026-10-27 01:52:29.647642 | 0.02 |
| `b270db3b8a` | 2026-10-27 02:38:32.701398 | 2026-10-27 02:38:34.219722 | 0.02 |
| `7251ac53eb` | 2026-10-27 03:10:15.206404 | 2026-10-27 03:10:16.971760 | 0.01 |
- O Studio e os seis outros containers foram identificados por imagem/revisão, mas isso não demonstra que os diretórios de teste dentro do mount `/cache` tenham sido importados ou chamados por esses serviços.
- A busca estática identifica caminhos candidatos que poderiam escrever estados; não correlaciona nenhum caminho arquivado a uma tarefa real. Não atribuir as tarefas incertas às variantes `continuity`, `fresh-hd`, `Halloween`, `seven-hours` ou `validation45` sem evidência adicional.
- Capturas arquivísticas continuam preservadas. Nenhum script foi importado, iniciado, copiado para local executável ou usado para alterar banco, mídia ou serviço.

## Próxima evidência necessária para fechar a atribuição

1. Consultar apenas metadados de auditoria permitidos, logs sanitizados e revisões exatas para procurar correlação por fingerprint/timestamp; não ampliar a seleção para prompts, tokens, URLs assinadas, conteúdo de mídia, UUIDs brutos ou campos de usuário.
2. Determinar se existe registro local confiável de resposta/custo para cada tarefa. A ausência de ID remoto impede concluir que o provedor não executou a chamada; não reenviar automaticamente uma tarefa `UNCERTAIN`.
3. Separar a rota Growth atual de escritores históricos ou ferramentas de recuperação; verificar logs sanitizados/transações disponíveis antes de atribuir autoria.
4. Manter sem conclusão a autoria exata e o resultado/custo terminal enquanto não houver evidência suficiente. Não executar scripts arquivados como forma de descobrir seu efeito.

Esta captura estática e a consulta limitada de metadados avançam a catalogação de WP-00, mas **não fecham WP-00, TEST-27 ou TEST-37**, não resolvem o resultado/custo terminal das tarefas incertas e não autorizam bootstrap, deploy ou promoção de código do cache.
