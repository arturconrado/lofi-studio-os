# Operação e implantação — versão em desenvolvimento

## Bloqueio de lançamento

Esta branch é uma fundação testada localmente, não um lançamento completo. Não ativar signup, streaming contínuo nem implantação de produção enquanto os critérios abertos em AUDIT-STUDIO-OS.md não forem resolvidos.

## Configuração segura

O arquivo `.env.example` contém somente nomes e placeholders. Credenciais devem entrar em arquivo `.env` excluído do Git, com permissões restritas, ou no secret manager da infraestrutura. Nunca envie senhas, chaves privadas ou refresh tokens no chat.

O SMTP existente do usuário pode usar TLS direto na porta 465 ou STARTTLS na porta 587. Configurar host, porta, usuário, senha, remetente, STUDIO_MASTER_KEY e STUDIO_PUBLIC_ORIGIN. Manter STUDIO_SIGNUP_ENABLED=0 até que o email worker esteja funcionando e um e-mail real seja recebido. Envios de resultado incerto não são repetidos automaticamente.

OAuth requer aplicativo Google configurado e redirect URI `<STUDIO_PUBLIC_ORIGIN>/api/youtube/oauth/callback`. Consentimento deve ocorrer pela conta autorizada do usuário. Nenhuma publicação é feita ao conectar. Não registrar query strings OAuth nos access logs.

## Serviços

- API: `uvicorn studio.api:app`, sem access log com query strings.
- Email: `python -m studio.email_worker`, com SMTP configurado.
- Exportação: `python -m studio.exports`, cache próprio com espaço disponível.
- Workers existentes: manter contratos atuais. Novos workers de workspace recebem `LOFI_WORKSPACE_ID=<uuid>` e cache separado. A API global não deve receber esse identificador.
- Streaming: o modo contínuo usa `LOFI_CONTINUOUS_ENABLED=1` somente depois de benchmark e testes autorizados. Default 0 mantém o mecanismo antigo.

O Dockerfile usa Python 3.12 e instala FFmpeg, fontes e dependências explícitas. O build Docker ainda precisa ser validado em um daemon isolado; não há Docker ativo no Mac desta sessão. A workflow de testes é manual para evitar execução/billing automática não autorizada.

## Antes da implantação

1. Reconferir lives/processos ativos, disco e capacidade; não inferir disponibilidade a partir da auditoria anterior.
2. Fazer novo dump consistente do banco Lo-Fi e preservar mídias, manifestos, configuração e imagens/versão atuais.
3. Restaurar o backup em staging e validar leitura de mídia.
4. Construir imagem e testar a API, workers e fluxos completos em rede e persistência isoladas do ClipBR.
5. Registrar digest da imagem antiga, commit novo e plano de alteração restrito aos serviços aprovados.
6. Obter aprovação explícita para reinícios/alterações de produção com risco operacional. Não executar compose down, prune, migrações destrutivas ou alterações de outros projetos.

## Rollback

As tabelas novas são aditivas. Em caso de falha, reimplantar a imagem antiga da API para manter acesso ao catálogo legado; schemas/workspaces novos permanecem preservados, mas a versão antiga não os serve. Isso não é um rollback funcional do SaaS novo. Não apagar schemas nem restaurar um dump sobre escrita recente sem avaliação e autorização. Nunca reiniciar containers de streaming apenas para rollback da interface/API.

Os digests iniciais de radio/channel-radio eram `sha256:1352b4a1faa9e9bf7f9f2d83fbff21a58b7c367d85085a4cfe42a6f1414303ee`; creator `sha256:a5c4976cc3190c30c51a17c5c9823ca6e51acc4b8a37f5d8502ce967a7596eea`. O digest da API deve ser capturado imediatamente antes de qualquer implantação futura.
