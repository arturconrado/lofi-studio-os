# 10 — Lacunas atuais após a recuperação SDD v2

**Estado em `main` (`8abef49`), 15/10/2026.** Documento aditivo: os relatórios 01–09 refletem o commit `bf5c851` e permanecem como evidência original. Depois deles, o PR #30 (`2084ad6`, [notas](../sdd-v2-recovery/README.md)) implementou parte do backlog, então a matriz [04](04-GAP_ANALYSIS.md) ficou desatualizada em vários itens. Este arquivo consolida **o que já foi resolvido e o que ainda falta**.

Nenhum código, banco, deploy ou geração foi alterado para produzir este levantamento.

> **Atualização — branch `feat/sdd-v2-gaps`:** as lacunas que dependiam só de código foram implementadas. Detalhes em [sdd-v2-gaps](../sdd-v2-gaps/README.md).
>
> | Situação | Itens |
> |---|---|
> | Implementado e testado | 2, 3, 8, 9, 10, 11, 12, 13, 14, 15, 18, 19, 21, 22, 24, 25 |
> | Ferramenta pronta, falta executar com acesso/decisão do responsável | 4 (backup), 5 (termos e declaração de direitos), 6 (QA do catálogo), 7 (calibração na mídia aprovada), 16 (tarifas reais), 17 (render de 1h em staging), 23 (registrar retenção) |
> | Depende de produção paga ou revisão artística | 1 (clipes de ação; o briefing por clipe já é gerado) |
> | Dado de produção, deploy ou já coberto | 20 (deploy), 26 (scripts preservados como evidência em `f86062f`), 27 (título do piloto) |
>
> Durante a implementação apareceram três defeitos que a lista original não previa: o recolor tingia o quadro inteiro, as camadas de luz vazavam cerca de 6% e a aprovação de faixas recusava o QC atual. Os três foram corrigidos.

**Legenda da coluna Fonte**

- **Código**: conferido em `main` (`8abef49`); referência `arquivo:linha`.
- **Banco**: estado de dados registrado na auditoria 01–09; não reconsultado agora.
- **Relatado**: declarado nas notas do PR #30 ou pelo responsável.

---

## 1. Resolvido pelo PR #30

Implementado e coberto por testes automatizados. Isso **não** certifica arte, movimentos ausentes nem homologação longa.

| Requisito SDD | Situação | Onde |
|---|---|---|
| FR-02 registro canônico dos 3 episódios aprovados | Snowy, Greenhouse e Autumn com hashes de imagem, movimento, vídeo e visual silencioso | `studio/visual_baselines.json`, `studio/visual_identity.py` |
| NFR-03 bloqueio do asset 8-bit rejeitado | Bloqueado por chave e hash, histórico preservado | `studio/visual_identity.py:10` (`assert_usable`) |
| FR-07 marcos 15/30/45 | Preset `quarter_hour_v2` (carinho 15/45, celular 30); `legacy_10_25_45` continua selecionável, com o hash de aprovação preservado | `studio/production_harness.py:14,48,56` |
| §9 estados e recursos exclusivos | Pose de entrada e saída por ação; conflito de mãos, gato e celular rejeitado no compilador | `studio/action_states.py` |
| FR-03 recolor por máscara | Blusa/almofada com zonas protegidas (rosto/cabelo, gato, mãos) e revisão vinculada aos hashes dos clipes | `studio/selective_color.py`, `studio/timeline_compositor.py:49,90,190` |
| FR-10 (parcial) prévia em velocidade real | Janela de 10s da mesma timeline, com offsets absolutos de clipe, áudio e luz | `studio/timeline_preview.py:5` |
| FR-11 checkpoints e retomada | Segmentos vinculados aos inputs e à versão do renderizador; segmento corrompido é refeito | `studio/timeline_compositor.py:127,143`, `studio/timeline_api.py:369` |
| FR-05 (parcial) crossfade | Mix derivado (padrão 1,5s) com duração medida após sobreposição; originais intocados | `studio/audio_mix.py:16`, `studio/creator_service.py:74-78` |
| FR-13 (parcial) perfil por canal | Cena, música e referências versionadas por hash e isoladas por canal | `studio/harness_profiles.py` |
| FR-05 (parcial) gate técnico em lotes novos | Rejeição interrompe o lote, sem retentativa paga | `studio/batch_factory.py`, `studio/qc_service.py` |

---

## 2. O que falta

### P0: impede a garantia de identidade ou qualidade

| # | Lacuna | Fonte | Evidência | Próximo passo mínimo |
|---|---|---|---|---|
| 1 | **10 dos 11 clipes de ação não existem.** Só a digitação foi importada. Faltam: respirar, olhar fora + gato se aproxima, carinho, gato volta à almofada, gato sai, pegar celular, olhar fora com celular, gato retorna, olhar o gato e largar o celular | Código | `production_harness.py:97`: todas as tarefas nascem `status:'missing'`; `assembly_plan` (`:161`) devolve `missing_actions` | Storyboard das ações dos marcos → cotação → **uma** ação piloto L2 condicionada à referência canônica → revisão das poses de entrada e saída em trecho real |
| 2 | **Não há máscaras animadas (tracking).** O recolor só vale onde a roupa não se move | Código | Máscaras são polígonos fixos (`timeline_compositor.py:90-99`); a docstring de `selective_color.py` declara o limite | Máscara revisada por clipe de ação quando o item 1 existir. Até lá, recolor só no loop de digitação |
| 3 | **O teste de recolor do render não prova ID-02.** O teste cobre a primitiva PIL/HSV, mas o render usa FFmpeg `colorize`+`maskedmerge`. O teste do render só checa decode e offsets, não os pixels das zonas protegidas | Código | `tests/test_selective_color.py` testa `recolor()`; `timeline_compositor.py:190` não chama essa função; `tests/test_timeline_compositor.py:77-91` não compara regiões protegidas | Teste no caminho FFmpeg: diff das zonas protegidas antes/depois dentro da tolerância do item 7. Unificar as duas implementações ou documentar qual é a canônica |
| 4 | **Não há backup imutável nem off-site.** Cache não equivale a recuperação de desastre; versionamento do S3 não confirmado | Banco / Relatado | Auditoria 04 NFR-02; nenhum artefato de backup em `ops/` | Confirmar versionamento/Object Lock no bucket; cópia off-site dos 3 episódios e das 241 faixas com checksums; um restore de teste |
| 5 | **Proveniência e direitos vazios.** `rights_evidence` vazio nos 241 assets | Banco | Auditoria 09; o campo existe (`studio/core.py:91`) e só é preenchido na aprovação manual (`studio/api.py:212`) | Registrar modelo, data, termos do provedor e declaração do responsável por sessão de geração, antes de publicar ou monetizar |
| 6 | **O catálogo musical nunca passou pelo QA.** 241 assets com `qc.version=not_run`, `qc_runs=0` | Banco | Auditoria 09; o analisador `quality_gate.analyze` existe | Relatório read-only por playlist; corrigir só derivados com problema comprovado na audição |
| 7 | **Tolerâncias não calibradas:** delta de cor fora da máscara, costura de loop, LUFS e luminância nos marcos | Relatado | Auditoria 08, "Pendências" | Medir na baseline dos 3 episódios e versionar os limites no repositório |

### P1: impede escalar episódios

| # | Lacuna | Fonte | Evidência | Próximo passo mínimo |
|---|---|---|---|---|
| 8 | **Os cenários do planejador não são os aprovados.** O enum é `city_sunset / mountain_stars / balcony_dawn`; Snowy, Greenhouse e Autumn só existem pelo caminho de reuso de episódio | Código | `production_harness.py:19`, `form_assistant.py:19` | `SceneProfile` das 3 cenas aprovadas (câmera, objetos, curva de luz), mantendo as atuais |
| 9 | **Faltam parâmetros `weather`, `time_of_day` e intensidade de chuva, neve e fogo** | Código | `ProductionSpec` (`production_harness.py:11-25`) não tem esses campos | Campos opcionais com default neutro, omitidos do hash quando vazios, como `production_spec_hash` já faz |
| 10 | **Objetos com estado e ações contextuais não existem** (`LAMP_ON/OFF`, `FIREPLACE_ON/OFF`, cortina) | Código | O estado em `action_states.py:2` só tem `girl/cat/phone/hands` | Estender o estado com os objetos de cada cena. Ações contextuais ficam como proposta até haver pose L3 aprovada |
| 11 | **A sequência de cada marco é fixa.** 15/30/45 sempre executam as mesmas ações; o SDD (§22) quer ações variáveis por episódio | Código | Listas fixas em `production_harness.py:48-63` | Tornar a sequência por marco um parâmetro validado por `action_states.validate` |
| 12 | **A IA não propõe eventos.** O assistente só preenche texto e enums, não consulta ações e objetos disponíveis e não emite `NEW_ASSET_REQUIRED` | Código | `form_assistant.py:15-22` (`Patch`) | Schema `EventProposal` (SDD §6.2), validado por `action_states` e sujeito a aprovação humana |
| 13 | **Não há prévia condensada de direção.** O SDD pede 8–10s com amostras de 0/15/30/45/55/60 min; hoje existe só uma janela contínua de 10s | Código | `timeline_preview.window` aceita uma janela (`:5-6`) | Concatenar micro-janelas da mesma assembly, com legenda do minuto real (saída A do SDD §26) |
| 14 | **Não há storyboard visual (Nível 0).** `/storyboard` devolve JSON, não keyframes | Código | `creator.py:190-205` | Frames dos clipes aprovados em cada marco, com o recolor e a luz aplicados |
| 15 | **Não há variações ocasionais reprodutíveis por seed** (esticar, sorrir, orelha do gato) | Código | Nenhuma seed no harness ou na montagem | Depois do item 1: seed versionada no manifest, desligável para testes de regressão |
| 16 | **Custo por vídeo aprovado não é medido.** O relatório tem tempo e bytes; CPU, disco e storage estão fora | Relatado | Notas do PR #30; auditoria 04 FR-12 | Acrescentar CPU-segundos e GB por job ao relatório do worker |
| 17 | **Capacidade de 4/8h nunca homologada.** Cerca de 20 GB livres e encoder limitado a 0,2 CPU | Banco / Relatado | Auditoria 04, riscos | Render real de 1h em staging com medição antes de oferecer 4/8h |
| 18 | **Não há fluxo de aprovação unificado.** O ciclo `DRAFT→…→APPROVED→RENDERING→QC→PUBLISHED` está espalhado em flags (`program_reviews`, `editorial_status`, `status`) | Código | `studio/core.py`, `studio/channels.py:128` | Enum único que mapeia os estados existentes, sem migração destrutiva |
| 19 | **Não há canal separado para som ambiente** (chuva, lareira, teclado como faixa opcional abaixo da música) | Código | `audio_mix.py` mixa só as faixas musicais | Definir a política na AudioBible e implementar como faixa opcional no mix |
| 20 | **PR #30 ainda não está em produção** | Relatado | Notas do PR #30, "Validação e rollback" | Deploy só de API, Creator e exportador, com filas inativas e a imagem anterior guardada |

### P2: refinamento

| # | Lacuna | Fonte | Evidência |
|---|---|---|---|
| 21 | NichePack completo (VisualBible, AudioBible, ActionPolicy, ApprovalPolicy); hoje o perfil cobre cena, música e referências | Código | `studio/harness_profiles.py` |
| 22 | Biblioteca versionada de poses e câmeras (`pose_id`, `viewpoint_id`, `safe_transform_bounds`) | Código | Auditoria 04 FR-14; não há catálogo |
| 23 | Métricas de canal e retenção nos marcos (`analytics_snapshots=0`) | Banco | Auditoria 04 FR-15 |
| 24 | Deduplicação perceptual das músicas e controle de repetição entre episódios | Relatado | Auditoria 09 |
| 25 | BPM medido; hoje é só a intenção do prompt | Código | Auditoria 09; notas do PR #30 |
| 26 | Scripts operacionais de geração da série fora do Git | Relatado | Auditoria 04 NFR-01 |
| 27 | O programa piloto se chama "Pixel Sunset…", mas o visual é o Greenhouse | Banco | Auditoria 04, risco 5 |

---

## 3. Ordem recomendada

1. **Proteger sem custo de IA:** 4 (backup) → 5 e 6 (direitos e QA read-only) → 7 (calibrar tolerâncias) → 3 (teste do recolor no render).
2. **Planejador com as cenas aprovadas:** 8 e 9.
3. **Primeira ação real:** item 1 com **uma** ação piloto, depois 2 (máscara dessa ação).
4. **Revisão barata antes do render longo:** 13 e 14.
5. **Escala:** 10–12, 15–19, depois o P2.

Pela regra do SDD §12, não avançar para render longo enquanto os itens P0 não tiverem evidência de correção.

## 4. Limites deste levantamento

- Os itens "Banco" repetem a auditoria 01–09 e não foram reconsultados.
- A ausência de uma capacidade se refere a este repositório; scripts externos não inspecionados podem existir (ver item 26).
- Os testes não foram executados de novo para este documento. A auditoria registrou 90 testes Python passando em `bf5c851`; o PR #30 acrescentou testes que não foram rodados aqui.
