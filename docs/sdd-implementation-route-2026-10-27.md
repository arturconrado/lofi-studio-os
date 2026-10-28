# Rota de desenvolvimento do SDD — estado e próximos gates

**Atualizado em 27/10/2026.** Documento de acompanhamento derivado do SDD v1.0 e do estado dos PRs no GitHub. É aditivo: não altera o SDD original, não afirma homologação e não autoriza deploy, escrita na VPS, publicação ou geração paga.

## Estado confirmado

| Frente | Evidência atual | Situação |
|---|---|---|
| WP-00 — descoberta | PR #65 foi mergeado com resumo sanitizado; PRs #67, #68 e #69 preservaram snapshots de arquivos do runtime/cache | Parcial. Os próprios PRs dizem que os snapshots não incluem configuração, banco, volumes, estado/runtime ou mídia e não provam restauração. WP-00 permanece aberto. |
| WP-01 — versões, persistência e acesso | PR #66 aberto; head `32f9b4aa3ce3a7a9f44d174087a98519f2f2ab1b`; CI verde; teste de regressão cobre redaction das revisões após exclusão | Uma fatia implementada; revisão técnica registrada em comentário. O GitHub não permite que o autor aprove o próprio PR, então falta aprovação independente. Ainda depende da saída de WP-00 e não conclui permissões ponta a ponta, proveniência, vínculo de aprovações a hashes ou todos os vínculos de artefatos. |
| WP-02 — finanças/operação | PR #61 mergeado unifica o limite; PR #71 corrige contagem de reservas em schemas de workspace e conversão de blocos dentro do teto autorizado. Acrescenta callback terminal para recuperar ID aceito sem reenviar, com deduplicação, HMAC opcional e preservação da reserva. | Parcial. Isolamento e concorrência têm regressão PostgreSQL. TEST-22 tem simulação ponta a ponta de resposta perdida, callback e recuperação do resultado sem segundo POST. TEST-23 tem prova parcial: processo novo lê a reserva incerta e bloqueia saldo insuficiente; falta validar a decisão/orientação do harness e o limite de reavaliações. TEST-24 tem fluxo local simulado: retoma a mesma tarefa, reutiliza entradas e duração, não repete envios pagos e bloqueia retomar após mudança do projeto. A suíte completa anterior tinha 287 testes aprovados; o head 9da0069 adicionou a regressão para corrida de callback e passou no CI `verify` em 28/10/2026. TEST-41 permanece parcial: callback terminal `cancelled` mantém ID e reserva, mas ainda não há evidência de cancelamento remoto nem reconciliação completa de custo. |
| WP-03 — fluxo existente | PRs #57, #58 e #60 mergeados cobrem partes da Biblioteca, paridade do portal e metadados; PR #63 continua aberto e seu CI passou | Parcial. A regressão integrada com PostgreSQL e o teste de componente confirmam o caminho de piloto aprovado → candidato visível/único na Biblioteca → publicação `ready` idempotente, preservando hash e sem iniciar upload. Ainda faltam a jornada em navegador autenticado contra a versão implantada, recuperação após falha/reinício e paridade com a imagem instalada (G1-02/TEST-01/02/33). O render final do Visual Workshop e a `visual_library` são fluxos de edição/reuso separados, não devem ser confundidos com a Biblioteca de publicação. A rotina de deploy ativa na VPS diverge do script do #63, gerencia três serviços e não inclui o publicador; o workflow também não envia/instala esse script. TEST-27 segue pendente. |
| WP-04 — direção/referências/avaliação | PR #62 (sinais de Growth) e #70 (recuperação de memória por canal/RAG) mergeados | Capacidades disponíveis no código; não substituem validar fontes, direção visual/temporal, calibração e avaliação com evidência do canal. |
| WP-05 — música/som | Nenhum aceite integral do pacote foi demonstrado por estes PRs | A desenvolver após WP-01/02; pode avançar em paralelo com WP-04 quando as dependências forem satisfeitas. |
| WP-06 — experiência conversacional | Ainda não há evidência de conclusão integral nos PRs listados | Protótipo pode avançar após WP-00; execução real depende de WP-01 a WP-05 e de uma proposta canônica única. |
| WP-07 — homologação/escala | Não demonstrada | Aguarda WP-03 a WP-06, TEST-26/27/29 e evidência de recuperação; não declarar capacidade de 4/8 horas sem medição. |
| WP-08/09 — Shorts/campanha | Plano de implementação existe; aceite de um Short narrativo e da campanha não foi demonstrado | Depois de aprovar o núcleo e ativar as regras G4. Manter fluxo, narrativa, duração, som e revisão próprios para Shorts. |
| WP-10/11 — FUT | Evoluções comerciais e convenção temporal | Fora do caminho crítico; iniciar só após dependências indicadas no SDD. |

## Evidência adicional da comparação de snapshots (somente leitura)

Baseline comparada: `origin/main` no commit `cb369c97e9f9fb175392f4341296b50d3f42476e`. As contagens abaixo comparam SHA-256; igualdade de conteúdo não prova que o arquivo seja executado, e divergência não prova que deva ser promovido.

- **music-worker:** 57 arquivos de aplicação capturados; 26 têm mesmo caminho e hash que `main` atual; os outros 31 divergem da versão atual, mas cada conteúdo corresponde exatamente a uma versão histórica do mesmo caminho em `main`. Não há arquivo de aplicação do snapshot sem correspondência histórica no caminho equivalente. Isso identifica a proveniência do conteúdo versionado, mas não identifica qual combinação de revisões compõe a imagem ativa nem prova que o código pode ser reconstruído.
- **youtube-publisher:** a recontagem do snapshot atual encontrou 130 arquivos; 87 têm mesmo caminho e hash, 23 têm caminho existente com hash diferente e 20 caminhos estão ausentes do caminho equivalente em `main`. Nos 23 divergentes, os 21 arquivos de aplicação (17 `studio/` e 4 `web/`) têm blob idêntico em algum ponto do histórico da `main`, embora não sejam as versões atuais desses caminhos. `requirements.txt` difere apenas por CRLF/LF; o `README.md` do snapshot é metadado da captura, não arquivo da aplicação. Uma comparação adicional dos 128 arquivos de aplicação/configuração do snapshot com o commit histórico `0a4a5b4` encontrou 109 correspondências exatas; `requirements.txt` difere apenas por CRLF/LF, e há 18 bundles JS extras. O commit `0a4a5b4` é descendente do rótulo OCI `1789d4d`; portanto, a captura é altamente consistente com o conteúdo-fonte dessa revisão, mas não prova que a imagem tenha sido construída a partir dela. O HTML observado referencia `web/app/assets/index-BrbmqVaJ.js` (SHA-256 `c1639840431067e9f0f1c62ad87c837b7ed42b452a23b943ebb8b18d26f01a75`), cujo conteúdo existe nesse commit histórico; o CSS referenciado também existe em `main`. Os outros 18 bundles JS não aparecem no HTML nem no bundle de entrada observado; 17 também estão no snapshot arquivado do export-worker, um ainda não tem origem atribuída. Os arquivos permanecem preservados dentro do snapshot.
- **cache-code:** 383 arquivos capturados. A comparação por conteúdo identificou 55 caminhos sem conteúdo idêntico em `main` ou nos snapshots dos dois serviços. Revalidei contra as árvores dos 61 branches remotos observados (excluindo a própria cópia do cache): os mesmos 55 não aparecem nos heads desses branches; são 50 caminhos `.py` com 47 conteúdos Python distintos e 5 páginas `.html`, em pastas de validação/experimentos e operações históricas. Isso não prova que os scripts nunca foram executados, nem que devam ser promovidos: a captura demonstra presença no mount `/cache`, mas não execução nem autoria funcional. A revisão de cada script deve identificar efeitos externos, dados/credenciais esperados e se a lógica pertence ao produto antes de qualquer migração.

### Triagem estática dos itens sem correspondência no cache

- `continuity-test-20261023` e `continuity-test-v2-20261023`: seis arquivos Python, dois runners e cópias alternativas de `timeline_compositor.py`/`workshop_continuity.py`.
- `fresh-hd-test-20261023`: 16 arquivos Python, com rotinas de execução, monitoramento, recuperação, registro e orçamento, além de seis cópias de módulos do workshop/compositor.
- `library-catalog-fix-20261023`: 24 arquivos Python e cinco páginas HTML. Inclui ferramentas de publicação/OAuth/diagnóstico e variantes do fluxo Halloween; as páginas HTML são entradas de UI de experimento.
- `quality-hour-review-20261013`: um script de registro; `validation45-20261023`: dois scripts de validação e uma cópia do compositor.
- Uma varredura estática de AST/padrões encontrou, em subconjuntos desses scripts, chamadas de processo, clientes de rede, operações de banco e remoção de arquivos. Em especial, `cleanup_test_chunks.py` e `recover_hd_upload.py` contêm chamadas `unlink`. Nenhum desses scripts foi importado ou executado; não foi validado o alvo, estado atual ou autorização para qualquer efeito.

**Classificação de WP-00:** esses 55 caminhos são conteúdo recuperado e acessível, mas permanecem sem atribuição operacional. Parte é código-fonte de variantes, parte é ferramenta de operação/validação e parte é interface de teste. Manter preservados no snapshot. Antes de portar qualquer item, comparar comportamento e dependências com o produto atual, identificar autor/objetivo e cobrir regressões em ambiente descartável. Não executar rotinas de publicação, recuperação, remoção, autorização ou geração a partir do cache.

A evidência anterior de recuperação em `docs/audit-2026-10-15/evidence` confirma apenas uma cópia local de fontes/entradas: 23 arquivos de código restaurados foram verificados, mas `offsite_full_disaster_restore_tested=false` e `complete_final_mp4s_local_backup=false`. É um resultado histórico útil, porém não fecha o TEST-27 do estado atual.

**Implicação:** WP-00 ainda precisa explicar a versão de origem dos 21 arquivos históricos do publisher e identificar a proveniência do bundle JS ativo preservado no snapshot; os 31 conteúdos do music-worker agora foram atribuídos a versões históricas dos mesmos caminhos em `main`, mas falta explicar qual composição de revisões e dependências gerou a imagem ativa. Também falta revisar os 55 itens de cache sem correspondência. Os 18 bundles sem referência no HTML observado e o manifesto não devem ser tratados como código ativo. Não copiar arquivos ou bundles para caminhos executáveis até atribuir função, origem, dependências, teste, dono e rollback. Contagens são evidência de divergência, não decisão de canonicalidade.

## Verificação read-only do runtime (27/10/2026)

Uma nova consulta somente de leitura ao host e aos metadados das imagens confirmou sete containers Lo-Fi em execução. Creator, Studio e export-worker usam imagem identificada pela revisão `cb369c9` (baseline atual de `main`). Publisher está identificado como `1789d4d`; rádio e channel-radio como `be426a8`; music-worker usa tag `d877875`, mas o rótulo OCI de revisão informa apenas `development`. Os três primeiros SHAs de serviço são ancestrais de `main`; isso não prova que os conteúdos efetivos das imagens sejam byte a byte iguais ao código atual. O rótulo do music-worker tampouco identifica uma revisão Git verificável.

A DigitalOcean também informa que há um snapshot do host, disponível, criado em 24/10/2026. Por ser anterior à observação atual, e sem restauração isolada exercitada, ele não comprova backup atual, consistência de banco/volumes, recuperação sem perda ou fechamento do TEST-27. Nenhum serviço, banco, volume, arquivo ou configuração foi alterado nesta consulta.

Uma comparação read-only posterior ao head do PR #63 confirmou que a rotina atualmente forçada pela chave de deploy na VPS é diferente de `ops/auto-deploy.sh` no PR. A rotina instalada descreve e gerencia Studio, creator e export-worker; não inclui o YouTube publisher. O workflow #63 empacota `studio/`, `web/` e `requirements.txt`, sem a rotina atualizada. Portanto, CI verde no PR não instala nem valida o mecanismo que o host executará. Não houve escrita remota.

**Ação WP-00 derivada:** reconciliar publisher, rádio, channel-radio e music-worker com os artefatos versionados e com o mecanismo de release, registrando revisão de origem, hash/digest da imagem, arquivos divergentes e o caminho de implantação. Para music-worker, estabelecer uma identidade de build rastreável. Não reconstruir nem trocar imagens até a comparação e os gates de recuperação estarem documentados.

**Dependência externa do deploy:** o workflow versionado envia apenas `studio/`, `web/` e `requirements.txt`; a chave SSH restrita executa um script fixo já instalado no host. O script atualizado do PR #63 não está no arquivo de entrada e o script instalado não se atualiza a si próprio. Portanto, mergear #63 sozinho não instala o próprio deployer no host. Para provar o deploy, é necessário um mecanismo de bootstrap revisável que entregue/instale o script e sua revisão, ou uma ação operacional única autorizada e registrada. Como este projeto proíbe mudanças diretas na VPS, nenhum deploy deve ocorrer até existir uma rota compatível com essa regra; CI verde não supre essa dependência.

O mapa estático de rotas da `main` baseline está em [sdd-wp00-route-map-2026-10-27.md](sdd-wp00-route-map-2026-10-27.md): 223 declarações em 25 módulos, com as regras globais de autenticação extraídas do middleware. O [mapa de sistema e dados](sdd-wp00-system-map-2026-10-27.md) reúne 57 tabelas distintas declaradas, dependências e caminhos de composição, além de riscos que exigem prova. A comparação de catálogo identificou 55 nomes em comum e duas tabelas de produção sem DDL rastreado (`live_motion_studies`, `visual_project_budgets`); o histórico confirma consumidores no código, mas ainda não o processo que criou ou grava essas estruturas. Esses mapas ainda não demonstram autorização por endpoint no runtime nem paridade integral das rotas/imagens implantadas; essas verificações continuam no WP-00.

## Sequência ajustada

### Etapa 1 — fechar WP-00 antes de expandir mudanças estruturais

1. Usar `main` atual como baseline e cruzar cada snapshot dos PRs #67–#69 com o código canônico. Classificar cada divergência como ativa, histórica, configuração, artefato gerado ou ainda indeterminada; não promover snapshots recuperados automaticamente para código executável.
2. Completar os mapas exigidos pelo SDD: complementar o mapa estático com permissões por endpoint e confirmação no runtime; mapear entidades/dados, serviços/workers/provedores, compositor, versão implantada e dependências entre portais. Incorporar a reconciliação atualizada dos sete containers e das imagens mencionadas acima. Identificar dono, origem e política de retenção das duas tabelas de produção sem DDL rastreado; não fazer migração ou limpeza até localizar seus escritores e dados dependentes. Manter detalhes operacionais/segredos em evidência privada; publicar apenas resumo sanitizado.
3. Reproduzir os relatos funcionais com dados e publicador simulados, ligando resultado à versão e às rotas observadas.
4. Fechar TEST-27 em ambiente isolado: verificar cópia/backup, restaurar em destino descartável, exercitar falha e reversão, e provar qual revisão/scripts a rotina de deploy realmente instala. Não usar uma listagem de dump como prova de restore.
5. Registrar lacuna, causa demonstrada, evidência, migração/reversão e teste de saída. WP-00 só fecha quando o inventário e o plano de migração estiverem completos, incluindo autorização por endpoint, paridade de serviços/rotas e origem/retensão das tabelas observadas; merge de #65 ou snapshots não bastam.

**Gate:** sem saída registrada de WP-00, não ampliar migrações nem declarar WP-01 concluído. Revisões de código podem ocorrer em paralelo, mas a aprovação de pacote permanece condicionada.

### Etapa 2 — terminar WP-01 e WP-02 em incrementos rastreáveis

- **#66:** manter como fatia de versionamento. Após WP-00, obter revisão independente e confirmar testes de edição, histórico, concorrência, isolamento e materiais (TEST-04/06/35/37). Abrir incrementos separados para permissões, proveniência e vínculo de aprovação/hash; não rotular a fatia como WP-01 completo.
- **WP-02:** o risco de `public.creator_plans` ignorar reservas em workspace foi reproduzido em DB limpo e corrigido na branch do #71; a contagem respeita o schema ativo e a conversão de teto de produção em blocos evita dupla contagem. Callback recupera o ID aceito, deduplica eventos, registra uso e mantém a reserva. O TEST-22 simula aceitação com perda da resposta, consulta enquanto incerto sem novo POST, callback, polling do mesmo ID e associação do resultado à tentativa original. O TEST-23 tem cobertura parcial por novo processo Python que reencontra a reserva incerta e recusa uma segunda reserva acima do teto; faltam limite de tentativas/reavaliação e orientação contextual. O TEST-24 exercita retomada na rota e worker locais, mantendo o mesmo plano, fontes, duração e tarefa, sem nova chamada paga; mudança incompatível bloqueia a retomada. A suíte completa anterior tinha 287 aprovados em PostgreSQL descartável; o head 9da0069 (incluindo callback terminal, cancelamento e corrida com resposta do POST) passou no CI `verify` em 28/10/2026. O cenário mantém ID original e reserva, mas TEST-41 continua parcial: não prova cancelamento remoto nem reconciliação final do custo. Não aumentar limites como substituto de cobertura.

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

- **#63:** não aprovar enquanto o caminho de instalação do script atualizado no host e TEST-27 não tiverem evidência. A verificação read-only confirmou que o comando ativo é diferente do script proposto e não gerencia o publicador; CI verde não cobre esses gates.
- **#66:** o code review atual não apontou defeito novo no head e o CI está verde, mas a saída de WP-00 e a revisão independente ainda são condições para aprovação formal.
- Os dois PRs foram criados pela conta conectada. A aprovação formal precisa vir de outro revisor; comentário de revisão não equivale a aprovação.
- Não mergear snapshots #67–#69 como aplicação. Eles são evidência de recuperação para comparação, não autorização para sobrescrever `main` ou produção.

## Critério de atualização

A cada PR, atualizar status apenas com evidência ligada ao head atual, testes/cenários cobertos e limitações. Manter separados: revisão do código, CI, teste/homologação em staging, autorização de merge e validação de produção. O SDD original e os dados de produção permanecem sem alteração por este documento.
