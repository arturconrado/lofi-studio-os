# Rota de desenvolvimento do SDD — estado e próximos gates

**Atualizado em 27/10/2026.** Documento de acompanhamento derivado do SDD v1.0 e do estado dos PRs no GitHub. É aditivo: não altera o SDD original, não afirma homologação e não autoriza deploy, escrita na VPS, publicação ou geração paga.

## Estado confirmado

| Frente | Evidência atual | Situação |
|---|---|---|
| WP-00 — descoberta | PR #65 foi mergeado com resumo sanitizado; PRs #67, #68 e #69 preservaram snapshots de arquivos do runtime/cache | Parcial. Os próprios PRs dizem que os snapshots não incluem configuração, banco, volumes, estado/runtime ou mídia e não provam restauração. WP-00 permanece aberto. |
| WP-01 — versões, persistência e acesso | PR #66 aberto; head `32f9b4aa3ce3a7a9f44d174087a98519f2f2ab1b`; CI verde; teste de regressão cobre redaction das revisões após exclusão | Uma fatia implementada e revisada em comentário. Ainda depende da saída de WP-00 e não conclui permissões ponta a ponta, proveniência, vínculo de aprovações a hashes ou todos os vínculos de artefatos. |
| WP-02 — finanças/operação | PR #61 mergeado unifica o limite de gasto com IA | Base entregue. Confirmar cobertura dos casos de reserva atômica, concorrência, timeout, reinício, reconciliação e cancelamento antes de ampliar autonomia paga. |
| WP-03 — fluxo existente | PRs #57, #58 e #60 mergeados cobrem partes da Biblioteca, paridade do portal e metadados; PR #63 continua aberto | Parcial. #63 ainda requer correção/verificação do caminho que instala `ops/auto-deploy.sh` no host e TEST-27. |
| WP-04 — direção/referências/avaliação | PR #62 (sinais de Growth) e #70 (recuperação de memória por canal/RAG) mergeados | Capacidades disponíveis no código; não substituem validar fontes, direção visual/temporal, calibração e avaliação com evidência do canal. |
| WP-05 — música/som | Nenhum aceite integral do pacote foi demonstrado por estes PRs | A desenvolver após WP-01/02; pode avançar em paralelo com WP-04 quando as dependências forem satisfeitas. |
| WP-06 — experiência conversacional | Ainda não há evidência de conclusão integral nos PRs listados | Protótipo pode avançar após WP-00; execução real depende de WP-01 a WP-05 e de uma proposta canônica única. |
| WP-07 — homologação/escala | Não demonstrada | Aguarda WP-03 a WP-06, TEST-26/27/29 e evidência de recuperação; não declarar capacidade de 4/8 horas sem medição. |
| WP-08/09 — Shorts/campanha | Plano de implementação existe; aceite de um Short narrativo e da campanha não foi demonstrado | Depois de aprovar o núcleo e ativar as regras G4. Manter fluxo, narrativa, duração, som e revisão próprios para Shorts. |
| WP-10/11 — FUT | Evoluções comerciais e convenção temporal | Fora do caminho crítico; iniciar só após dependências indicadas no SDD. |

## Evidência adicional da comparação de snapshots (somente leitura)

Baseline comparada: `origin/main` no commit `cb369c97e9f9fb175392f4341296b50d3f42476e`. As contagens abaixo comparam SHA-256; igualdade de conteúdo não prova que o arquivo seja executado, e divergência não prova que deva ser promovido.

- **music-worker:** 57 arquivos capturados; 26 têm mesmo caminho e hash em `main`; 31 têm caminho existente com hash diferente.
- **youtube-publisher:** 128 arquivos; 87 têm mesmo caminho e hash; 22 têm caminho existente com hash diferente; 19 caminhos não existem em `main`.
- **cache-code:** 383 arquivos capturados. A comparação por conteúdo identificou 55 itens cujo conteúdo não aparece nos arquivos de código rastreados em `main` nem nos snapshots dos dois serviços; a revisão registrada no PR #69 identificou 47 conteúdos Python distintos entre esses itens.

**Implicação:** WP-00 ainda precisa classificar os 31 + 22 arquivos divergentes e os 19 caminhos ausentes do publisher, e revisar os 55 itens de cache sem correspondência. Não copiar nenhum desses arquivos para caminhos executáveis até atribuir função, origem, dependências, teste, dono e rollback. Contagens são evidência de divergência, não decisão de canonicalidade.

## Sequência ajustada

### Etapa 1 — fechar WP-00 antes de expandir mudanças estruturais

1. Usar `main` atual como baseline e cruzar cada snapshot dos PRs #67–#69 com o código canônico. Classificar cada divergência como ativa, histórica, configuração, artefato gerado ou ainda indeterminada; não promover snapshots recuperados automaticamente para código executável.
2. Completar os mapas exigidos pelo SDD: rotas reais e permissões, entidades/dados, serviços/workers/provedores, compositor, versão implantada e dependências entre portais. Manter detalhes operacionais/segredos em evidência privada; publicar apenas resumo sanitizado.
3. Reproduzir os relatos funcionais com dados e publicador simulados, ligando resultado à versão e às rotas observadas.
4. Fechar TEST-27 em ambiente isolado: verificar cópia/backup, restaurar em destino descartável, exercitar falha e reversão, e provar qual revisão/scripts a rotina de deploy realmente instala. Não usar uma listagem de dump como prova de restore.
5. Registrar lacuna, causa demonstrada, evidência, migração/reversão e teste de saída. WP-00 só fecha quando o inventário e o plano de migração estiverem completos; merge de #65 ou snapshots não bastam.

**Gate:** sem saída registrada de WP-00, não ampliar migrações nem declarar WP-01 concluído. Revisões de código podem ocorrer em paralelo, mas a aprovação de pacote permanece condicionada.

### Etapa 2 — terminar WP-01 e WP-02 em incrementos rastreáveis

- **#66:** manter como fatia de versionamento. Após WP-00, obter revisão independente e confirmar testes de edição, histórico, concorrência, isolamento e materiais (TEST-04/06/35/37). Abrir incrementos separados para permissões, proveniência e vínculo de aprovação/hash; não rotular a fatia como WP-01 completo.
- **WP-02:** auditar o que o #61 cobre contra TEST-21/22/23/24/41. Implementar apenas os casos sem evidência, primeiro com adaptador de provedor simulado. Não aumentar limites como substituto de cobertura.

### Etapa 3 — destravar WP-03 e o caminho de deploy

- **#63:** antes de aprovação, incluir no mecanismo de release a versão correta de `ops/auto-deploy.sh` (ou documentar e verificar outra fonte imutável que o host realmente instala), manter os gates de readiness/rollback e fechar TEST-27 numa cópia isolada.
- Validar a jornada com publicador simulado: aprovação → Biblioteca → envio/reconciliação, mesmo hash aprovado e enviado, reconexão sem duplicata (TEST-01/02/25/34/39).
- Não confundir merge de código com implantação em produção. Deploy requer gate e autorização próprios, com revisão anterior preservada.

### Etapa 4 — qualidade do núcleo: WP-04 e WP-05

Depois de WP-01/02 e da referência funcional de WP-03, avançar em paralelo:

- **WP-04:** corpus de referência, ações e junções, validações visuais/temporais, calibração e evidência; Growth/RAG só recomenda com evidência associada e sem sobrepor a intenção aprovada (TEST-03/07–13/28/30).
- **WP-05:** auditoria do acervo usado, proveniência e direitos, composição nova orientada pelo harness, mix completo e revisão auditiva (TEST-16/17/38/40). Faixa existente não serve como prova de composição nova.

### Etapa 5 — experiência, homologação e Shorts

- **WP-06:** consolidar canal, proposta editável, custos cobertos para prévia e acompanhamento em uma fonte canônica. Implementar a experiência conectada somente após os contratos do núcleo.
- **WP-07:** executar jornada completa na aplicação, segundo cenário/configuração, recuperação e medições comparáveis. TEST-26/27/29 devem registrar ambiente, recursos, hashes e limites demonstrados.
- **WP-08:** primeiro Short narrativo com acervo compatível, quadro vertical, história, duração e áudio próprios; revisão individual (TEST-18/19/32/38/39).
- **WP-09:** campanha e calendário só após validação do Short; agendamentos continuam dependendo de autorização explícita e fuso confirmado (TEST-20).
- **WP-10/11:** FUT permanece posterior e opcional.

## Regras de revisão/aprovação para os PRs abertos

- **#63:** não aprovar enquanto o caminho de instalação do script e TEST-27 não tiverem evidência; CI verde não cobre esses gates.
- **#66:** o code review atual não apontou defeito novo no head e o CI está verde, mas a saída de WP-00 e a revisão independente ainda são condições para aprovação formal.
- Os dois PRs foram criados pela conta conectada. A aprovação formal precisa vir de outro revisor; comentário de revisão não equivale a aprovação.
- Não mergear snapshots #67–#69 como aplicação. Eles são evidência de recuperação para comparação, não autorização para sobrescrever `main` ou produção.

## Critério de atualização

A cada PR, atualizar status apenas com evidência ligada ao head atual, testes/cenários cobertos e limitações. Manter separados: revisão do código, CI, teste/homologação em staging, autorização de merge e validação de produção. O SDD original e os dados de produção permanecem sem alteração por este documento.
