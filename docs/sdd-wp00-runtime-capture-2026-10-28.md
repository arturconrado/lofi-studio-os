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

## Caminho de implantação

A chave de deploy configurada no `authorized_keys` executa um caminho fixo no host. O hash SHA-256 do script instalado começa por `4b97425d`; o script `ops/auto-deploy.sh` do PR #63 começa por `803d0961`. São arquivos diferentes. O cabeçalho do script instalado declara que atualiza Studio, creator e export-worker; não inclui publisher, rádio, channel-radio nem music-worker. O workflow do PR #63 não envia nem instala o script executado pela chave. Portanto, o PR #63 ainda não prova que a mudança de deploy proposta será executada.

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
