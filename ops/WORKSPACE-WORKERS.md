# Workers por workspace

O provisionador deve ser executado por um administrador em terminal confiável, com o código do projeto disponível. A API não recebe acesso ao Docker nem cria recursos a cada cadastro.

```bash
python -m studio.workspace_workers \
  --workspace UUID_DO_WORKSPACE \
  --image lofi-studio-os:VERSAO_APROVADA \
  --network REDE_LOFI \
  --env-file /caminho/privado/.env \
  --output-dir /caminho/privado/workers/UUID_DO_WORKSPACE
```

O comando confirma a existência do workspace, membership e schema, e prepara arquivos privados sem iniciar processos. Acrescente `--apply` para iniciar os dois workers após verificar a capacidade da VPS. Use o mesmo diretório para atualizar um workspace existente; projetos e volumes são identificados pelo UUID completo.

Cada workspace recebe worker de música (0,15 CPU / 256 MB), exportador (0,20 CPU / 384 MB), cache próprio e namespaces de banco, Redis e mídia. Esses limites precisam ser ajustados após benchmark de exportação longa; o teste de startup não comprova desempenho de renderização de 4h. O provisionador não habilita geração paga ou streaming e não copia conteúdo. As configurações financeiras e chaves de geração vêm exclusivamente do banco do usuário.

Só são encaminhadas as credenciais de infraestrutura necessárias ao banco, Redis, armazenamento e criptografia. Chaves administrativas de OpenRouter, Resend, senha do administrador e configuração de cadastro ficam fora dos workers. Os arquivos gerados têm permissão 600 e devem permanecer fora do Git. A conexão ao banco usa o mesmo papel de infraestrutura; schemas e prefixos são isolamento da aplicação, não uma barreira contra comprometimento do próprio worker.

Os containers executam como usuário da imagem, com filesystem de leitura, privilégios removidos, sem portas públicas e sem socket Docker. O ajuste inicial do proprietário do cache usa um container temporário sem rede. O cache é um volume externo explícito e não é removido ao parar o projeto.

## Capacidade e operação

O provisionamento é administrativo e limitado pela capacidade aprovada. Não executar automaticamente para cadastros ilimitados. Geração depende de credenciais próprias, confirmação de custo e limites financeiros. Criador de programas e transmissores por workspace ainda precisam de provisionamento equivalente; esses dois workers não representam o pipeline completo.

Para parar sem apagar o cache:

```bash
docker compose -f /caminho/privado/workers/UUID_DO_WORKSPACE/compose.json stop
```

## HTTPS de staging

A API de testes permanece em `127.0.0.1:18889`. As portas 80/443 pertencem ao proxy do ClipBR e não devem ser alteradas por este provisionamento. O domínio `staging.lofistudiox.com` está conectado por um túnel exclusivo e protegido por Cloudflare Access, restrito ao administrador autorizado. O conector valida o JWT do Access antes de encaminhar à API. Não usa as portas 80/443 do ClipBR. Cadastro público permanece desativado. O manifesto do túnel usa uma imagem fixada por digest e referencia um arquivo privado `tunnel.token`, excluído do Git.
