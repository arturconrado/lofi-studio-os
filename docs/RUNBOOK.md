# Lo-Fi Vibe Coding Cloud v1 — implantação sem impactar SuperCorteLikes

## Contrato de operação

- **Não** criar Droplet nem serviços pagos extras.
- **Não** executar `docker compose down` no projeto `clipbr-vps`.
- **Não** apagar imagens/volumes do projeto anterior; nada de `docker system prune` global.
- Não parar PostgreSQL, Redis, MinIO, Web, API ou Caddy.
- Os workers secundários do SuperCorteLikes só podem permanecer suspensos **após** teste real de login/API e da fila.
- **GitHub Actions:** confirmar `VPS_AUTO_DEPLOY_DISABLED=true`, porque o deploy antigo executa `docker compose up` de todos os serviços e pode reativar os workers.
- Não habilitar `PAID_GENERATION_ENABLED` ou mudar `:free` sem autorização financeira explícita.

## 0. Pré-requisitos e auditoria (somente leitura)

Acesse a VPS por console ou SSH autorizado. Não use root para operações diárias depois do bootstrap. Confirme os containers, rede e memória:

```sh
cd /opt/lofi-vibe-coding-cloud-v1
./scripts/preflight.sh
```

Se `clipbr-vps_default` não existir, `configure.sh` tentará identificar a rede pelo container PostgreSQL. Verifique manualmente com `docker inspect` antes de iniciar.

## 1. Enviar o pacote

Baixe o ZIP desta conversa e, de seu computador **apenas como transporte de arquivo**:

```sh
scp lofi-vibe-coding-cloud-v1.zip root@162.243.114.141:/root/
ssh root@162.243.114.141
mkdir -p /opt
unzip -n /root/lofi-vibe-coding-cloud-v1.zip -d /opt
cd /opt/lofi-vibe-coding-cloud-v1
```

O Mac não será usado para geração ou transmissão; só copiará o pacote e acessará o portal.

## 2. Configuração e provisionamento isolado

Este passo **cria banco novo** e **bucket exclusivo**, sem modificar as tabelas ou arquivos antigos. `scripts/configure.sh` busca apenas o Redis password do arquivo local do projeto anterior (não exibe no Terminal).

```sh
cd /opt/lofi-vibe-coding-cloud-v1
./scripts/configure.sh
./scripts/provision-postgres.sh
./scripts/provision-minio.sh
```

**Antes do passo 2:** confirmar backup consistente do banco e MinIO existentes; a VPS não tem snapshot automático associado no levantamento anterior. Se faltar espaço para backup, pare e decida outra estratégia sem contratar serviço novo.

Se o ambiente antigo não estiver em `/srv/clipbr/app/.env.production`, altere o caminho nos scripts e valide a configuração. Não compartilhe `.env` nem chaves nesta conversa.

## 3. Subir somente dois serviços leves

```sh
docker compose config --quiet
nice -n 10 docker compose build
docker compose up -d --no-deps studio music-worker
docker compose ps
./scripts/status.sh
```

O portal fica **apenas no loopback da VPS**: `127.0.0.1:18787`.

## 4. Acesso seguro sem expor a porta à internet

No computador de administração, abra um túnel (não é processamento da aplicação):

```sh
ssh -N -L 18787:127.0.0.1:18787 root@162.243.114.141
```

Abra `http://127.0.0.1:18787` no navegador. O login é Basic Auth do MVP **sobre o túnel SSH**. Veja as credenciais no `.env` **na VPS** com `grep '^STUDIO_ADMIN_' .env`; não as compartilhe.

**Nunca publique a porta 18787 diretamente na internet:** Basic Auth isolada não é substituto adequado para SSO e HTTPS público com proteção contra brute force.

## 5. Primeiro catálogo

O banco será inicializado com 10 prompts. Pelo portal, execute esta ordem:

1. Verifique PostgreSQL/Redis/MinIO no painel Infraestrutura.
2. Abra `Music Factory`, selecione `LVC-001` e confira o prompt.
3. Insira `OPENROUTER_API_KEY` no `.env` (edição na VPS, nunca no navegador).
4. Execute `docker compose up -d --force-recreate studio music-worker` após atualizar `.env`.
5. Faça **uma única** geração gratuita com `google/lyria-3-pro-preview:free`.
6. Se houver áudio, escute integralmente e registre a licença comercial válida para essa faixa e provedor antes de aprová-la.
7. Se a API falhar, mantenha o status FAILED; **não** mude para paid automaticamente.

A integração Lyria não foi validada com a conta do usuário; o decoder suporta áudio base64 nos envelopes multimodais conhecidos e falha fechado quando a saída não é áudio reconhecível.

## 6. Monitoramento e proteção de recursos

- `docker stats --no-stream` e `free -h` devem ser observados após subida.
- Studio: 420 MB e 0,4 vCPU; Music Worker: 600 MB e 0,45 vCPU.
- Ambos usam logs com rotação, filesystem read-only e sem portas públicas.
- Não ativar a rádio ainda: é preciso ao menos um catálogo comercialmente validado, testes privados e um encoder de transmissão controlado.
- A stack Grafana/Prometheus/Loki existente permanece intacta neste deploy. Novo dashboard e métricas podem ser adicionados depois, com mudanças explícitas de configuração.

## 7. Rollback somente do Lo-Fi

```sh
cd /opt/lofi-vibe-coding-cloud-v1
docker compose stop music-worker studio
```

Isso **não** apaga banco `lofi_studio`, bucket `lofi-vibe-coding`, nem altera containers do SuperCorteLikes.
Para reativar: `docker compose up -d --no-deps studio music-worker`.

## Limitações honestas desta primeira entrega

- A rádio 24/7, YouTube OAuth, transcodificação de vídeos, n8n e agendamento editorial **não estão implementados neste pacote**.
- MinIO está compartilhado fisicamente, mas isolado por bucket e chave própria.
- Redis usa prefixo `lofi:` e senha existente. Para isolamento forte de Redis, provisionar ACL persistente, o que requer mudança testada na configuração existente.
- A confirmação humana de direitos é registrada no catálogo; **não comprova exclusividade legal** ou aprovação garantida pelo YouTube.
- Se o modelo Lyria gratuito ficar indisponível, a geração para, sem cobrar automaticamente.
