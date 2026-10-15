# 07 — Backlog de correções mínimas

**Proposta para avaliação; nenhuma tarefa de correção foi executada nesta auditoria.** Esforço relativo: pequeno = ajuste localizado; médio = adaptação de contrato/UI e testes; grande = novos assets/poses/rotinas dependentes de validação visual. Não são compromissos de dias nem preços de fornecedor.

| Ordem | Prioridade / tarefa | Dependências e área | Custo conhecido / esforço | Aceite | Rollback |
|---|---|---|---|---|---|
| 1 | P0 — reconciliar baseline e aprovações | Episódios/registry, hashes e decisão do responsável | Sem geração externa; pequeno | Referência aprovada aparece pelo nome e versão correta; dados anteriores preservados | Registro aditivo; manter apontamento anterior |
| 2 | P0 — rejeitar asset 8-bit defeituoso para novo uso | Registro por hash, UI Creator/player, validação de seleção | Sem geração externa; pequeno | Artefato continua recuperável no histórico, mas não vira default/ciclo/export novo | Reverter a rejeição por decisão explícita, sem reupload |
| 3 | P0 — unificar vínculo de referência em todos os caminhos | `creator`, piloto de movimento e action import; câmera/asset exatos | Sem geração para o bloqueio; médio | Não aceita texto “mesma garota” sem fonte revisada; fonte escolhida corresponde ao perfil do roteiro | Feature flag/adaptador mantendo leitura legada |
| 4 | P0 — guardar fontes e corrigir recibos divergentes | Inventário real e hashes, scripts operacionais preservados | Storage/CPU a medir; pequeno/médio | Todas as fontes recuperáveis têm hash correto e histórico; nunca sobrescrever recibo antigo silenciosamente | Metadado corretivo versionado, original retido |
| 5 | P0 — máscaras e recolor seletivo | Baseline congelada, regiões protegidas revisadas | Sem IA obrigatória; médio | Apenas roupa/almofada mudam; rosto/cabelo/gato/fundo não são redesenhados | Descartar derivado e voltar ao asset-base |
| 6 | P0 — biblioteca mínima de movimentos | Mapear loops bons, limites L0/L1 e ações L2 ausentes | Reuso sem chamada; assets novos exigem cotação; grande se exigir poses | Trecho real de cada ação/retorno aprovado, sem deformação geral para simular gesto | Manter loop aprovado e bloquear ação ausente |
| 7 | P0 — QA musical no fluxo de produção | `quality_gate` já existe; operar primeiro em cópias/derivados | CPU, sem nova composição obrigatória; médio | Relatório por faixa/mix; reanálise não substitui originais nem aprova direitos automaticamente | Retornar playlist/derivado anterior |
| 8 | P1 — preset 15/30/45 + estados | Biblioteca de ações e manifest versionado | Sem geração externa; médio | Recursos exclusivos e estados válidos; preset legado intacto | Seleção explícita do preset anterior |
| 9 | P1 — preview fiel ao manifest | Etapas 3,6,8; compositor existente | Montagem curta local; médio | Storyboard + direção 8–10s + loop real + áudio real, vinculados aos mesmos hashes | Reter prévias anteriores com sua versão |
| 10 | P1 — mix/crossfade derivado | QA musical e playlist congelada | CPU, sem alterar fontes; médio | Duração recalculada após sobreposição; sem corte/pico inesperado; audição aprovada | Usar mix anterior preservado |
| 11 | P1 — checkpoints e custo por aprovado | Worker atual, disco/quotas medidos | CPU/storage a medir; médio | Restart recupera segmentos por hash; não repete pedidos pagos; capacidade medida antes de 4/8h | Worker anterior e jobs interrompidos preservados |
| 12 | P1/P2 — NichePack e métricas | Contratos estabilizados | Sem estimativa financeira inventada; médio | Segundo perfil configurável sem fork; métricas reais separadas de sugestões | Perfil antigo continua válido |

## Primeiro incremento recomendado

Executar apenas 1–4: consolidar a referência já aprovada, impedir a reutilização do artefato errado e sanar rastreabilidade. Depois demonstrar **uma** alteração localizada de cor e **uma** ação compatível com a baseline em trecho curto. Não financiar um novo vídeo completo para descobrir se a identidade ainda falha.

## Limites financeiros

Reservas antigas, custos informados pelo provedor e custo total da VPS são conceitos separados. A referência de áudio de 2min possui custo informado de US$0,08; o histórico registra reservas distintas de imagem/movimento. Não extrapolar isso para um custo garantido de uma hora com todas as ações. A auditoria não aumentou tetos nem consumiu chamadas externas.

## Resultado de integridade e reaproveitamento

Os 15 pares cache/S3 medidos coincidiram com os recibos. Portanto não há divergência comprovada a corrigir nesses arquivos: na tarefa 4, priorizar proteção/backup e manter correção de recibo apenas se uma divergência futura for demonstrada. As fontes animadas de 8s dos três episódios são reutilizáveis como base após mapeamento e revisão da costura; “11 ações ausentes no inventário do harness” não significa que todo movimento tenha de ser gerado novamente.
