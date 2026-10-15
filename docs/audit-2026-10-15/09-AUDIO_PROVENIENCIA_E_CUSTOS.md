# 09 — Áudio, proveniência e custos

## O que está funcionando

**Verificado no código e catálogo:** geração por `google/lyria-3-pro-preview`, armazenamento de originais com SHA, duração medida por FFprobe, decode completo de cada composição no batch, prompts persistidos e custo informado/reservado por pedido (`studio/provider.py`, `batch_factory.py:65–102`). O catálogo administrativo contém 241 assets, com SHA de arquivo distintos. Isso comprova arquivos diferentes, não originalidade musical perceptual ou jurídica.

A trilha é independente do visual. `creator_service.package:65–74` concatena MP3s sem recodificação de áudio e registra offsets/playlist. `video_export.export` faz mux com visual H.264, converte áudio para AAC, mede duração/streams e decodifica a saída. O exportador exige revisão do snapshot atual; a auditoria não contornou esse bloqueio.

## Qualidade e curadoria

- `quality_gate.analyze` implementa análise de integridade, loudness, picos, duração, silêncio/padding e outros sinais. `master` pode gerar derivado com ganho medido. Sua existência não significa execução automática no fluxo que gerou o catálogo atual.
- No snapshot: `qc_runs=0`; 241 registros `qc.version=not_run`; revisão técnica e editorial pendentes. A aprovação dos episódios pelo responsável é válida para a baseline, mas não deve ser confundida com preenchimento automático dessas colunas.
- `qc_service.reprocess` escreve resultados e pode invalidar aprovações/variantes. **Não foi chamado nesta auditoria**. Análises novas foram realizadas em leitura, com FFmpeg para saída nula, sem alterar fontes ou catálogo.
- O pacote legado usa concatenação, não crossfade entre faixas. Pode haver finais musicais suaves nas fontes; isso não comprova ausência de cortes em todas as junções. Implementar crossfade deve criar um derivado e recalcular duração, não sobrescrever originais.
- O batch acrescenta BPMs de uma lista fixa a um brief que pode pedir outro BPM (`batch_factory.py:56–62`). É possível produzir instruções conflitantes; os BPMs do catálogo são intenção/metadado, não medição musical automática.
- Não foi demonstrada deduplicação perceptual de todas as músicas. O serviço de QC compara PCM quando executado, mas não há recibos dessa execução no snapshot atual.

## Medições desta auditoria

Resultados em `evidence/media-evidence.json`: rehash de áudio de cada um dos três episódios, comparação cache/S3, análise de volume e silêncio para saída nula. LUFS/true peak/LRA dos recibos históricos permanecem claramente identificados como medições anteriores vinculadas ao mesmo áudio. Uma nova medição LUFS completa não concluída dentro do limite operacional não é apresentada como resultado novo.

O limiar de silêncio usado como diagnóstico é −50 dBFS por pelo menos 1s; não é regra editorial universal. A ausência de eventos nesse detector não garante ausência de todo gap ou de silêncio musical intencional. Pico abaixo de 0 dBFS não exclui defeitos presentes em uma fonte antes da codificação. Nenhuma das medições substitui a audição do responsável.

## Proveniência e direitos

**Verificado:** modelos, prompts, IDs de geração, hashes e recibos existem em partes do pipeline; os registros `assets.rights_evidence` estão vazios nos 241 assets inspecionados. Relatórios dos episódios registram situação comercial pendente.

**Não verificável com as evidências atuais:** titularidade integral, licença comercial aplicável a cada geração, ausência de material protegido, admissibilidade futura de Content ID ou monetização. Isso não é uma declaração de que os arquivos sejam ilegais: é ausência de documentação suficiente no registro auditado. Não foram aceitos termos nem consultadas contas externas para criar autorização presumida.

**Proposta mínima:** anexar recibo/modelo/data/termos aplicáveis e declaração do responsável por sessão; relacionar cada derivado aos originais; manter revisão comercial separada da aprovação visual. Verificação jurídica externa não é substituída por um indicador técnico PASS.

## Custos

- A faixa de 121,78s da referência 8-bit tem US$0,08 de custo informado no pedido existente. Nenhuma composição foi solicitada nesta auditoria.
- As reservas da série de vídeos e da prévia Veo são históricas e têm critérios distintos; preço antigo não é cotação atual.
- Imagem/vídeo reaproveitados não geram uma nova chamada ao provedor. Isso não elimina CPU, armazenamento, tráfego ou custo da VPS.
- Não há consolidação suficiente de CPU/disco/retrabalho por episódio aprovado para prometer custo total por hora ou capacidade de 8h. O orçamento proposto de US$15 não foi aumentado nem consumido pela auditoria.

## Próximo incremento recomendado

Preservar as músicas aprovadas e produzir primeiro um relatório read-only de QA por playlist. Corrigir somente as transições/ganhos comprovadamente problemáticos em derivados, com audição comparativa. Não regenerar a biblioteca inteira para preencher flags pendentes.

## Resultados medidos nos três episódios

| Episódio | Decode atual | Pico amostral atual | Média atual dBFS | LUFS do recibo anterior | Trechos abaixo do limiar diagnóstico |
|---|---|---:|---:|---:|---:|
| Snowy Night Studio  | Sem erro | -2.6 dBFS | -18.6 | -17.0 | 29 (máx. 3.24s) |
| Autumn Bookshop Coding  | Sem erro | -3.1 dBFS | -18.5 | -17.0 | 26 (máx. 2.82s) |
| Greenhouse Rain Study  | Sem erro | -2.2 dBFS | -18.6 | -17.1 | 27 (máx. 3.39s) |

Foram encontrados períodos de nível muito baixo recorrentes, alguns próximos das junções musicais. Podem incluir finais/pausas intencionais; o detector sozinho não os classifica como defeitos artísticos. São pontos objetivos para audição de transições antes de decidir por crossfade. Não invalidam a aprovação do responsável e nenhum arquivo foi normalizado, cortado ou substituído.
