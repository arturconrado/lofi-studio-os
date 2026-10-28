# WP-00 — rechecagem de runtime e deploy (2026-10-28)

## Método e escopo

Consulta somente de leitura ao droplet, em 28/10/2026 às 22:21 UTC. A lista de serviços foi obtida com `docker ps`; as revisões OCI foram lidas por `docker inspect`. Nenhum arquivo, serviço, banco, volume, mídia, configuração ou dado de aplicação foi alterado. Credenciais, conteúdo do banco, endereço do host e valores de ambiente não foram incluídos.

## Serviços observados

| Serviço | Imagem/tag observada | Revisão OCI | Estado observado |
|---|---|---|---|
| Studio | `lofi-studio-os:production-cb369c9` | `cb369c97e9f9fb175392f4341296b50d3f42476e` | `healthy` |
| Creator | `lofi-studio-os:production-cb369c9` | `cb369c97e9f9fb175392f4341296b50d3f42476e` | ativo |
| Export worker | `lofi-studio-os:production-cb369c9` | `cb369c97e9f9fb175392f4341296b50d3f42476e` | ativo |
| YouTube publisher | `lofi-studio-os:production-ed85886` | `1789d4d4cf77917436aaf68a6636c8143fd91738` | ativo |
| Rádio | `lofi-studio-os:production-be426a8-radio` | `be426a8336312a7bc5b9c0612534f16b187b4c81` | ativo |
| Channel radio | `lofi-studio-os:production-be426a8-radio` | `be426a8336312a7bc5b9c0612534f16b187b4c81` | ativo |
| Music worker | `lofi-studio-os:production-d877875` | `development` | ativo |

O Studio/creator/export worker permanecem na revisão `cb369c9`; publisher, serviços de rádio e music worker usam identidades distintas. A observação confirma as diferenças de revisão, mas não demonstra equivalência funcional nem quais rotas cada serviço atende.

## Estado do caminho de deploy

A `main` observada para esta captura é `7966a93dfb0761046fe858c44dce413626499012`. O workflow Checks dessa revisão terminou com sucesso no run [40778344097](https://github.com/arturconrado/lofi-studio-os/actions/runs/40778344097).

O workflow Deploy correspondente terminou com falha no preflight, run [40778828549](https://github.com/arturconrado/lofi-studio-os/actions/runs/40778828549). O log informa que o deployer instalado não retornou `LOFI_DEPLOY_PROTOCOL=2` e encerrou antes de enviar o arquivo de release. Uma consulta de leitura no shell encontrou `lofi-deploy-protocol` ausente do PATH; isso não identifica, por si só, a configuração completa do comando SSH forçado.

Consequentemente, esta captura não mostra a revisão `7966a93` implantada na aplicação. A falha do preflight não substitui a validação da rotina instalada, seu bootstrap, o publicador ou os demais serviços.

## Limites e gates restantes

Esta rechecagem não executou matriz de autorização por papel/endpoint, teste de isolamento com requisições adversariais, atribuição dos escritores das tabelas sem DDL rastreado, restauração de backup, simulação de falha ou rollback. O único snapshot listado pela DigitalOcean continua sendo o snapshot de 24/10/2026; ele não foi restaurado e não comprova recuperação do estado observado em 28/10.

WP-00 e TEST-27 permanecem abertos. Esta evidência é apenas um retrato de runtime e da barreira do deploy; não autoriza instalação remota, mudança de configuração, publicação, geração paga ou limpeza de dados.
