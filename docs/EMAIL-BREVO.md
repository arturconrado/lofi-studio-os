# Preparação anterior: Brevo

**Substituída pela integração Resend.** Consulte `EMAIL-RESEND.md`. O conteúdo abaixo registra a opção anterior; não configura dois provedores simultaneamente.

Provedor selecionado: Brevo Free. Domínio: `lofistudiox.com`. Remetente proposto: `Lo-Fi Studio OS <nao-responda@lofistudiox.com>`.

O plano Free inclui até 300 envios por dia, incluindo e-mails transacionais. Permanecer no plano gratuito; não ativar upgrade, créditos pagos ou cobrança automática. A configuração na branch é preparatória: não há conta vinculada nem envio real validado.

## Ativação

1. Criar ou entrar na conta Brevo e manter o plano Free. O titular deve concluir cadastro, termos e verificação da conta.
2. Adicionar `lofistudiox.com` em domínios/remetentes e obter os registros de verificação, DKIM e DMARC apresentados pelo Brevo.
3. Publicar somente os valores fornecidos pela conta, após verificar os registros DNS existentes. Não inventar chaves DKIM, duplicar políticas DMARC ou sobrescrever registros de outros serviços. Receber e enviar e-mail são configurações distintas; esta integração fornece envio transacional, não uma caixa de entrada.
4. Adicionar o remetente `nao-responda@lofistudiox.com` e validar o domínio/remetente no provedor.
5. Obter o SMTP login e gerar uma chave SMTP. Configurar as credenciais no `.env` excluído do Git ou no secret manager; não enviar chaves pelo chat.
6. Usar `smtp-relay.brevo.com`, porta 587 com STARTTLS, ou 465 com TLS direto. A aplicação implementa ambas as opções.
7. Antes de iniciar o worker, autenticar o domínio, configurar as credenciais e verificar que os links de cadastro usam a URL HTTPS funcional da aplicação. Manter `STUDIO_SIGNUP_ENABLED=0` até validar entrega real e fluxo de confirmação/reset.
8. Fazer um teste privado para o endereço autorizado pelo usuário. Nenhum e-mail foi enviado automaticamente nesta preparação.

## Dependências pendentes

- Conta Brevo Free com envio transacional habilitado.
- Registros DNS específicos da conta e domínio autenticado.
- SMTP login/chave configurados com segurança.
- Aplicação acessível por HTTPS no domínio; a auditoria anterior não encontrou A/AAAA/CNAME nessa zona.
- Teste real de recebimento, confirmação e recuperação de senha.

Fontes oficiais: [plano Free](https://help.brevo.com/hc/en-us/articles/208589409-About-Brevo-s-pricing-plans), [SMTP](https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP), [chaves SMTP](https://help.brevo.com/hc/en-us/articles/7959631848850-Create-and-manage-your-SMTP-keys).
