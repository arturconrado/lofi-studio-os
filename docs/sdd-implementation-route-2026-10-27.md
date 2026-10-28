# Rota de desenvolvimento do SDD — estado e próximos gates

**Atualizado em 28/10/2026.** Documento de acompanhamento derivado do SDD v1.0 e do estado dos PRs no GitHub. É aditivo: não altera o SDD original, não afirma homologação e não autoriza deploy, escrita na VPS, publicação ou geração paga.

## Estado confirmado

| Frente | Evidência atual | Situação |
|---|---|---|
| WP-00 — descoberta | PR #65 foi mergeado com resumo sanitizado; PRs #67, #68 e #69 preservaram snapshots de arquivos do runtime/cache; captura read-only do runtime em 28/10 registrada em [sdd-wp00-runtime-capture-2026-10-28.md](sdd-wp00-runtime-capture-2026-10-28.md). O `docker inspect` confirma que somente o Studio declara `uvicorn studio.api:app`; os demais seis containers Lo-Fi executam workers/serviços dedicados. A busca nas árvores de aplicação dos sete containers encontrou apenas `to_regclass`/`SELECT` para `live_motion_studies` e `visual_project_budgets`; a autoria dos inserts segue sem explicação. Estado adicional read-only às 05:49 UTC: três tarefas `UNCERTAIN` antigas sem metadados de callback, ID de provedor ou estado terminal; janela de snapshot adiada até reconciliação. PR #71 head `6fcfae2` e PR #66 head `0294609` tiveram CI 284/285 aprovado. | Parcial. O inventário de rotas do Studio coincide com a `main` (223 operações/199 caminhos). A autorização por endpoint em runtime ainda precisa de sessão autenticada; a origem/escritores externos ou históricos das tabelas e TEST-27 permanecem abertos. Publisher, rádio e music-worker usam revisões OCI distintas, e o deployer ativo não instala o script do PR #63. O único snapshot listado pela DigitalOcean é de 24/10 e não foi restaurado isoladamente. |
| WP-01 — versões, persistência e acesso | PR #66 aberto; head `b9a5a29`, sincronizado com a main-base; CI run `40645194495` passou (305 testes Python, 37 frontend, typecheck/build e verificações de interface). A fatia preserva revisão/hash do roteiro, origem/hash da referência e dos clipes, snapshots históricos e a versão inicial dos blocos junto com a reserva financeira. | Parcial. Ainda depende dos gates de WP-00 e não conclui permissões ponta a ponta, proveniência completa, vínculo de aprovações a hashes ou todos os vínculos de artefatos. O código foi atualizado, mas revisão independente do head e aceite do pacote continuam necessários. |
| WP-02 — finanças/operação | PR #61 mergeado unifica o limite; PR #71 trata contagem de reservas em schemas de workspace, callback autenticado/deduplicado para recuperar IDs sem reenviar, histórico de tentativas e pedido de cancelamento local que preserva reconciliação/cobertura quando o envio remoto pode ter ocorrido. Em 28/10, #71 também acrescentou escopo imutável de ações e contadores por entrega/operação para a oficina visual. A captura de produção identificou três tarefas `UNCERTAIN` totalizando US$ 0,05, sem token de callback, ID de provedor ou resultado terminal. | Parcial. TEST-22 simula resposta perdida/callback/recuperação sem segundo POST. TEST-23 cobre persistência após reinício e bloqueio sem chamada ao provedor; histórico de estados e alternativas estão visíveis. TEST-24 simula retomada sem nova chamada paga e bloqueia configuração incompatível. TEST-41 cobre cancelamento local de item ainda enfileirado e solicitação durante envio/execução sem liberar a reserva nem perder o ID original; faltam cenário integrado de queda/reinício após solicitar cancelamento e conciliação verificável do custo terminal. G4-04 agora impede acrescentar novas ações a uma entrega visual com gasto sem revisão explícita; ainda não há contadores agregados por campanha nem a mesma política nos demais motores pagos. Não existe cancelamento remoto documentado no adaptador atual. |
| WP-03 — fluxo existente | PRs #57, #58 e #60 mergeados cobrem partes da Biblioteca, paridade do portal e metadados; PR #63 continua aberto e seu CI passou | Parcial. A regressão integrada com PostgreSQL e o teste de componente confirmam o caminho de piloto aprovado → candidato visível/único na Biblioteca → publicação `ready` idempotente, preservando hash e sem iniciar upload. Ainda faltam a jornada em navegador autenticado contra a versão implantada, recuperação após falha/reinício e paridade com a imagem instalada (G1-02/TEST-01/02/33). O render final do Visual Workshop e a `visual_library` são fluxos de edição/reuso separados, não devem ser confundidos com a Biblioteca de publicação. A rotina de deploy ativa na VPS diverge do script do #63, gerencia três serviços e não inclui o publicador; o workflow também não envia/instala esse script. TEST-27 segue pendente. |
| WP-04 — direção/referências/avaliação | PR #62 (sinais de Growth) e #70 (recuperação de memória por canal/RAG) mergeados | Capacidades disponíveis no código; não substituem validar fontes, direção visual/temporal, calibração e avaliação com evidência do canal. |
| WP-05 — música/som | PR #74 aberto, head `08fe9a0`, CI run `40646215950` aprovado. A montagem final agora registra método, programas/hash/duração/intervalo de cada original, perfil/codec do mix e pendência de audição. Testes locais de áudio relacionados: 9 passaram. | Parcial. A evidência do recibo não substitui demonstrar composição nova dirigida pelo harness (TEST-16) nem audição/revisão vinculada ao hash final e integridade do áudio completo (TEST-17). WP-05 segue condicionado a WP-01/02 e pode avançar em paralelo com WP-04 quando as dependências estiverem atendidas. |
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

**Captura de 28/10:** a lista completa das sete imagens/serviços Lo-Fi, revisões OCI, hash do script de deploy ativo, metadados de dumps locais e espaço em disco está registrada de forma sanitizada em [sdd-wp00-runtime-capture-2026-10-28.md](sdd-wp00-runtime-capture-2026-10-28.md). Studio, creator e export-worker usam a mesma revisão `cb369c9`; publisher usa `1789d4d`, rádio/channel-radio `be426a8`, e music-worker continua marcado apenas como `development`. O snapshot da DigitalOcean de 24/10 ainda não foi restaurado. Esta leitura atualiza a evidência de runtime, mas não fecha TEST-27.

**Ação WP-00 derivada:** reconciliar publisher, rádio, channel-radio e music-worker com os artefatos versionados e com o mecanismo de release, registrando revisão de origem, hash/digest da imagem, arquivos divergentes e o caminho de implantação. Para music-worker, estabelecer uma identidade de build rastreável. Não reconstruir nem trocar imagens até a comparação e os gates de recuperação estarem documentados.

**Dependência externa do deploy:** o workflow versionado envia apenas `studio/`, `web/` e `requirements.txt`; a chave SSH restrita executa um script fixo já instalado no host. O script atualizado do PR #63 não está no arquivo de entrada e o script instalado não se atualiza a si próprio. Portanto, mergear #63 sozinho não instala o próprio deployer no host. Para provar o deploy, é necessário um mecanismo de bootstrap revisável que entregue/instale o script e sua revisão, ou uma ação operacional única autorizada e registrada. Como este projeto proíbe mudanças diretas na VPS, nenhum deploy deve ocorrer até existir uma rota compatível com essa regra; CI verde não supre essa dependência.

O mapa estático de rotas da `main` baseline está em [sdd-wp00-route-map-2026-10-27.md](sdd-wp00-route-map-2026-10-27.md): 223 declarações em 25 módulos, com as regras globais de autenticação extraídas do middleware. Em 28/10, o inventário dinâmico OpenAPI gerado localmente dentro do container Studio teve os mesmos 223 pares método/caminho e o mesmo hash que `main` (`cb369c9`); isso confirma a paridade da lista declarada no Studio, não a execução nem permissões dos endpoints. O [mapa de sistema e dados](sdd-wp00-system-map-2026-10-27.md) reúne 57 tabelas distintas declaradas, dependências e caminhos de composição, além de riscos que exigem prova. A comparação de catálogo identificou 55 nomes em comum e duas tabelas de produção sem DDL rastreado (`live_motion_studies`, `visual_project_budgets`); o histórico confirma consumidores no código, mas ainda não o processo que criou ou grava essas estruturas. Matriz de autorização e paridade das demais imagens/serviços continuam no WP-00.

## Sequência ajustada

### Etapa 1 — fechar WP-00 antes de expandir mudanças estruturais

1. Usar `main` atual como baseline e cruzar cada snapshot dos PRs #67–#69 com o código canônico. Classificar cada divergência como ativa, histórica, configuração, artefato gerado ou ainda indeterminada; não promover snapshots recuperados automaticamente para código executável.
2. Completar os mapas exigidos pelo SDD: preservar a confirmação read-only de que a lista de rotas do Studio coincide com a `main` baseline; completar permissões por endpoint no runtime e rota/paridade das outras imagens/serviços; mapear entidades/dados, serviços/workers/provedores, compositor, versão implantada e dependências entre portais. Incorporar a reconciliação atualizada dos sete containers e das imagens mencionadas acima. Identificar dono, origem e política de retenção das duas tabelas de produção sem DDL rastreado; não fazer migração ou limpeza até localizar seus escritores e dados dependentes. Manter detalhes operacionais/segredos em evidência privada; publicar apenas resumo sanitizado.
3. Reproduzir os relatos funcionais com dados e publicador simulados, ligando resultado à versão e às rotas observadas.
4. Fechar TEST-27 em ambiente isolado: verificar cópia/backup, restaurar em destino descartável, exercitar falha e reversão, e provar qual revisão/scripts a rotina de deploy realmente instala. Não usar uma listagem de dump como prova de restore.
5. Registrar lacuna, causa demonstrada, evidência, migração/reversão e teste de saída. WP-00 só fecha quando o inventário e o plano de migração estiverem completos, incluindo autorização por endpoint, paridade de serviços/rotas e origem/retensão das tabelas observadas; merge de #65 ou snapshots não bastam.

**Gate:** sem saída registrada de WP-00, não ampliar migrações nem declarar WP-01 concluído. Revisões de código podem ocorrer em paralelo, mas a aprovação de pacote permanece condicionada.

### Etapa 2 — terminar WP-01 e WP-02 em incrementos rastreáveis

- **#66:** manter como fatia de versionamento. Após WP-00, obter revisão independente e confirmar testes de edição, histórico, concorrência, isolamento e materiais (TEST-04/06/35/37). O head atual `7db866e` sincroniza a evidência documental do WP-00 até `397b4b6`; o CI run 283 está em execução, enquanto o head anterior `8e1db7b` passou no run 280. O head funcional já recebeu revisão comentada; ainda não representa WP-01 completo. Abrir incrementos separados para permissões ponta a ponta e vínculo de aprovação/hash; não rotular a fatia como WP-01 completo.
- **WP-02:** o risco de `public.creator_plans` ignorar reservas em workspace foi reproduzido em DB limpo e corrigido na branch do #71; a contagem respeita o schema ativo e a conversão de teto de produção em blocos evita dupla contagem. Callback recupera o ID aceito, deduplica eventos, registra uso e mantém a reserva. O TEST-22 simula aceitação com perda da resposta, consulta enquanto incerto sem novo POST, callback, polling do mesmo ID e associação do resultado à tentativa original. A interface diferencia polling do pedido original, callback pendente e ausência de referência persistida; mostra valor/data da reserva e orienta a não gerar novamente. A cota durável por unidade criativa compartilha chave entre continuações e cópias, permite variantes distintas na tentativa inicial e exige justificativa para o ciclo de correção. Uma regressão agora inicia outro processo da aplicação e comprova que a cota continua persistida; depois remove somente resultados sintéticos do projeto de teste, preserva o vídeo-base e confirma que outra solicitação para a unidade é bloqueada sem chamar o provedor. CI passou no head #71 `9319dc8` (run 40645186991: 303 testes Python, 36 frontend) e no head #66 `b9a5a29` (run 40645194495: 305 testes Python, 37 frontend), incluindo typecheck, build e comparação de bundles. TEST-23 ainda precisa apresentar o histórico de decisões e alternativas ao usuário. G4-04 não está completo: faltam cotas agregadas por ação/entrega/campanha e a política nos demais motores pagos. O TEST-24 exercita retomada na rota e worker locais sem nova chamada paga e bloqueia configuração incompatível. O TEST-41 continua parcial: callback `cancelled` preserva ID e reserva, mas não prova cancelamento remoto ou reconciliação final do custo. Não aumentar limites como substituto de cobertura.

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
- **#66:** o review anterior foi feito em head antigo (`71f171c`) e não constitui aprovação do head atual `9df808c`. O CI atual passou no run 255; a saída de WP-00 e a revisão independente do head atual continuam necessárias antes da aprovação formal.
- Os dois PRs foram criados pela conta conectada. A aprovação formal precisa vir de outro revisor; comentário de revisão não equivale a aprovação.
- Não mergear snapshots #67–#69 como aplicação. Eles são evidência de recuperação para comparação, não autorização para sobrescrever `main` ou produção.

## Critério de atualização

A cada PR, atualizar status apenas com evidência ligada ao head atual, testes/cenários cobertos e limitações. Manter separados: revisão do código, CI, teste/homologação em staging, autorização de merge e validação de produção. O SDD original e os dados de produção permanecem sem alteração por este documento.

## Snapshot de acompanhamento — 28/10/2026 08:13 UTC

Esta seção substitui os hashes e estados anteriores somente para os PRs indicados; as seções acima preservam evidências históricas e não devem ser lidas como estado atual.

| PR | Estado observado | Evidência e próximo gate |
|---|---|---|
| #71 — WP-02 | Aberto, base `main`, head `e633f72b78b7f839e97ae604effc968cf5d45a2b`; `MERGEABLE`; CI atual passou; revisão independente e aceite formal continuam pendentes. | Além das reservas e reconciliação já descritas, pedidos de vídeo na fila podem ser encerrados localmente antes do envio; quando o estado é `SUBMITTING`, `RUNNING` ou `UNCERTAIN`, o pedido de cancelamento fica registrado, a mesma tarefa segue reconciliada e a reserva é preservada. O CI `40657842386` passou: 306 testes Python e 37 testes frontend, typecheck, build, checagem do bundle e verificações de interface. TEST-41 ainda parcial; esta entrega não executa cancelamento remoto nem conciliação final do custo. |
| #66 — WP-01 | Aberto, base `docs/sdd-implementation-route-current`, head `53a151780052d93dd28bf41908d02dabd90c1c4a`; `MERGEABLE`; decisão formal de review vazia. | Sincronizado com o head #71 `94dc0db`. CI `40653351948` passou. A fatia ainda depende de WP-00; revisar o head atual e fechar os gates de permissões/proveniência antes de aceite. |
| #63 — WP-03/deploy | Aberto, base `main`; CI anteriormente observado como aprovado. | A rotina fixada no host não é a versão deste PR e não instala a si própria; não aprovar nem executar deploy até haver bootstrap compatível com a regra de alterações via GitHub e evidência de TEST-27. |
| #72 — runtime/schema | Aberto, base `docs/sdd-implementation-route-current` (#71), head `b6691f2b2bbef2bb296951a50898218ad8869f74`; `MERGEABLE`; decisão formal de review vazia. | CI `40654844668` passou na composição atual. Inclui regressão do callback público sem sessão, valida assinatura e mantém `public` sem herdar `LOFI_WORKSPACE_ID`; o token inválido continua sem tarefa (404). WP-00/TEST-37 seguem parciais. |
| #73 — evidências WP-04 | Aberto, base `main`; CI aprovado. | Captura documental parcial; não prova calibração, cobertura de referências nem aceite de WP-04. |
| #74 — proveniência WP-05 | Aberto, base `main`; CI aprovado. | Recibo de montagem parcial; composição nova dirigida pelo harness e revisão auditiva do áudio final continuam pendentes. |

## Atualização de sincronização e validação — 28/10/2026

| PR | Head/base atuais | CI | Situação |
|---|---|---|---|
| #71 — WP-02 | Head `514666d23d1c6969d4c86abb0971e0d87b6f252f`, base `main` | Run `40658397002` (343) passou. O head de implementação `e633f72` também passou no run 342. | Aberto e mergeável; revisão independente e aceite do pacote pendentes. TEST-41 segue parcial. |
| #66 — WP-01 | Head `255e9b1e4ac35c2914d677f101597fc335477ed6`, base atualizada do #71 | Run `40658754010` (346) passou, incluindo bundle combinado. | Aberto e mergeável; WP-01 continua parcial e condicionado a WP-00. |
| #72 — autorização/workspace | Head `10c290f4caa0569a9e56083c8ca254cbe394ea0d`, base atualizada do #71 | Run `40658486105` (345) passou. | Aberto e mergeável; autorização em runtime e TEST-37 permanecem pendentes. |

A sincronização preservou os diffs independentes dos três PRs. Nenhum foi aprovado ou mergeado; não houve deploy, escrita na VPS, alteração na `main` ou geração paga.

## Revalidação final dos heads — 28/10/2026

Após a cobertura integrada que confirma a consulta do estado terminal pelo ID remoto original, os heads foram sincronizados e revalidados:

| PR | Head | CI | Estado |
|---|---|---|---|
| #71 — WP-02 | `376e97136fe2d872fa4050afde4a2ff15e511818` | Run `40659432492` (350) passou. | Aberto e mergeável; TEST-41 continua parcial. |
| #66 — WP-01 | `c0f97dd94c46bc1d59525e46d9a3bf1a12d0860e` | Run `40659444424` (351) passou. | Aberto e mergeável, sincronizado com #71. |
| #72 — autorização/workspace | `3ce9ebf3b86c18b0617d56d27c081b16fb6afa37` | Run `40659457467` (352) passou. | Aberto e mergeável, sincronizado com #71. |

O código de cancelamento mantém reserva e reconcilia o mesmo job após um pedido local; não implementa cancelamento remoto. Ainda faltam o teste de queda/reinício pós-cancelamento e conciliação final verificável do custo. Não houve aprovação formal, merge, deploy, acesso de escrita à VPS ou alteração na `main`.

### Gates ainda abertos para o plano completo

- **WP-00:** ainda não há nova leitura da VPS nesta rodada porque o alias `lofi_vps` resolve para o literal `lofi_vps`, sem hostname configurado. A auditoria read-only, TEST-27 (restauração isolada) e reconciliação de serviço/dados seguem incompletas. Nenhuma escrita na VPS foi feita.
- **WP-01/02:** #66 e #71 têm CI verde (`40653880793` e `40653870924`), mas continuam abertos e sem decisão formal de review; o aceite do pacote depende dos gates do WP-00 e dos cenários SDD que ainda não estão cobertos.
- **WP-03:** #63 não resolve sozinho a instalação do próprio deployer. A jornada autenticada, recuperação após falha e equivalência com a imagem instalada permanecem por demonstrar.
- **WP-04/05:** #73 e #74 são fatias parciais e não fecham os critérios funcionais e de qualidade correspondentes.
- **WP-06 a WP-11:** continuam sem evidência de conclusão integral; FUT permanece fora do caminho crítico do núcleo.

Sem merges, deploys, alterações na VPS, produção, dados ou publicação foram feitos como parte deste snapshot. Como as PRs citadas foram abertas pela conta conectada, a aprovação formal requer uma conta revisora diferente; autoria e CI verde não equivalem a aprovação.

## Revalidação de progresso — 28/10/2026 09:45 UTC

| Frente/PR | Evidência atual | Situação e próximo gate |
|---|---|---|
| WP-00 | Captura read-only de 09:23 confirma Studio/creator/export-worker na revisão atual da `main`; publisher e rádio usam revisões ancestrais da `main`. A comparação prévia de 57 arquivos do music-worker corresponde a `d877875`; o rótulo `development` não identifica essa origem por si só. | Parcial. Correspondência de revisão/conteúdo não prova paridade funcional. Atribuição dos escritores externos/históricos, matriz autenticada de permissões, reconciliação das tarefas `UNCERTAIN`, bootstrap de deploy e TEST-27 seguem pendentes. A última captura financeira detalhada registrada continua sendo 08:19 (3 tarefas `UNCERTAIN`, US$ 0,05 agregado); não foi feita nova leitura financeira às 09:23. |
| #71 — WP-02 | Head `5b6c28219fd4b1c508b837ae0769862f8948c230`, base `main`, aberto e mergeável. CI `Checks` run `40666373862` passou: 307 testes Python; as verificações de frontend, typecheck, build, bundle e interface também passaram. | A fonte de custo usa cobrança final conhecida em vez da reserva maior, e conserva a reserva quando a cobrança é incerta. `/api/budget` consulta o schema ativo e reporta custos conciliados sem duplicar valores de payload. TEST-41 agora simula perda de conexão, reinício em processo novo, consulta do mesmo ID remoto, estado terminal `cancelled` e custo final; não houve chamada paga. WP-02 ainda não fecha G4-04 (limites agregados por ação/entrega/campanha e cobertura equivalente nos demais motores pagos), nem a reconciliação das tarefas legadas sem ID/token. |
| #66 — WP-01 | Aberto, base `docs/sdd-implementation-route-current`, head `e93756db95281f0d793e48ec0650d7adf1499b41`, mergeável. | Parcial e condicionado à saída de WP-00; a fatia de versionamento não conclui permissões/proveniência e aceite integral do pacote. |
| #72 — autorização/workspace | Aberto, base `docs/sdd-implementation-route-current`, head `b194d3a8c5950361f38a4dacf0b6e8700bad03b2`, mergeável. | Parcial; matriz autenticada completa e TEST-37 seguem pendentes. |
| #63 — deploy/publicador | Aberto, base `main`, head `e84af99d7b2441f5857e99d54b052e5702ed2f9f`, mergeável. | CI não comprova instalação: caminho de bootstrap e TEST-27 ainda bloqueiam deploy. |
| #73/#74 — WP-04/WP-05 | Abertos, mergeáveis; evidências anteriores continuam parciais. | Calibração de referência e avaliação (WP-04), composição nova dirigida pelo harness e revisão auditiva do áudio final (WP-05) permanecem sem aceite. |

Sem merge, aprovação formal, deploy, escrita na VPS, publicação ou geração paga nesta atualização. WP-00 ainda bloqueia o aceite dos pacotes dependentes; WP-03 a WP-09 e FUT-10/11 não estão concluídos.

## Revalidação WP-02 — 28/10/2026 09:57 UTC

- PR #71 head `ba3c5d032560e642fd40fbd62fa8c8cb3120b87f`; CI `Checks` run `40667767237` passou: 308 testes Python, Vitest/typecheck/build e verificações de interface.
- No teto financeiro configurado por projeto visual, o uso agora considera a cobrança final conciliada quando disponível; custo desconhecido conserva a reserva. Adicionada regressão PostgreSQL que valida a liberação do excedente e a retenção da reserva incerta. `py_compile` e `git diff --check` também passaram localmente.
- Esta alteração cobre a conciliação financeira do teto existente por projeto. Não cria ainda relações explícitas de campanha/entrega nem contadores agregados por ação, entrega e campanha; portanto G4-04 e WP-02 continuam parciais.
- PR #71 segue aberto e sem merge. O alias SSH ainda não resolve um hostname; a auditoria read-only da VPS não foi repetida. Sem alteração na VPS, `main`, produção ou dados externos.

## Revalidação WP-05 / Shorts — 28/10/2026 10:08 UTC

- PR #74 head `e0876d4ce094ab47a1a63f3610dcdefbf5955b71`; CI `Checks` run `40669061373` passou: 290 testes Python, 34 testes Vitest e verificações de typecheck/build/interface.
- O recibo do Short agora identifica hash e janela da trilha aprovada de origem, programa e revisão, além da política de uma única faixa de áudio sem trilha musical, voz ou efeitos sobrepostos. A regressão inspeciona a saída e confirma uma faixa de áudio.
- A mudança melhora proveniência e comprova a composição atual, que reutiliza um trecho da trilha do vídeo longo. Não implementa direção sonora própria para Shorts, novas músicas/efeitos/voz nem revisão auditiva final; G5-06 e WP-05 seguem parciais.
- PR #74 permanece aberto. Sem merge, publicação, geração paga ou alteração na VPS/`main`.

## Revalidação WP-05 / escolha de trilha para Shorts — 28/10/2026 10:13 UTC

- PR #74 head `6b7aaea2d00e6a314aae7579eca819fb9b914015`; CI `Checks` run `40670263745` (373) está enfileirado. `git diff --check` e compilação Python passaram localmente; o ambiente local não tem `pytest` nem dependências frontend.
- A tela de Shorts permite manter o trecho sincronizado da trilha do vídeo longo ou selecionar uma trilha pronta do canal. Antes de enfileirar a montagem, o servidor revalida pertencimento ao canal, duração, manifesto, integridade do programa e revisão de áudio atual; o contrato rejeita combinações inconsistentes de modo e identificador.
- É reaproveitamento de áudio existente, sem custo de geração. Não equivale a composição musical nova nem direção sonora independente para Shorts; G5-06 e WP-05 permanecem parciais, e a revisão auditiva final ainda precisa de evidência humana.
- PR #74 continua aberto e mergeável. Nenhum merge, publicação, chamada paga ou alteração na VPS/`main` foi realizada.

## Resultado da revalidação WP-05 — 28/10/2026 10:24 UTC

- PR #74 head `ab0b28318f0b73a3971d5c5e5cc7b2f35227976d`; Checks run `40671239425` (377) passou: 290 testes Python, 34 Vitest, typecheck, build, bundle versionado e verificações de interface.
- As falhas anteriores dos runs 373 e 375 eram somente divergência do bundle compilado entre macOS local e Linux CI. O bundle canônico do Linux foi sincronizado; o workflow retornou ao conteúdo original e não faz parte do diff final do PR.
- #74 segue aberto, sem merge. A revisão humana final de áudio e a direção sonora própria de Shorts continuam pendentes; WP-05 e G5-06 seguem parciais.
- O registro deste roteiro está no head #71 `1efec3579f062c702c4ce5a7a7cd22f85fabf599`; Checks run `40670373288` (374) passou. O PR #71 continua aberto e mergeável.
- Sem merge, deploy, escrita na VPS/`main`, publicação ou geração paga.

## Pesquisa de ferramenta para Shorts — G5-09 — 28/10/2026

Consulta de documentação oficial em 28/10/2026; esta é uma decisão de arquitetura de produto, não um teste de integração:

| Referência | Capacidade relevante | Limite para este projeto |
|---|---|---|
| [OpusClip ClipAnything](https://www.opus.pro/clipanything) | Busca momentos com prompts e sinais visuais/sonoros; o fornecedor declara suporte a vídeos com pouco ou nenhum diálogo, ação/personagens e reenquadramento vertical. | É uma ferramenta externa de clipping e análise; seus scores de viralidade não são evidência de demanda nem previsão para nosso canal. Seu uso exigiria enviar a fonte e revisar proveniência/custo fora do pipeline atual. |
| [WayinVideo — escolher a ferramenta](https://help.wayin.ai/en/articles/16146926-which-wayinvideo-tool-should-i-use) e [editor](https://help.wayin.ai/en/articles/16210969-video-editor-overview) | Distingue busca de momentos visuais, clipping, reframing e edição em timeline; documenta ações mesmo quando há pouca narração. | É uma superfície cloud separada; adicionar integração paralela duplicaria seleção, edição, aprovação e fonte financeira que o SDD quer manter canônicas. |
| [WayinVideo — música e efeitos](https://help.wayin.ai/en/articles/15692195-how-to-add-music-and-sound-effects) | Editor pode adicionar áudio próprio, biblioteca de música/efeitos ou geração AI de música/efeitos, ajustar tempo/volume e orientar revisão do mix. Disponibilidade depende de plano/workspace. | Demonstra padrões de direção/mix a estudar, mas não prova que seus ativos, licenças ou critérios de revisão atendem ao canal. |
| [FFmpeg — filtros oficiais](https://ffmpeg.org/ffmpeg-filters.html) | Crop, scale, overlay, split e filtros com linha do tempo permitem reenquadrar e compor localmente em timestamps controlados. | É compositor determinístico, não entende sozinho a semântica de uma cena, escolhe narrativa ou aprova música/efeitos. |

**Decisão: adaptar o fluxo local; dispensar integração com OpusClip/WayinVideo neste marco.** O harness deve analisar materiais aprovados e intervalos reais, propor história e enquadramento vertical, registrar direção sonora e entregar a montagem em Revisão; o compositor existente executa crop/fundo sincronizado e trilhas sem duplicação. Integração futura só será considerada se um gap medido não puder ser coberto localmente, após validar exportação, direitos/proveniência, custo, privacidade, API e experiência de revisão. Nenhuma conta foi conectada, arquivo enviado ou crédito externo consumido.

Esta pesquisa fecha somente a decisão documental de G5-09; não prova implementação de análise visual sem fala, reenquadramento inteligente, direção sonora G5-06, nem os aceites de WP-08/TEST-18/19.

## Revalidação WP-05 / direção sonora narrativa para Shorts — 28/10/2026

- PR #74 head `7507e8d44d0b2efd880c893cd9435630110067f4`; Checks run `40673063578` passou: 290 testes Python, 34 testes Vitest, typecheck/build, bundle Linux versionado e verificações de interface.
- A tela permite selecionar música contínua, pausa breve na virada da história, toque suave no desfecho ou ambos. A montagem aplica os cues localmente nos timestamps narrativos; a pausa afeta a música de origem e o toque é sintetizado localmente. A proveniência registra cues e intervalos; a regressão confirma MP4 vertical decodificável com uma faixa de áudio.
- Isso cobre uma fatia de G5-06, não composição nova dirigida pelo harness (TEST-16), nem revisão humana do áudio completo vinculada ao hash final e integridade (TEST-17). A audição/aprovação humana continua necessária; WP-05 permanece parcial.
- #74 segue aberto e mergeável. Sem merge, deploy, escrita na VPS/`main`, publicação ou geração paga.

## Revalidação WP-02 / cotas agregadas da oficina visual — 28/10/2026

- PR #71 head `8fe41891a6a32748c8eb72b3af0953f5c5b7e6ac`; Checks run `40675136315` passou: 309 testes Python, 37 testes Vitest, typecheck/build, bundle Linux e verificações de interface.
- A primeira reserva paga de uma entrega fixa o inventário de ações da imagem-base e das ações narrativas para a oficina. Imagem e vídeo compartilham o mesmo inventário; cada operação registra usos iniciais e o único ciclo de correção por unidade. Projetos com tarefas históricas recebem escopo inicial reconstruído a partir do rascunho salvo e do histórico de tarefas.
- Para incluir ações fora do escopo, a interface exige uma revisão explícita com motivo, confirma a lista atual e registra o histórico; a revisão não faz chamada paga nem muda o teto financeiro. A próxima geração exige nova cotação e confirmação de custo.
- Isso cobre a unidade entrega/operação no motor visual. G4-04 segue parcial: ainda falta um vínculo canônico de campanha e a aplicação de cotas agregadas equivalentes aos demais motores pagos. TEST-23 não é fechado por esse teste isolado; campanhas, outras engines e reinício/recuperação continuam a exigir aceites próprios.
- #71 permanece aberto, sem merge. Sem deploy, escrita na VPS/`main`, publicação ou chamada paga.

## Revalidação WP-05 / direção musical ligada ao harness — 28/10/2026

- PR #74 head `7e387cbc1f15f05e56ce0fd758bf7a290f07f0bc`; Checks run `40676622125` passou: 292 testes Python, 34 Vitest, typecheck/build, bundle versionado e verificações de interface.
- O worker agora usa um compilador determinístico do pedido de cada faixa: tema aprovado, briefing musical, bíblia/estilo e instrumentos da receita, itens a evitar, BPM, tonalidade e variação são combinados. O texto resultante é o mesmo persistido no prompt do job e enviado ao provedor; testes não chamam o provedor.
- Isto verifica a construção e persistência da direção, não uma saída musical real. TEST-16 ainda exige gerar uma composição nova usando referência autorizada e avaliar ritmo, instrumentos e atmosfera. TEST-17 ainda exige decodificação/integridade e audição do arquivo final vinculado ao hash. WP-05 permanece parcial e sem gasto pago nesta etapa.
- #74 continua aberto e mergeável. Sem merge, deploy, escrita na VPS/`main`, publicação ou geração paga.

## Revalidação WP-01 / integração com a base atual — 28/10/2026

- PR #66 foi sincronizado com a base corrente do #71 (`366c94b27ed37cbe38a3caa06746e20e3d5e8b20`) após resolver conflito na referência do bundle da interface. O bundle final foi recompilado pela execução Linux e o passo temporário de upload de artefato foi removido do workflow.
- Head #66 `ee599eb6dd22d6549c0e58148a6f655c71944c2b` passou no Checks run `40677730874`: 311 testes Python, 38 Vitest, typecheck/build, bundle e verificações de interface. O GitHub agora reporta `CLEAN`/`MERGEABLE`.
- A revisão técnica cobre somente a fatia declarada de versionamento/proveniência de roteiros. WP-01 segue parcial e condicionado à saída de WP-00; permissões, vínculos completos de aprovações/artefatos e aceites remanescentes continuam abertos. CI verde e mergeabilidade não são aprovação formal, homologação nem conclusão do pacote.
- #66 continua aberto, sem merge. Sem deploy, escrita na VPS/`main`, publicação ou geração paga.

## Revalidação WP-01/WP-02 / isolamento e autorização — 28/10/2026

- PR #72 foi sincronizado com o head documental `27bc127ea8a64225ba5c8a981c135012fc9fd307`; novo head `0a2031f23af5121ffe14581a65e041bc2cb48e95` passou no CI `Checks` run `40679017972`. A suíte do CI, verificação de interface, typecheck e build passaram. Testes locais direcionados: 25 aprovados e 43 ignorados por dependerem de ambiente externo.
- A atualização integra os achados mais recentes de WP-02/WP-00 ao código de contexto de workspace e autorização de gasto; não amplia a cobertura de runtime nem altera as permissões do servidor.
- WP-01/WP-02 continuam parciais: matriz de autorização por endpoint, TEST-37 em runtime e os aceites restantes dependem da auditoria WP-00. O alias SSH `lofi_vps` ainda não resolve para o hostname configurado, portanto nenhuma conexão foi iniciada.
- PR #72 segue aberto e mergeável; sem aprovação, merge, deploy, escrita na VPS/`main`, publicação ou geração paga.

## Revalidação dos gates de WP-01/02/03 — 28/10/2026

- PR #66 head `d0e3cc1da963ebd2e6b94a34568fd126d163d2c0`, base documental `4ddba084e6fc2695015b9b8b5abe3375eea4e318`, passou no Checks run `40680226236`. A sincronização apenas incorporou a atualização do roteiro; a fatia WP-01 permanece parcial e condicionada a WP-00.
- PR #72 head `acabd2f321da0bc86a724651d71d74e5716a2c33`, na mesma base, passou no Checks run `40679519558`. TEST-37 e a matriz autenticada do runtime continuam pendentes.
- PR #63 head `909ca6f52134a8dffc60e678dbcc962856c04267` passou no Checks run `40724149004`. O workflow agora consulta o protocolo instalado antes de transmitir o arquivo; `ops/auto-deploy.sh` responde `LOFI_DEPLOY_PROTOCOL=2` sem escrita.
- A captura WP-00 confirma que o deployer atualmente instalado na VPS ainda não reconhece esse protocolo. Com o novo gate, o workflow para antes de enviar qualquer release até que a versão atualizada seja instalada por caminho autorizado. Isso fecha o falso sinal de deploy automático, mas não instala o script, não implanta o publicador e não conclui TEST-27.
- Os PRs continuam abertos; nenhuma aprovação, merge, deploy, conexão à VPS ou alteração de produção ocorreu.

## CI após sincronização documental — 28/10/2026

- Depois do head documental `29483c24efb5058ae643b3cadbb2a18e302df5c5`, #66 foi sincronizado no head `8aea254b04013d0f63fa74beb53d5a660dc87d0f` e passou no Checks run `40746185868`; #72 foi sincronizado no head `e790827c6e4369275c027673ca8cf64e0599eb4f` e passou no run `40746206476`.
- A alteração sincronizada é documental. Os códigos funcionais de WP-01/WP-02 permanecem parciais e ainda dependem das verificações WP-00; mergeabilidade e CI não substituem autorização autenticada em runtime, homologação ou produção.

## WP-00 após login autenticado — 28/10/2026

- O usuário entrou no Studio; `/studio/diagnostico` abriu em sessão autenticada e apresentou o estado visual de serviços. Essa evidência confirma acesso à interface nesta conta.
- A tentativa de abrir `/openapi.json` no navegador foi bloqueada antes de retornar dados. Não houve validação do catálogo dinâmico, códigos HTTP ou permissões das rotas implantadas.
- A matriz por papéis continua pendente: não foram exercitados `viewer`, `creator`, `operator`, `workspace_admin` e Basic admin. WP-00 e TEST-37 permanecem abertos; não se presume que a interface acessível prove autorização correta por endpoint.
- Evidência detalhada registrada em `docs/sdd-wp00-runtime-capture-2026-10-28.md`. Nenhuma mutação foi realizada.

## Novas evidências de G4-02, G4-05 e TEST-37/41 — 28/10/2026

- Em #71, a regressão `test_cancel_video_survives_worker_restart_and_reconciles_same_remote_job_and_cost` foi incluída no head `47c3e0ac80c122de0a89480dd1a13aa72423f512`, aprovado no Checks run `40767324317`. Ela cobre cancelamento antes do envio, pedido de cancelamento em tarefa já aceita, perda da conexão, reinício em outro processo, consulta do mesmo ID remoto e conciliação do custo terminal, sem reenviar a geração. Não houve chamada real paga.
- Em #72, a regressão HTTP `test_paid_http_route_rejects_non_admin_roles_before_reserving` percorre `POST /api/tracks/{id}/generate`: `viewer`, `creator` e `operator` recebem 403; `workspace_admin` alcança o bloqueio de chave ausente; a contagem de jobs permanece zero. Head `60d0a5e90f3af423aeb7a79236d858b1b83bf26b`, Checks run `40768357896` aprovado.
- Estes resultados fecham evidência automatizada específica para TEST-41 e reforçam a autorização de gasto em TEST-37/G4-02. Não fecham WP-02: G4-04 ainda precisa de limites agregados por ação/entrega/campanha e equivalência nos demais motores; operações legadas incertas ainda não têm confirmação terminal.
- TEST-37/WP-00 permanecem parciais: falta executar a matriz completa de papéis e escopos nos endpoints, revisar registros com valores identificáveis e demonstrar as regras contra a revisão efetivamente instalada. Testes de integração locais não substituem homologação no runtime.

## Revalidação de CI e proteção de logs — 28/10/2026

- PR #71 head `887e0dfd7c62bee33958596cd2caf839e5b54c35` passou no Checks run `40768890226`; a atualização inclui testes HTTP/autorização e evidência de cancelamento/reconciliação sem chamada paga.
- PR #66 head `3ceda0da4e60a6a5fb371067a1f311f6cfd75000` passou no run `40768916446`, sincronizado com o head acima. A fatia WP-01 permanece parcial e condicionada a WP-00.
- PR #72 head `e2b32422f8348581a9ef848bbdcc11643d8916f0` passou no run `40769238542`. A nova regressão injeta um texto sentinela na exceção simulada do worker e confirma que não é copiado para o log nem para o detalhe persistido.
- Estes resultados comprovam CI e regressões automatizadas específicas, não a matriz completa de autorização ou revisão de logs no runtime; TEST-37/WP-00 continuam parciais.
- O alias SSH `lofi_vps` continua sem resolver hostname. A tentativa foi somente de conexão não interativa com comando de leitura e falhou antes de abrir sessão; nenhuma operação foi executada na VPS. A auditoria remota e TEST-27 seguem pendentes.
- Os três PRs permanecem abertos e sem merge; nenhuma mudança foi feita em `main`, VPS, produção, mídia, publicação ou provedores pagos.
