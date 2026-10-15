# 02 — Inventário de ativos e preservação

Inventário completo em `evidence/asset-inventory.json`; snapshot do catálogo em `production-before.json`. Leitura de produção em 15/10/2026, schema administrativo existente. Não foram criados usuários ou copiados dados de outros tenants.

## Contagens observadas

| Objeto | Quantidade | Interpretação |
|---|---:|---|
| Programas | 4 | Três programas anteriores e o piloto 8-bit de 121,78s |
| Episódios/pilotos | 9 | Inclui série de sete episódios e estudos anteriores |
| Referências canônicas desta auditoria | 3 | Greenhouse, Snowy Night e Autumn Bookshop, aprovados pelo responsável |
| Assets de áudio | 241 | Todos `technical_status=PENDING`, `editorial_status=PENDING`, `qc.version=not_run` |
| Pedidos musicais | 256 | 241 completos, 9 falhos e 6 incertos |
| Planos criativos | 10 | Inclui dois rascunhos de 60min sem programa gerado |
| Revisões de programas no banco | 2 | Separadas da aprovação artística dos episódios |
| Fontes/cenas de programas | 10 | Inclui fonte defeituosa histórica e Greenhouse importado no piloto |
| Exportações | 1 | Não foi solicitada exportação nesta auditoria |
| Program queue | 0 | Não foi alterada |

A soma de durações dos programas não corresponde a horas de composições únicas: `program_members` reutiliza faixas. Nenhum SHA de arquivo se repete entre os 241 registros de áudio, mas isso não exclui semelhança musical ou duplicação perceptual/PCM ainda não analisada.

## Baseline aprovada

| Episódio | ID | Duração registrada | Vídeo final / visual sem áudio | Aprovação |
|---|---|---:|---|---|
| Snowy Night Studio | `1192acca-4cea-5d5b-9cf2-0a436909fc0e` | 3600s | 913,085,370 / 824,725,239 bytes | Confirmada pelo responsável; flag legada pendente |
| Autumn Bookshop Coding | `277ef275-73f0-53fb-ba14-9046186151fd` | 3600s | 726,730,640 / 638,317,412 bytes | Confirmada pelo responsável; flag legada pendente |
| Greenhouse Rain Study | `013eb0ef-06e3-578f-a9f8-a49532b5478b` | 3600s | 929,810,245 / 841,306,582 bytes | Confirmada pelo responsável; flag legada pendente |

## Onde estão os originais e as cópias

- Armazenamento S3: arquivos finais, fontes e relatórios sob os prefixes dos episódios.
- Cache operacional: `/srv/lofi-vibe-coding/cache/seven-hours/episode-05`, `episode-06`, `episode-07`, incluindo PNG-base, fonte de movimento, vídeo final, visual sem áudio, áudio e recibos.
- Preservação local desta auditoria: imagens/clipes-base/recibos e snapshot Git `source-bf5c851.tar.gz` em `outputs/auditoria-sdd-v2/baseline/`. Nenhum arquivo aprovado foi substituído.

**Limite de recuperação:** duas cópias no mesmo servidor não demonstram recuperação de perda total da VPS. A consulta de versionamento do bucket não foi confirmada (`ClientError`); isso não prova que o versionamento esteja desativado. Não foi executado restore de desastre nem imutabilidade de storage. As cópias e hashes verificáveis estão em `media-evidence.json`; divergências, se houver, devem ser registradas, nunca corrigidas silenciosamente.

Os MP4 completos não foram duplicados na VPS, que tinha aproximadamente 20 GB livres. O snapshot local inclui insumos reutilizáveis e evidências; não se afirma que ele sozinho substitua um backup integral off-site de todos os originais musicais e renders finais.

## Piloto defeituoso

`LOFI-3A590745`: uma faixa de 121,782792s; imagem pixel art nova com cabeça extra; loop local de 60s derivado de núcleo de 20s. O visual selecionado atualmente é o Greenhouse existente, mas o ciclo defeituoso original permanece preservado. Há cópia de `scene.png`, loop, áudio e recibo para comparação, sem nova geração.

## Aprovações e rastreabilidade

A confirmação do responsável foi registrada no relatório; não foi usada para preencher em massa direitos, QA musical ou revisões de todos os assets. A divergência das flags será reconciliada em incremento posterior, vinculando aprovação ao arquivo correto. Os hashes dos 241 áudios são os registros existentes; o rehash completo desta auditoria concentra-se nos três episódios e suas fontes. Não afirmar que todos os originais musicais foram revalidados byte a byte.

## Resultado da verificação de bytes

Os **15 pares** confrontados (vídeo final, visual sem áudio, imagem-base, fonte de movimento e áudio × três episódios) coincidem entre cache e S3 e com os SHA registrados. Os três visuais sem áudio medem 3.600s, H.264, 1280×720, 24fps. Isso confirma cópias recuperáveis no ambiente atual; não comprova backup off-site ou reprodução de uma falha total da VPS.
