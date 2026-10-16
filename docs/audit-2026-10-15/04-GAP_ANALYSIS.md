# 04 — Requisitos, capacidades e riscos

Estado no commit `bf5c851`. A aprovação artística dos três episódios foi confirmada pelo responsável; a matriz avalia a capacidade reproduzível da plataforma, não invalida esses arquivos.

| ID SDD | Estado | Evidência | Lacuna / prioridade |
|---|---|---|---|
| FR-01 auditoria | Implementada e validada nesta entrega | Inventário read-only, índice de código, hashes, comparações e testes anexos | Limitações declaradas, sem simular inspeção de todas as horas |
| FR-02 identidade | Parcial | Baselines aprovadas; referências/fingerprints no harness; reuso exato em `creator_service.visual` | Falta perfil canônico versionado com máscaras/poses; caminho histórico sem referência gerou drift. P0 |
| FR-03 recolor seletivo | Ausente | `shirt_color` é parâmetro de prompt; não foi localizado operador de recolor/máscaras protegidas | Não confundir troca de cor por nova geração com recoloração seletiva. P0 |
| FR-04 base de movimento | Parcial | Clipes Veo e ciclos existentes; microanimação local em `scene_animation`, `ambient_animation`, `ambient_fast` | Material reaproveitável existe; biblioteca de ações articuladas e poses com entrada/saída não está pronta. P0 |
| FR-05 sessão musical | Parcial | `provider.generate`, `batch_factory`, catálogo, concatenação e `quality_gate` | QA existe, mas 241 assets estão `not_run`; crossfades não integram o caminho legado; proveniência comercial não preenchida. P0 |
| FR-06 timeline 60min | Parcial | `compile_spec` + `assembly_plan`: 3.600s, sem overlap de intervalos; compositor local testado | Agenda planejada não comprova ação executada; faltam clipes reais completos. P0 |
| FR-07 marcos 15/30/45 | Ausente | `production_harness.py:44,52` fixa pausas 10/20/30/40/50 e celular 25/45 | Implementar preset novo sem reescrever manifests históricos. P1 |
| FR-08 IA propõe ideias governadas | Parcial | `form_assistant.py` retorna campos tipados e exige aplicação revisada | Não consulta estados/objetos/ações disponíveis para propor eventos executáveis. P1 |
| FR-09 ações contextuais | Parcial | Curvas de luz, chuva/vapor, regiões e estrelas locais | Ligar luminária/lareira com gesto causal não foi implementado; exige pose/objeto alcançável. P1 |
| FR-10 preview fiel 8–10s | Ausente como experiência completa | Piloto de interação 8s; estudo ambiental de 64s; são caminhos separados | Falta compilação das amostras do mesmo manifest final + loop real + áudio em velocidade normal. P1 |
| FR-11 cache e retomada | Parcial | Fingerprints, reuso compatível, request IDs; jobs interrompidos são marcados | Worker apaga intermediários no `finally`; não retoma segmentos concluídos. P1 |
| FR-12 custos por etapa | Parcial | Reservas duráveis, preço verificado, tetos e bloqueios financeiros | CPU/disco/storage por vídeo aprovado sem medição; limite de prévia US$2 separado do orçamento proposto. P1 |
| FR-13 configuração de nicho | Ausente como NichePack | Canal tem nome/nicho; estilos musicais enumerados | Não há pacote versionado de identidade, ações, áudio, cena e aprovação. P1 |
| FR-14 câmera/poses | Ausente como biblioteca versionada | Enquadramentos dos assets existem; clipes são full-frame e scene-bound | Não há catálogo de poses/câmeras com transformação validada. P2 |
| FR-15 métricas | Parcial | Módulos `growth`, `monetization`, logs e custos reservados | `analytics_snapshots=0`; sem custo unitário completo nem causalidade de retenção medida. P2 |
| NFR-01 reprodutibilidade | Parcial | Seeds locais, hashes, request IDs, manifests e fingerprints | Provider não garante reprodução exata; há scripts operacionais fora do Git; preview e produção nem sempre compartilham plano. P0 |
| NFR-02 preservação | Parcial | Originais no S3 e cópias no cache; snapshot local de código/inputs e verificações anexas | Cache não equivale a backup imutável/off-site; versionamento S3 não pôde ser confirmado. P0 |
| NFR-03 falha segura | Parcial | Preflight bloqueia montagem sem assets e revisões; geração sem retentativa automática | Histórico criou imagem sem identidade condicionada; requer rejeição e vinculação de fontes em todos os caminhos. P0 |
| NFR-04 observabilidade | Parcial | Tabelas `audit`, `jobs`, `factory_tasks`, reports de render | Não há tempos/custos consolidados por vídeo aprovado, nem checkpoint recuperável. P1 |
| NFR-05 formato e sincronismo | Parcial | Episódios reais 1280×720/24fps; export H.264/AAC; testes de duração/A/V | Configuração pública de formatos é limitada; compositor longo em produção não foi certificado. P1 |

## Distinções que impedem falsos positivos

- `ready` no lote significa fontes disponíveis; não equivale a aprovação de arte, direitos ou publicação.
- `render_ready=false` no compilador não significa compositor inexistente: significa que planejamento sozinho não fornece materiais revisados.
- Uma referência de 8s aprovada não satisfaz os 11 tipos de ação exigidos pelo compilador atual.
- Pixel delta baixo/alto mede diferença visual, não interpreta “respirou satisfeita”, “fez carinho” ou “passou o tempo”.
- 90 testes automatizados aprovados não certificam o rosto/gato em todos os frames, áudio artístico ou execução ininterrupta de 8h.
- A existência de `quality_gate` não implica que o catálogo foi reanalisado: `qc_runs=0` e assets `not_run` são evidências do estado real.

## Riscos operacionais transversais

1. **P0 — registro de referência:** aprovação verbal e flags legadas divergem; reconciliar com hashes exatos, sem reprovar o que foi aceito.
2. **P0 — trilha de auditoria de assets:** metadados de fontes devem ser confrontados com bytes, e nunca usados como única cópia recuperável.
3. **P1 — capacidade:** cerca de 20 GB livres; encoder do exportador limitado a 0,2 CPU. Não assumir que 8h cabem em tempo/disco aceitável.
4. **P1 — publicação incerta:** registro Ocean está `uncertain`, Forest/Neon estão `held`, publisher parado. Apenas registrar; não retentar upload nem alterar agenda.
5. **P1 — nomes de interface:** o programa piloto continua com título “Pixel Sunset…” embora seu visual selecionado seja Greenhouse. Corrigir metadado é tarefa posterior, não regeneração.

## Localização das evidências de código

Cada referência abaixo pertence ao commit `bf5c851`; hashes completos e linhas de todas as funções estão em `evidence/requirement-trace.json`. A ausência de uma classe/operador é conclusão limitada ao repositório e aos scripts inspecionados, não prova sobre arquivos externos não acessíveis.

- FR-01: `studio/creator.py:12` (saved_plans; demais funções no índice).
- FR-02: `studio/creator_service.py:12` (visual; demais funções no índice); `studio/production_harness.py:11` (ProductionSpec; demais funções no índice); `studio/timeline_api.py:16` (get_plan; demais funções no índice).
- FR-03: `studio/production_harness.py:11` (ProductionSpec; demais funções no índice); `studio/scene_animation.py:10` (render; demais funções no índice).
- FR-04: `studio/scene_animation.py:10` (render; demais funções no índice); `studio/ambient_animation.py:7` (events; demais funções no índice); `studio/ambient_fast.py:7` (FastScene; demais funções no índice).
- FR-05: `studio/batch_factory.py:20` (authorized_settings; demais funções no índice); `studio/creator_service.py:12` (visual; demais funções no índice); `studio/quality_gate.py:12` (policy; demais funções no índice); `studio/qc_service.py:6` (reprocess; demais funções no índice).
- FR-06: `studio/production_harness.py:11` (ProductionSpec; demais funções no índice); `studio/timeline_compositor.py:17` (file_hash; demais funções no índice).
- FR-07: `studio/production_harness.py:11` (ProductionSpec; demais funções no índice).
- FR-08: `studio/form_assistant.py:15` (Patch; demais funções no índice).
- FR-09: `studio/timeline_compositor.py:17` (file_hash; demais funções no índice); `studio/temporal_preview.py:13` (smooth; demais funções no índice).
- FR-10: `studio/motion_validation.py:22` (quote_model; demais funções no índice); `studio/temporal_preview.py:13` (smooth; demais funções no índice).
- FR-11: `studio/timeline_worker.py:9` (heartbeat; demais funções no índice); `studio/timeline_api.py:16` (get_plan; demais funções no índice).
- FR-12: `studio/financial.py:6` (check_available; demais funções no índice); `studio/batch_factory.py:20` (authorized_settings; demais funções no índice).
- FR-13: `studio/production_harness.py:11` (ProductionSpec; demais funções no índice).
- FR-14: `studio/production_harness.py:11` (ProductionSpec; demais funções no índice).
- FR-15: `studio/financial.py:6` (check_available; demais funções no índice).
- NFR-01: `studio/production_harness.py:11` (ProductionSpec; demais funções no índice); `studio/provider.py:9` (decode_chunk; demais funções no índice).
- NFR-02: `studio/creator_service.py:12` (visual; demais funções no índice).
- NFR-03: `studio/timeline_compositor.py:17` (file_hash; demais funções no índice); `studio/creator.py:12` (saved_plans; demais funções no índice).
- NFR-04: `studio/timeline_worker.py:9` (heartbeat; demais funções no índice).
- NFR-05: `studio/video_export.py:9` (export; demais funções no índice); `studio/timeline_compositor.py:17` (file_hash; demais funções no índice).
