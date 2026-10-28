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

- A captura de 28/10 observou três tarefas visuais em `UNCERTAIN`, mas a consulta de runtime usada para preservar privacidade trouxe contagens e custo agregado, sem IDs, payloads, request IDs, timestamps individuais ou autoria.
- O Studio e os seis outros containers foram identificados por imagem/revisão, mas isso não demonstra que os diretórios de teste dentro do mount `/cache` tenham sido importados ou chamados por esses serviços.
- A busca estática identifica caminhos candidatos que poderiam escrever estados; não correlaciona nenhum caminho a uma tarefa real. Não atribuir as tarefas incertas às variantes `continuity`, `fresh-hd`, `Halloween`, `seven-hours` ou `validation45` sem evidência adicional.
- Capturas arquivísticas continuam preservadas. Nenhum script foi importado, iniciado, copiado para local executável ou usado para alterar banco, mídia ou serviço.

## Próxima evidência necessária para fechar a atribuição

1. Em sessão read-only, identificar para cada tarefa incerta somente os campos mínimos necessários à correlação: ID, `kind`, `created_at`, `updated_at`, hash/versão do payload sem seus valores privados, e IDs de solicitação/provedor quando já existirem. Não selecionar prompt, tokens, URLs assinadas, conteúdo de mídia nem campos de usuário.
2. Comparar esses fingerprints com os registros/históricos da aplicação e com as revisões exatas dos containers que poderiam escrevê-los.
3. Separar escrita de API, transição de worker, ferramenta de recuperação e cópia de teste; verificar transaction/audit log ou evidência operacional disponível antes de atribuir autoria.
4. Manter a incerteza se as evidências não permitirem correlação. Não executar scripts arquivados como forma de descobrir seu efeito.

Esta captura estática avança a catalogação de WP-00, mas **não fecha WP-00, TEST-27 ou TEST-37**, não resolve tarefas incertas e não autoriza bootstrap, deploy ou promoção de código do cache.
