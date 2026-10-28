# WP-00 — captura de runtime de 28/10/2026

Consulta somente de leitura ao droplet da Lo-Fi Studio, com acesso SSH direto ao IP retornado pela API da DigitalOcean. O alias local `lofi_vps` continuava sem resolver. Nenhum comando alterou serviços, banco, arquivos, configuração, snapshots ou dados.

## Serviços Lo-Fi observados

| Serviço | Tag da imagem | Revisão OCI observada | Identidade da imagem |
|---|---|---|---|
| Studio | `production-cb369c9` | `cb369c97e9f9fb175392f4341296b50d3f42476e` | Igual a creator e export-worker |
| Creator | `production-cb369c9` | `cb369c97e9f9fb175392f4341296b50d3f42476e` | Igual a Studio e export-worker |
| Export worker | `production-cb369c9` | `cb369c97e9f9fb175392f4341296b50d3f42476e` | Igual a Studio e creator |
| YouTube publisher | `production-ed85886` | `1789d4d4cf77917436aaf68a6636c8143fd91738` | Imagem distinta |
| Rádio | `production-be426a8-radio` | `be426a8336312a7bc5b9c0612534f16b187b4c81` | Igual a channel-radio |
| Channel radio | `production-be426a8-radio` | `be426a8336312a7bc5b9c0612534f16b187b4c81` | Igual a rádio |
| Music worker | `production-d877875` | `development` | Tag não determina revisão Git |

Os sete containers Lo-Fi estavam em execução. Studio estava marcado como healthy; creator, export-worker, publisher, rádio, channel-radio e music-worker estavam ativos. A revisão do core (`cb369c9`) coincide com `main` nessa captura. As revisões do publisher (`1789d4d`) e de rádio (`be426a8`) existem no histórico e são ancestrais de `main`, mas são antigas; isso não prova que os bytes das imagens correspondam exatamente a esses commits. A revisão OCI de music-worker não identifica um commit. A observação de estado não substitui teste funcional de cada endpoint.

### Confirmação de disponibilidade — 28/10/2026, 06:52 UTC

Uma segunda consulta SSH somente de leitura, usando diretamente o IP público retornado pela API da DigitalOcean e a chave local `lofi_vps`, confirmou os mesmos sete containers Lo-Fi ativos e as mesmas tags de imagem da captura acima; Studio continuava `healthy`. `ssh -G lofi_vps` ainda não resolve o alias e trata o texto como hostname literal, por isso esta confirmação usou IP conhecido e `StrictHostKeyChecking=yes`. Nenhum comando de escrita foi executado no servidor.

## Caminho de implantação

A chave de deploy configurada no `authorized_keys` executa um caminho fixo no host. O SHA-256 completo do script instalado foi comparado com o arquivo versionado em `origin/main` (`cb369c9`): os bytes correspondem exatamente (`4b97425d…`). Portanto, o código do script que está instalado permanece recuperável na `main`. O script `ops/auto-deploy.sh` proposto no head do PR #63 tem hash diferente (`803d0961…`). O script atualmente instalado declara que atualiza Studio, creator e export-worker; não inclui publisher, rádio, channel-radio nem music-worker. O workflow do PR #63 empacota `studio/`, `web/` e `requirements.txt`, mas não instala o novo `ops/auto-deploy.sh` no caminho fixo chamado pela chave. Assim, o script antigo está preservado em `main`, mas o PR #63 ainda não prova que o publicador ou a nova rotina de deploy serão ativados.

## Comparação dos arquivos das imagens com Git

Foram calculados SHA-256 dentro dos containers para arquivos em `studio/`, `web/` e `requirements.txt`, sem copiar o conteúdo para o host e sem gravar dados no servidor. A comparação foi contra `origin/main` atual e, quando útil, contra revisões históricas rastreáveis:

| Grupo de serviço | Arquivos lidos | Comparação de conteúdo |
|---|---:|---|
| Studio, creator e export-worker (mesma imagem) | 140 | Os 113 caminhos da `main` estão presentes; 112 têm hash idêntico. O único diferente é `requirements.txt`, por CRLF/LF. Há 27 bundles JS adicionais na imagem. |
| YouTube publisher | 128 | Compara exatamente com o commit histórico `0a4a5b4`, exceto CRLF/LF em `requirements.txt`; além dele, a imagem contém 18 bundles JS adicionais. |
| Rádio e channel-radio (mesma imagem) | 104 | 70 arquivos batem com a `main` atual. Os 34 restantes têm conteúdo presente em versões históricas da própria `main`; nenhum arquivo lido ficou sem correspondência por conteúdo e caminho. |
| Music worker | 57 | Todos os 57 arquivos batem com o commit `d877875`; 26 também batem com a `main` atual e os outros 31 são versões antigas encontradas no histórico. |

O container de rádio não inclui oito caminhos existentes na `main` atual — sete módulos de criação/Visual Workshop (`copywriting.py` e seis arquivos `workshop_*`) e um bundle da interface. Como é uma imagem separada, isso pode ser uma seleção de serviço, mas a dependência real de cada rota ainda precisa ser homologada. O music-worker contém só o subconjunto de 57 arquivos comparados; a identidade de conteúdo bate com o commit `d877875`, embora o rótulo OCI esteja como `development`.

Entre os bundles adicionais de Studio e publisher, oito arquivos JS não aparecem em nenhum outro arquivo da pasta web examinada e não têm correspondência no histórico de `main`. Os oito estão preservados no snapshot GitHub do publisher de 27/10; os hashes locais do manifesto foram conferidos e cada conteúdo foi comparado byte a byte com ambos os containers Studio e publisher. Eles permanecem material preservado; não foram removidos nem promovidos à aplicação. Os outros bundles adicionais têm correspondência por caminho/conteúdo no histórico de `main`.

Esse inventário demonstra que o código e os ativos examinados têm conteúdo recuperável no histórico de `main` ou nos snapshots de recuperação, mas não declara equivalência operacional entre serviços. Em particular, a imagem de rádio é um subconjunto montado com revisões históricas e precisa continuar separada do deploy principal até suas dependências e responsabilidades serem homologadas.

## Recuperação e capacidade observada

- O snapshot `lofi-vps-full-pre-main-merge-2026-10-24` continua disponível na DigitalOcean, criado em 24/10/2026. Ele antecede esta captura e não foi restaurado em ambiente isolado.
- O dump local mais recente observado era de 28/10/2026 00:31 UTC, 438.066 bytes, SHA-256 `f7fc1fa6…2c7f0006`. `pg_restore --list` leu seu catálogo com sucesso por streaming, sem gravar arquivos ou restaurar dados. A listagem, hash e tamanho não provam cobertura de volumes/mídia, restauração integral ou recuperação sem perda.
- A partição reportou 154 GB totais, 129 GB usados, 26 GB livres (84% usados). É uma leitura pontual, não uma série histórica.

## Resultado para o SDD

Esta captura atualiza a evidência do WP-00 sobre serviços, identidade das imagens, conteúdo por hash, rotina realmente chamada, material de backup e capacidade. Confirma que o core (`studio`, `creator`, `export-worker`) compartilha uma imagem/revisão, enquanto publisher, serviços de rádio e music-worker têm revisões distintas. O código lido é recuperável pela `main` histórica, com oito bundles preservados somente nos snapshots identificados. A origem funcional dos bundles não referenciados, paridade de rotas/runtime, restore isolado, rollback exercitado e reconciliação do mecanismo de bootstrap continuam pendentes. **TEST-27 não está concluído.**

## Checagem de autenticação do runtime

Uma requisição GET local ao endpoint OpenAPI do Studio retornou HTTP 401 (`Autenticação necessária`). Isso comprova que o endpoint de documentação está atrás do middleware de sessão; não revela a lista de rotas nem comprova as permissões específicas de cada endpoint. A aba da plataforma estava em `/login`, então a matriz runtime de permissões segue pendente de uma sessão autenticada.

## Revalidação read-only — 28/10/2026, aproximadamente 05:15 UTC

O alias local `lofi_vps` ainda não resolvia. A lista autenticada de droplets da DigitalOcean identificou um único droplet ativo compatível com o servidor; usei o endereço retornado pela API com a chave `lofi_vps`, host-key checking estrito e comandos apenas de leitura. O nome observado pelo SSH corresponde ao droplet. Nenhum endereço IP ou conteúdo de chave foi registrado neste documento.

Nova inspeção de estado confirmou os sete containers Lo-Fi ativos e em execução, com as mesmas tags e revisões OCI descritas acima: core em `cb369c9`, YouTube publisher em `1789d4d`, rádio/channel-radio em `be426a8` e music-worker com rótulo `development`. Isso confirma o estado observado, sem provar saúde funcional ou equivalência dos serviços.

A entrada ativa de deploy em `authorized_keys` continua restrita e chama um comando fixo no host. O SHA-256 do executável chamado continua idêntico ao `ops/auto-deploy.sh` de `origin/main` (`cb369c9`, prefixo `4b97425d`). O `ops/auto-deploy.sh` no head atual do PR #63 continua diferente (prefixo `803d0961`). O PR não instala esse script no caminho fixo; o bloqueio de integração permanece. A leitura não abriu `.env`, valores de segredo, conteúdo de banco, volumes ou mídia.

Resultado: a falha do alias não impede mais a consulta autorizada de leitura enquanto a API da DigitalOcean fornecer o droplet atual, mas o alias local segue sem correção. Nenhum arquivo, serviço, banco, configuração ou dado da VPS foi alterado.

## Rechecagem de estado dos containers — 28/10/2026, 05:18 UTC

Uma nova consulta read-only de `docker ps` confirmou sete containers Lo-Fi em execução: Studio (`healthy`, ativo há cerca de 5 h), creator e export-worker (ativos há cerca de 5 h), YouTube publisher, rádio, channel-radio e music-worker (ativos há cerca de 3 dias). As tags de imagem permanecem `production-cb369c9`, `production-ed85886`, `production-be426a8-radio` e `production-d877875`, respectivamente. Também há um container separado `lofi-staging-tunnel-connector` em execução; ele não foi tratado como serviço de produção do Lo-Fi Studio. Estado `Up`/`healthy` confirma apenas o estado reportado pelo Docker nesta consulta, não a disponibilidade funcional de cada rota ou worker. Nenhuma ação remota de escrita foi executada.

## Catálogo PostgreSQL read-only — 28/10/2026, 05:19 UTC

Em transação explicitamente read-only, consultei apenas `information_schema.columns` e os catálogos `pg_class`/`pg_trigger` para as duas tabelas sem DDL rastreado. `public.live_motion_studies` tem `channel_id UUID`, `object_key TEXT` e `report JSONB`; `public.visual_project_budgets` tem `project_id UUID` e `limit_usd NUMERIC`. Ambas informam `lofi_app` como owner e não têm triggers de usuário. A extensão `pg_stat_statements` não está disponível, então esta captura não oferece histórico de consultas para atribuir escritores observados em produção. Não foram lidos registros, valores, credenciais ou dados de mídia. Isso confirma o formato e o owner atuais, mas os catálogos consultados não provam autoria/histórico de criação; ausência de trigger tampouco exclui escritores na aplicação. A busca no código canônico da `main` encontra apenas consultas `SELECT`/existência para essas tabelas, sem DDL nem comandos de escrita nos módulos correspondentes. A origem operacional, os escritores e a retenção continuam sem prova e devem permanecer como descoberta pendente do WP-00.

## Inventário de snapshots/backups DO — 28/10/2026, 05:23 UTC

Uma nova listagem autenticada de imagens do usuário na DigitalOcean retornou um único item: o snapshot privado `lofi-vps-full-pre-main-merge-2026-10-24`, criado em 24/10/2026. A listagem de droplet anteriormente verificada informa `backup_ids` vazio. Não foi criado nem restaurado snapshot nesta consulta. O artefato antecede a captura atual e, sem restore em destino isolado com teste de rollback, continua insuficiente para TEST-27.

## Fingerprint de inicialização do schema — 28/10/2026, 05:24 UTC

O valor de `studio_schema_state.revision`, consultado com transação read-only, coincide com `schema_revision()` calculado dentro do container Studio em execução e com o mesmo cálculo usando o código de `main` no commit `cb369c97e9f9fb175392f4341296b50d3f42476e`: `a644d5c9f624c1203c12a99af9b8764a57b1afe8a6f480b3c4e960d02fae4e21`. Isso confirma que as funções de inicialização incluídas nesse fingerprint coincidem entre runtime, estado registrado no banco e essa revisão da `main`. O fingerprint não identifica a origem de tabelas externas à lista coberta por essas funções, não prova a revisão de cada serviço e não substitui inventário de escritores.

## Estatísticas agregadas das duas tabelas — 28/10/2026, 05:25 UTC

`pg_stat_user_tables` reportou, para cada tabela, um insert, zero updates/deletes e estimativa de uma linha viva; `stats_reset` do banco retornou `NULL`. São contadores agregados, sem conteúdo de linhas, sem autoria de comando/processo e sem intervalo temporal atribuível nesta evidência. Eles confirmam atividade de inserção contabilizada pelas estatísticas atuais, mas não identificam o escritor, nem a criação estrutural, política de retenção ou atualidade exata dos dados. Não usar estes contadores para decidir migração ou exclusão.

## Busca read-only por leitores/escritores das tabelas — 28/10/2026, 05:33 UTC

Pesquisei as referências a `live_motion_studies` e `visual_project_budgets` nos diretórios de aplicação `/app` e `/opt` dos sete containers Lo-Fi ativos, sem importar nem executar código da aplicação. As referências encontradas são:

- `live_motion_studies`: somente `to_regclass` e `SELECT object_key, report` em `studio/live_presentation.py`, arquivo presente no core, publisher e serviços de rádio.
- `visual_project_budgets`: somente `to_regclass` e `SELECT limit_usd` em `studio/workshop_api.py`, no core e publisher.
- Nenhuma referência a essas relações foi encontrada na imagem do music-worker.

A busca não encontrou DDL nem comandos `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` ou `DROP` nessas árvores de aplicação. Portanto, as imagens e versões de aplicação inspecionadas não explicam quem criou as tabelas nem quem inseriu as linhas contabilizadas pelo PostgreSQL. Isso reduz o escopo do código em execução que precisa ser investigado, mas não prova ausência de SQL dinâmico, processos externos, scripts fora de `/app` e `/opt`, jobs históricos ou escritores executados em versões anteriores. Origem, autor, retenção e comportamento de escrita dessas relações continuam sem atribuição demonstrada; não migrar nem remover com base apenas nesta busca.

A consulta foi somente leitura: nenhum serviço, arquivo, dado ou configuração foi alterado. Essa evidência complementa o catálogo e as estatísticas agregadas, mas não fecha esse gate de WP-00.

## Processo principal de cada container — 28/10/2026, 05:34 UTC

`docker inspect` somente de leitura registrou o comando principal dos sete containers Lo-Fi. O Studio executa `uvicorn studio.api:app` na porta 8787. Os demais executam workers/serviços dedicados: `studio.creator_service`, `studio.exports`, `studio.youtube_publish`, `studio.radio`, `studio.channel_radio` e `studio.worker`. Assim, os outros seis containers não apresentam um entrypoint HTTP independente na configuração do container observada; o inventário de 223 operações refere-se ao servidor FastAPI do Studio, e a inspeção de rotas foi corretamente limitada a ele. Isso não exclui portas auxiliares iniciadas por subprocessos ou integrações externas, mas não há entrypoint HTTP adicional declarado nos containers consultados.

Nenhuma configuração ou serviço foi alterado.

## Estado read-only das tarefas pagas incertas — 28/10/2026, 05:49 UTC

Conectei ao droplet pela API autenticada da DigitalOcean e SSH com validação estrita da host key; o alias local `lofi_vps` continua sem resolução. `docker ps` mostrou sete serviços Lo-Fi em execução e o Studio saudável. Em seguida, uma transação PostgreSQL explicitamente read-only consultou somente contagens e agregados de `factory_tasks`, lotes, exports, uploads e lives, e terminou com `ROLLBACK`.

Há **3 tarefas `UNCERTAIN`**, com reserva agregada de **US$ 0,05**; foram criadas entre 27/10 01:52 UTC e atualizadas até 27/10 03:10 UTC. Nenhuma contém `callback_token`, `webhook_event_key`, `provider_job_id` ou `provider_terminal_status`. Isso demonstra que o callback introduzido no PR #71 não consegue reconciliar essas tarefas legadas: ele só poderá ajudar novas solicitações que persistirem o token. Não consultei nem registrei IDs, payloads, prompts, credenciais ou dados de mídia.

Na mesma transação, lotes ativos, exports ativos, uploads em andamento, canais de rádio ao vivo e broadcasts ativos retornaram zero. Uma segunda consulta gerada sobre todos os schemas não sistêmicos encontrou cada uma das seis relações monitoradas em um único schema e confirmou os mesmos totais; assim, a consulta atual do deploy contra `public` cobre essas relações no estado observado. Isso não prova ausência de trabalho em andamento no provedor para os três pedidos incertos. Por essa razão, **não desliguei o droplet nem iniciei snapshot com janela de manutenção**. A janela previamente autorizada continua condicionada a reconciliar essas reservas ou obter evidência suficiente de que elas não têm pedido externo ativo. Nenhum dado, serviço ou configuração foi alterado.

O gate de deploy no PR #63 foi atualizado para contar `UNCERTAIN`, evitando que releases futuros ignorem este estado. Essa barreira protege releases posteriores; não resolve os três registros atuais nem autoriza edição direta no banco de produção.

## Revalidação read-only de serviço, finanças e deploy — 28/10/2026, 08:19 UTC

O alias local `lofi_vps` ainda resolve para o texto literal e não contém o hostname/IP configurado. Para manter a auditoria avançando sem alterar SSH local, a conexão foi feita somente para leitura usando o endereço do único droplet ativo retornado pela API autenticada da DigitalOcean, chave local `lofi_vps` e `StrictHostKeyChecking=yes`; o nome retornado pelo host corresponde ao droplet. Não foi registrado aqui o IP nem qualquer conteúdo de chave.

`docker ps` e `docker inspect` confirmaram novamente os sete serviços Lo-Fi: Studio, creator e export-worker na imagem/revisão `production-cb369c9`/`cb369c9`; publisher em `production-ed85886`/`1789d4d`; rádio e channel-radio em `production-be426a8-radio`/`be426a8`; music-worker em `production-d877875`, rótulo OCI `development`. Os sete estão em execução; o Studio reporta `healthy`. A `main` consultada por Git permanece no commit `cb369c9`, portanto a observação de revisão do core continua consistente com ela.

Uma transação PostgreSQL `READ ONLY`, encerrada com `ROLLBACK`, consultou somente contagens e custo agregado. Permanecem **3 `factory_tasks` em `UNCERTAIN`**, com **US$ 0,05** em reservas; lotes de produção ativos, exports ativos, uploads em andamento, canais live e broadcasts ativos continuam em zero. Não selecionei IDs, payloads, prompts, tokens ou mídia. A partição continua em 154 GB totais, 129 GB usados e 26 GB livres (84%).

O comando de deploy fixado pelo SSH tem SHA-256 `4b97425d9c53e5250de228aa01cbe48faa7a91e3b3a88871226a2272d8793a43`, idêntico ao `ops/auto-deploy.sh` de `origin/main` (`cb369c9`). Isso confirma que a rotina atualmente recuperável é a antiga, não o script atualizado do PR #63. Não houve escrita remota, parada de serviço, criação de snapshot, alteração de dados ou deploy.

## Revalidação de revisão das imagens — 28/10/2026, 09:23 UTC

Uma inspeção read-only dos rótulos OCI confirmou que Studio, creator e export-worker usam a revisão `cb369c97e9f9fb175392f4341296b50d3f42476e`, igual à `main` consultada no GitHub. O YouTube publisher usa `1789d4d4cf77917436aaf68a6636c8143fd91738`; o rádio e channel-radio usam `be426a8336312a7bc5b9c0612534f16b187b4c81`. Comparações de commits com a `main` retornaram, respectivamente, `1789d4d` como ancestral 74 commits atrás e `be426a8` como ancestral 23 commits atrás, sem commits exclusivos dessas revisões em relação à `main`. Isso comprova que os respectivos códigos-fonte estão representados no histórico atual de `main`, mas não que os serviços antigos tenham conteúdo/configuração idênticos aos serviços centrais ou que estejam homologados com eles.

O music-worker continua usando a tag de release `production-d877875`, mas seu rótulo OCI de revisão é `development`; não há SHA de origem verificável por esse rótulo. A imagem não foi comparada por conteúdo com a `main`. A pasta de release inspecionada no host não contém metadados Git, então ela não permite substituir essa lacuna por `git status` ou `HEAD` do checkout.

Conclusão: revisão principal e imagens de publisher/rádio têm proveniência parcial rastreável ao histórico versionado; a imagem do music-worker continua sem proveniência verificável. Mesmo para os serviços rastreáveis, correspondência de SHA ou ancestralidade não demonstra paridade funcional, validade de configuração, comportamento dos workers, nem aprovação de produção. Nenhum arquivo, imagem, serviço ou configuração da VPS foi alterado.

**Gates que permanecem abertos:** corrigir o alias local continua pendente; as três operações pagas incertas não têm evidência de resultado remoto terminal e impedem concluir o backup/restauro isolado sem risco de interromper trabalho externo. O snapshot antigo segue apenas disponível, não restaurado. O PR #63 ainda precisa de uma rota de bootstrap compatível com a regra de mudanças via GitHub e com o comando fixo do host. Esta captura não fecha WP-00 nem TEST-27.
