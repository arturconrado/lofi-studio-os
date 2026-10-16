# SDD v2 — lacunas implementadas (branch `feat/sdd-v2-gaps`)

Esta entrega altera o código. Ela fecha as lacunas de [10-LACUNAS_POS_RECUPERACAO](../audit-2026-10-15/10-LACUNAS_POS_RECUPERACAO.md) que dependiam só de código.

**Não inclui:** geração paga, novos gestos aprovados, deploy, publicação, escrita no banco de produção nem homologação de 4/8h. A produção continua na versão anterior até um deploy específico.

## Correções de defeitos encontrados durante a implementação

1. **A troca de cor tingia o quadro inteiro (P0, ID-02).** O merge do recolor usava uma máscara cinza dentro de YUV 4:2:0. Nos planos de cor (U/V), essa máscara virava 128 (neutro). O resultado era 50% da cor nova aplicada no quadro todo, inclusive no rosto e no gato. Medição: desvio de croma de 23 fora da máscara contra 23,5 dentro dela. Agora a máscara tem planos de cor próprios; fora dela o desvio é **0** (teste sem perdas no filtro). O defeito entrou no PR #30, que ainda não estava em produção.
2. **As camadas de luz vazavam ~6% no quadro todo.** Isso valia para céu, luzes, lareira e luminária. A conversão automática da máscara cinza para YUV comprime 0..255 em 16..235. Usam agora o mesmo helper `mask_planes`, que é exato fora da máscara. Isso afetava também as camadas de céu e luzes já existentes.
3. **A aprovação de faixa recusava o QC atual.** A aprovação exigia a versão `3.0.0`, mas o `quality_gate` grava `3.1.0`; os dois valores vêm da importação inicial. A aprovação passou a aceitar também a versão atual do gate. Todas as outras exigências continuam iguais.

## O que foi implementado

| Lacuna | Entrega | Onde |
|---|---|---|
| 2 máscaras animadas | Quadros-chave de máscara por clipe, com interpolação, seguindo a fase do loop; editor no portal | `timeline_compositor.clip_mask_frames`, `POST /assembly/plans/{pid}/clips/{cid}/masks` |
| 3 teste ID-02 | Uma única implementação de recolor (render, prévia e still) e testes do render real e do filtro sem perdas | `selective_color.py`, `tests/test_scene_layers.py` |
| 4 backup | Cópia off-site verificada por SHA-256 que não sobrescreve silenciosamente, com Object Lock opcional, checagem de versionamento/Lock e teste de restauração | `python -m studio.backup` |
| 5 proveniência | `assets.provenance` gravado automaticamente nas músicas novas, backfill em modo dry-run, relatório por programa e trava opcional na publicação | `studio/provenance.py`, `GET /api/programs/{id}/rights` |
| 6 QA do catálogo | Relatório **somente leitura** (transação READ ONLY): QC, loudness, silêncio, BPM medido e quase-duplicatas | `python -m studio.catalog_audit` |
| 7 tolerâncias | Calibração medida nos episódios aprovados (costura, luminância, ruído do encoder, loudness) e `check()` para renders novos | `python -m studio.calibration` |
| 8–9 cenas e ambiente | Registro de cenas, incluindo as 3 aprovadas (objetos visíveis, clima, períodos de luz). Chuva, neve e névoa entram como camadas locais em loop sem emenda, sem precisar de clipes novos | `studio/scene_profiles.py` |
| 10 objetos | Estado de objetos (luminária, lareira); luz da lareira e da luminária ligada ao relógio; gesto de acender exige clipe L3 novo | `action_states.OBJECT_EFFECTS` |
| 11 marcos variáveis | Agenda "eventos personalizados por minuto" com 5 sequências; cada sequência declara os objetos que exige | `ProductionSpec.markers` |
| 12 IA propõe eventos | Até 5 ideias no formato §6.2, validadas pelas mesmas regras do formulário; aplicação só com revisão; ideias sem execução viram `NEW_ASSET_REQUIRED` | `studio/event_proposals.py` |
| 13 prévia condensada | 10s com amostras em velocidade real de 0/15/30/45/55/60 min, cada uma no seu relógio, com rótulo e áudio dos mesmos instantes | `timeline_preview.condensed` |
| 14 storyboard visual | Folha com um quadro real de cada amostra, gerada junto com a prévia condensada | `timeline_preview.storyboard_sheet` |
| 15 variações ocasionais | Sorriso, orelha do gato e olhar à janela, com seed versionada, ≥90s longe dos marcos; sem clipe aprovado elas ficam de fora, sem simulação | `production_harness.occasional_events` |
| 16–17 custo e capacidade | CPU, pico de disco, bytes enviados e extrapolação por hora de programa; custo em US$ só com tarifas reais configuradas | `timeline_compositor.resource_report`, `GET /assembly/plans/{pid}/economics` |
| 18 estado do episódio | DRAFT→PROPOSED→VALIDATED→PREVIEWED→RENDERING→QC→APPROVED→PUBLISHED, derivado sem migração | `studio/episode_state.py` |
| 19 som ambiente | Chuva ou lareira geradas localmente (sem amostras de terceiros), ~26 dB abaixo da música; a versão só com música é enviada separada | `studio/ambient_audio.py` |
| 21 NichePack | Regras por canal (cenários, estilos, sequências, interrupção máxima por hora, variações, gestos) validadas no servidor | `harness_profiles.NichePolicy` |
| 22 poses e câmeras | Biblioteca versionada derivada do contrato de estados e das cenas; transformação segura = identidade | `studio/pose_library.py` |
| 23 métricas | Retenção nos minutos 15/30/45 e marcação com/sem eventos para comparação A/B | `growth.Snapshot` |
| 24–25 áudio | Quase-duplicatas por impressão digital tonal; BPM medido (estimativa) gravado no QC das faixas novas | `studio/audio_analysis.py` |
| 1 clipes (apoio) | Briefing de produção por clipe faltante: direção, duração, poses de entrada e saída, câmera e checklist | `GET /assembly/plans/{pid}/clip-briefs` |

**Compatibilidade:** quando os campos novos ficam no padrão, o hash criativo, as fingerprints dos clipes e o plano de montagem são idênticos aos de `main`. Isso foi verificado em 4 configurações legadas. Revisões já feitas continuam válidas. Clima e luz locais não mudam as fingerprints, então clipes revisados servem para várias variantes.

## Achado de produto

Os 3 episódios aprovados **não mostram celular nem almofada**; o gato fica sobre a mesa. Por isso o preset 15/30/45 atual (celular aos 30) é recusado nessas cenas. Use "Eventos personalizados" (por exemplo: carinho aos 15, alongar aos 30, gato se espreguiça aos 45). Para usar celular nelas, é preciso uma nova base revisada com o celular visível.

## Operação (o que depende de você)

| Passo | Comando / ação |
|---|---|
| Backup | Configurar `BACKUP_S3_*` (outra conta ou bucket, com versionamento + Object Lock). Rodar `python -m studio.backup check`, depois `run --scope approved`, `run --scope catalog` e `verify --manifest …` |
| Proveniência | Revisar os termos do provedor e preencher `LOFI_PROVIDER_TERMS_JSON`. Rodar `python -m studio.provenance backfill` (dry-run) e depois `--apply`. A declaração de direitos continua na aprovação de cada faixa. Para travar a publicação: `LOFI_REQUIRE_PROVENANCE_FOR_PUBLISH=1` |
| QA do catálogo | `python -m studio.catalog_audit --program <ID> --out qa.json` (não escreve no banco) e ouvir os itens marcados |
| Calibração | `python -m studio.calibration --source <pilot>=motion.mp4,full.mp4,source.png` (×3) e versionar o `studio/qc_thresholds.json` gerado |
| Custos | Definir `LOFI_CPU_HOUR_USD` e `LOFI_STORAGE_GB_MONTH_USD` com as tarifas reais da VPS |
| Capacidade | Fazer um render real de 1h em staging e ler `local_resources.per_program_hour` antes de prometer 4/8h |
| Clipes | Baixar o briefing, produzir ou cotar **uma** ação piloto, enviar e revisar no portal |
| Título do piloto | Corrigir o título "Pixel Sunset…" do programa com visual Greenhouse direto nos metadados do programa (dado de produção; não é alterado por código) |
| Deploy | API, Creator e exportador com filas inativas, guardando a imagem anterior. O worker de montagem precisa da versão nova (máscaras animadas, prévia condensada) |

## Validação

151 testes Python (Postgres descartável e FFmpeg real) e 6 verificações de interface passam. Entre eles: testes sem perdas no nível do filtro (desvio 0 fora das máscaras), renders reais de recolor, máscaras animadas, clima, lareira e prévia condensada, loop sem emenda das camadas de clima e som, BPM em faixas de clique (±3), quase-duplicatas com deslocamento e ganho, backup com fonte adulterada e conflito, e restauração com objeto corrompido.

**Não validado:** qualidade artística, gestos nos pixels (os clipes não existem), render de 4/8h, termos jurídicos e retenção real.
