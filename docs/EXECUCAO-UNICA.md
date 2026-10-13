# Execução assistida na DigitalOcean (sem custo adicional de infraestrutura)

## Status e limitações

Este pacote foi validado localmente com testes Python e verificações de sintaxe.
Não foi executado na VPS real. Precisa de operador autenticado via SSH ou Console DigitalOcean.
O pacote implanta **portal + fila de produção + catálogo**. A rádio 24/7, OAuth/RTMP do YouTube e publicação pública NÃO fazem parte desta versão.
A geração via OpenRouter depende de chave do usuário, de endpoint realmente disponível e dos direitos aplicáveis; os custos pagos estão desativados.

## Proteções obrigatórias

- Custo de DigitalOcean mantido: não cria novas instâncias ou serviços extras.
- Não interrompe nem recria Caddy, PostgreSQL, Redis, MinIO, API ou web antigos.
- Workers antigos apenas suspensos com confirmação manual e health-check básico, e podem ser restaurados.
- Banco, bucket e credenciais exclusivos do Lo-Fi; sem exclusão de volumes.
- Porta de portal publicada apenas em `127.0.0.1:18787` no host da VPS.
- O GitHub Actions do SuperCorteLikes pode religar workers durante deploy. Ajuste `VPS_AUTO_DEPLOY_DISABLED=true` em Settings → Secrets and variables → Actions → Variables no repositório, antes da redução. Confirme também que não há workflow de implantação em execução.
- A suspensão dos workers NÃO substitui backup consistente dos dados existentes. Para tarefas que possam estar em voo, verifique filas antes de suspender.

## Passo 1: transportar e abrir SSH

No computador usado como *terminal* (nenhuma geração/edição/streaming ocorre nele):

```bash
scp ~/Downloads/lofi-vibe-coding-cloud-v1-1.zip root@162.243.114.141:/root/
ssh root@162.243.114.141
```

Na VPS:

```bash
cd /opt
unzip -n /root/lofi-vibe-coding-cloud-v1-1.zip
cd /opt/lofi-vibe-coding-cloud-v1
bash scripts/go-live.sh inspect
```

## Passo 2: redução reversível (interativa)

Valide manualmente que o site, o login e a API respondem antes de prosseguir.

```bash
bash scripts/go-live.sh reduce
```

O executor verifica a aplicação antiga, registra estados, suspende o `worker`, solicita validação manual, suspende o `media-worker`, solicita nova validação. Se a validação for recusada, tenta restaurar os workers. A observabilidade permanece ativa.

## Passo 3: deploy do Lo-Fi isolado

```bash
bash scripts/go-live.sh deploy
bash scripts/go-live.sh smoke
```

O executor cria `.env` privado, provisiona banco e bucket próprios, constrói a imagem, inicia o portal e o worker, e verifica a infraestrutura. Se o smoke falhar, tenta parar apenas os containers Lo-Fi. O SuperCorteLikes não é recriado.

## Passo 4: acesso remoto seguro

No terminal do computador administrador:

```bash
ssh -N -L 18787:127.0.0.1:18787 root@162.243.114.141
```

Abra `http://127.0.0.1:18787` no navegador; no primeiro acesso o portal solicita HTTP Basic sobre o túnel SSH.
Na VPS, um operador autorizado pode consultar as credenciais administrativas com `sudo grep '^STUDIO_ADMIN_' /opt/lofi-vibe-coding-cloud-v1/.env` **sem compartilhá-las em chat**.

## Passo 5: integração OpenRouter

No servidor, edite `/opt/lofi-vibe-coding-cloud-v1/.env` adicionando `OPENROUTER_API_KEY` diretamente, com um editor local e controle de permissões. Não envie a chave no chat. Após salvar:

```bash
cd /opt/lofi-vibe-coding-cloud-v1
docker compose up -d --no-deps --force-recreate studio music-worker
bash scripts/go-live.sh smoke
```

Faça uma geração gratuita de teste. A integração não tem fallback pago. O modelo padrão é `google/lyria-3-pro-preview:free`; o endpoint pode apresentar limites/indisponibilidade.

## Reversão

Para parar somente o Lo-Fi e restaurar os workers antigos:

```bash
cd /opt/lofi-vibe-coding-cloud-v1
bash scripts/go-live.sh rollback
```

Para apenas parar o Lo-Fi sem alterar o estado de workers antigos:

```bash
docker compose stop music-worker studio
```

## Verificação de recursos

```bash
free -h
docker stats --no-stream
df -h /
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Não execute `docker system prune`, `docker compose down -v`, upgrades de planos ou operações globais de limpeza para executar esse procedimento.
