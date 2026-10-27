# Memória de Growth por canal

## Objetivo

O harness consulta evidências já registradas para o canal em produção de planos criativos e na geração nativa de títulos e descrições. A consulta é isolada pelo `channel_id` e combina similaridade lexical com regras explícitas para formato, intenção, qualidade da amostra e proveniência. É um RAG estruturado e determinístico: não cria embeddings nem faz uma chamada adicional a um provedor.

## Fontes consultadas

- Capturas próprias do YouTube Studio em `analytics_snapshots`: termos de Pesquisa copiados manualmente, tema/título, idade do vídeo, janela e métricas disponíveis.
- Capturas públicas de referências em `reference_observations`: título, intenção, formato, notas e visualizações observadas. Ritmo aproximado só é considerado quando existem pelo menos três vídeos comparáveis do mesmo canal de referência, formato e intenção; não representa CTR, impressões, retenção ou demanda do nosso canal.
- Experimentos humanos concluídos em `growth_experiments`: hipótese, variável e resultado registrado; tratados como observação, não como prova causal.

Cada item recuperado mantém IDs de origem e data. A saída tem versão de esquema e limita o contexto a oito evidências curtas. O texto livre de notas é dado não confiável e nunca pode substituir as regras do harness.

## Atualização contínua

A memória é uma projeção ao vivo das tabelas existentes, não um índice que precisa ser reconstruído. Ao salvar uma nova captura do Studio, observação de referência ou resultado de experimento, a próxima geração do mesmo canal já pode recuperá-la. O harness não promove títulos gerados, sugestões nem métricas inferidas a evidência; a coleta do Studio continua manual e não há promessa de ingestão automática.

## Custos e limites

A recuperação roda localmente no banco, sem custo de embedding ou chamada extra. O texto recuperado entra na chamada de geração já autorizada e no cálculo de reserva existente (máximo de US$ 0,10 para embalagem). Reutilização idempotente considera o digest da memória recuperada: evidência nova altera o contexto e evita reaproveitar uma saída produzida com contexto antigo.

## Uso responsável

Métricas próprias do Studio são a fonte de desempenho do canal. Referências públicas servem para inspiração editorial e hipóteses originais; nunca para copiar títulos ou inferir métricas privadas. Nenhuma ação automática altera vídeos, títulos, miniaturas, playlists, telas finais, publicação ou configuração do canal.

## Integrações

- `studio/creator.py`: usa memória do canal ao criar plano, tema, direção musical e pacote criativo.
- `studio/growth.py`: usa memória ao gerar embalagem de vídeo e retorna fontes/versionamento para auditoria.
- `frontend/src/features/produce.tsx` e `frontend/src/features/library.tsx`: exibem que evidências do canal foram consultadas e persistem IDs de fonte nos metadados nativos de Growth.

## Evolução segura

Uma fonte nova só deve entrar após definir seu escopo de canal, campos de proveniência, regras de confiabilidade/frescor e limite de contexto. Novos sinais devem ser apresentados como hipóteses mensuráveis e avaliados depois no YouTube Studio, com janela e origem comparáveis. A memória é consultiva: aprovação humana segue necessária antes de salvar ou publicar metadados.
