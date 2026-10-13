# Lo-Fi Studio OS — auditoria e implementação em desenvolvimento

Data: 13 de outubro de 2026. Esta entrega **não é uma declaração de prontidão para lançamento**.

## Infraestrutura observada

- DigitalOcean, droplet 581671384, Ubuntu 24.04, 4 vCPU, 8 GB RAM, disco 160 GB.
- IP 162.243.114.141, projeto `/opt/lofi-vibe-coding-cloud-v1`, sem diretório Git no início.
- Disco no início: 126 GB utilizados, 29 GB livres (82%). Memória disponível: aproximadamente 5 GB.
- Cinco containers Lo-Fi ativos; API saudável. Outros containers pertencem ao ClipBR e permaneceram intactos.
- Live principal estava `stopped`, e a inspeção de processos encontrou zero processos FFmpeg naquele momento.
- Cache persistente dos transmissores: `/srv/lofi-vibe-coding/cache` → `/cache`. Restart policy `unless-stopped`.
- Banco Lo-Fi dedicado por nome (`lofi_studio`), hospedado no serviço PostgreSQL compartilhado. Redis e MinIO também são serviços compartilhados.
- DigitalOcean não registrava backups nem snapshots. Um dump consistente do banco Lo-Fi foi criado e restaurado em PostgreSQL local; 313 faixas recuperadas. **Não é um backup completo de todos os objetos MinIO e serviços da VPS**.
- Cloudflare: `lofistudiox.com` ativo como zona, sem registros A/AAAA/CNAME na consulta. Nenhum DNS foi alterado.
- SMTP e credenciais OAuth do YouTube não estavam configurados no ambiente da API. Usuário escolheu utilizar seu provedor SMTP existente.

## Matriz AS-IS e mudanças

| Funcionalidade | Estado real inicial | Evidência | Problema | Solução nesta branch / pendência | Prioridade |
|---|---|---|---|---|---|
| Saúde da API | Funcional | `/health` OK; PostgreSQL, Redis, MinIO e worker online | Sem observabilidade suficiente da recepção externa | Preservado; métricas externas ainda pendentes | P0 |
| Login administrativo | Funcional | Middleware Basic; credenciais via ambiente | Identidade compartilhada, sem sessão SaaS | Login separado do administrador, sessão segura e preservação do Basic | P0 |
| Multiusuário | Ausente | Não havia tabelas de usuários/workspaces | Sem isolamento | Cadastro, verificação, recuperação, sessões, perfis, membros e troca de workspace implementados e testados localmente | P0 |
| E-mail transacional | Ausente | Nenhuma configuração SMTP | Confirmação e recuperação não poderiam ser entregues | Outbox criptografado e worker SMTP TLS; envio real pendente | P0 |
| Persistência de tenants | Ausente | Catálogo global no schema público | Vazamento entre usuários | Schemas separados, prefixos S3/Redis e cache por workspace; testes de isolamento de faixas | P0 |
| Música | Parcial | 250 faixas REVIEW, 63 DRAFT; código de geração e QC | Novas gerações e direitos não validados nesta sessão | QC existente testado; nenhuma geração paga executada | P1 |
| Programas | Funcional parcialmente | Programas de 4h e 8h com áudio/visual separados | Arquivo visual não equivale a MP4 final longo | Exportador de MP4 e jobs separados; 1h/4h reais produzidos localmente com programa previamente revisado | P0 |
| Streaming atual | Parcial | `program_radio.py` usa FFmpeg por programa | Trocar program_id encerra execução atual; não há fila contínua antiga | Motor opt-in de encoder persistente com decoders independentes; testes locais acelerados | P0 |
| Fila futura | Ausente | Controle antigo fixa um program_id | Sem versionamento e atualizações seguras | Fila PostgreSQL versionada e bloco atual preservado, com testes de concorrência lógica | P0 |
| Renovação | Ausente | Sem inclusão de programas aprovados na fila | Biblioteca não renovava programação | Aprovação de programa completo pode inserir automaticamente no canal opt-in; pipeline completo faixa→segmento ainda pendente | P0 |
| Dois streams | Não verificável em produção | Um canal existente, nenhuma live ativa | Capacidade real de encoders não medida | Dois encoders locais simultâneos testados; benchmark da VPS e dois destinos externos pendentes | P0 |
| YouTube OAuth | Ausente | Sem client ID/secret | Conexão dependia de chave RTMPS manual | OAuth com state de uso único, PKCE e tokens criptografados; testado com mock; autorização real pendente | P1 |
| Publicação/agendamento YouTube | Ausente | Episódios registravam URLs manualmente | Não havia upload via API | Continua indisponível de forma explícita; não implementado nesta entrega | P1 |
| Interface | Parcial | HTML/JS existente com navegação extensa | Operação dispersa | Login novo, cinco áreas principais, fila e exportação com estados reais; QA visual desktop local | P1 |
| Orçamento | Parcial | Reserva musical existente; planner não checava enabled/daily | Possibilidade de pedidos pagos fora da política | Confirmação explícita para planos, guardas diário/acumulado e isolamento de chave do workspace | P0 |
| Dependências | Defeituosa | Auditoria inicial encontrou vulnerabilidades conhecidas | Bibliotecas antigas | Atualização e nova auditoria registradas junto às evidências | P0 |
| Sistema agêntico | Parcial | Workers e autopilot existentes | Não há camada completa de governança | Operações críticas continuam determinísticas; camada agêntica integral pendente | P2 |

## Arquitetura implementada

A fábrica existente foi preservada. A API FastAPI recebe autenticação e novos routers. O administrador continua associado ao catálogo legado no schema público. Usuários comuns trabalham em schemas `ws_<uuid>`, sem fallback ao schema público. Sessões globais validam a membership a cada requisição. A camada S3 acrescenta prefixo por workspace; Redis e cache também recebem namespace.

O motor contínuo mantém um único FFmpeg encoder com entradas raw de vídeo e PCM. Cada bloco usa um decoder separado; os timestamps são gerados pelo encoder da sessão, evitando reiniciar a conexão na troca normal. Fila e estado são persistidos no PostgreSQL. Essa estratégia exige benchmark de CPU/memória antes de ativação: o pipeline anterior copiava vídeo comprimido, enquanto o novo encoder recompõe o vídeo.

**Limites atuais:** prefetch e watchdog/recovery de sessões longas ainda precisam evoluir; a fila pode esperar download no limite de um bloco. Falha de decoder encerra a execução de forma controlada; a recuperação completa 24/7 não foi comprovada. O modo contínuo permanece desabilitado por padrão. Um programa reserva aprovado pode repetir quando a fila está vazia; isso não constitui curadoria completa de repetição editorial.

A renovação implementada é de **programas completos revisados**. Não equivale ao pipeline automático completo de músicas/clipes recém-gerados até segmentos aprovados.

## Estados de validação

- Implementado e testado localmente: sessão, CSRF, confirmação/reset por tokens, isolamento de faixas, RBAC básico, sessão administrativa separada, fila versionada, renovação de programa revisado, encoder persistente, dois encoders locais, guardas financeiros e OAuth com mock.
- MP4 1h/4h: renderização e decodificação completa executadas localmente com áudio e visual do programa revisado `WARM4H-20261012`, sem novos gastos.
- Staging remoto: não implantado.
- Produção: somente auditoria e leituras; mudanças desta branch não implantadas.
- Não validado: envio SMTP real, consentimento OAuth real, upload/agendamento, recepção YouTube, failover prolongado, operação 24/7, performance da VPS com dois novos encoders, suíte E2E integral e conformidade WCAG AA.

## Critérios de lançamento que continuam abertos

1. Configurar SMTP e executar confirmação/reset reais de ponta a ponta.
2. Configurar aplicativo Google OAuth, consentimento e canal autorizado; implementar upload/agendamento de publicação.
3. Provisionar workers isolados para cada workspace, sem credenciais globais herdadas.
4. Validar storage/Redis/worker multiusuário em staging e isolamento em todos os routers.
5. Implementar prefetch, recuperação, watchdog e métricas de sinal; validar continuidade por duração real.
6. Completar renovação faixa/clipe→segmento→fila, rights/QC e curadoria.
7. Medir capacidade da VPS, validar dois destinos autorizados sem impacto no ClipBR.
8. Completar sistema agêntico, kill switch, approvals e observabilidade.
9. Executar todas as jornadas E2E e revisão de acessibilidade.
10. Preparar backup completo de mídia e implantação com aprovação explícita para alterações de produção com risco de interrupção.

Referência utilizada para OAuth: [documentação oficial do Google](https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps).
