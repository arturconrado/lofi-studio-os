# 05 — Arquitetura incremental proposta

**Status de todo este documento: proposta, não implementação.** Manter stack, portal, storage, catálogo e isolamento atuais. Não trocar Python por outro motor nem exigir geração por frame.

## Contratos mínimos, com adaptação dos dados atuais

1. **Perfil de identidade versionado:** registrar referências dos três episódios, hashes reais, câmera/âncoras, áreas protegidas e aprovação do responsável. Não obter a aparência novamente de uma descrição textual. Máscaras/poses ausentes são lacunas explícitas, não campos preenchidos com dados fictícios.
2. **Perfil de cena:** vincular asset-base, clima, iluminação, objetos presentes/alcançáveis, regiões revisadas e ações permitidas. O reuso de um clipe full-frame conserva seu cenário; não recortar e transplantar a personagem automaticamente.
3. **ActionDefinition:** evoluir as tarefas/fingerprints atuais com estados de entrada/saída, recursos exclusivos, duração real, fonte de movimento e revisão. L0 ambiente e L1 microdeformação não podem satisfazer uma ação L2/L3.
4. **EpisodeSpec/manifest único:** adaptar `ProductionSpec`, sem trocar IDs de programas/assets. Acrescentar versão explícita e `timeline_preset`. Preview e produção congelam o mesmo conjunto de referências e decisões. Revisões antigas continuam vinculadas à versão anterior.
5. **AudioSession:** preservar tracks/assets existentes; adicionar playlist ordenada, durações medidas, QA e derivado de mix sem substituir originais. Não invalidar visual quando apenas a música mudar.

## Agenda nova sem regressão

- Preservar `legacy_10_25_45_v1` como representação do cronograma atual, inclusive para manifests que ainda não têm nome de preset.
- Propor `engagement_15_30_45_v2` como default para novos episódios, conforme decisão confirmada.
- Horários são 900/1800/2700 segundos. A ação de cada marco é escolhida apenas entre assets/poses existentes e revisados; não criar fallback de gesto não suportado. Se faltar a ação, apresentar pendência no storyboard e bloquear sua aprovação como executada.
- Validar recursos (mãos, celular, gato), pré-condições e retorno à digitação, além de validar overlap de intervalos.
- Manter iluminação em tempo absoluto; revisar transição do final da noite para o início caso haja repetição 24/7. Não mascarar reset de luz com um loop curto.

## Preview econômico e fiel

- Nível 0: keyframes de início/meio/fim, regiões editáveis, identidade e quadro de pendências.
- Direção: montagem de 8–10s de amostras dos mesmos assets/eventos, com indicação do instante representado; nunca áudio acelerado.
- Movimento: trecho de 20–60s em velocidade normal, incluindo ação e retorno; teste de seam independente.
- Áudio: amostras reais de 15–30s e transições; métricas completas quando possível. Aprovação visual não aprova automaticamente música ou licença.
- Uma alteração invalida apenas aprovações/dependências afetadas. Mostrar claramente “planejado”, “prévia”, “material aprovado” e “render final”.

## UI e compatibilidade

Integrar na sequência atual Ideia → Cena e música → Orçamento → Produção. Primeiro escolher uma baseline; depois variar cena/cor/estilo musical. Pixel art, se retomada, será uma variante revisada da mesma identidade e não um novo personagem padrão. Não adicionar um segundo portal de testes.

Preservar as APIs `/creator`, `/creator/assembly`, `/miniobs`, `/exports` e IDs existentes. Campos novos devem ser opcionais na leitura de dados legados e explícitos em novas gravações. Não desativar revisões de exportação/publicação para facilitar um piloto.

## Operação

Manter filas e workers; adicionar cache por dependência e checkpoints verificados por segmento antes de ampliar duração. Usar reports atuais como base de telemetria e separar custo de chamada externa, CPU/disco/storage e retrabalho. Custo externo zero no reuso não significa custo total zero. Sem alteração do ClipBR ou reinício amplo do compose.
