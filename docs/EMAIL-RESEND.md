# Resend no Lo-Fi Studio OS

A integração de produção usa o backend Python e a fila de e-mails existente. Defina as variáveis abaixo no `.env` excluído do Git ou no secret manager:

```dotenv
STUDIO_EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxxxxxx
STUDIO_EMAIL_FROM=Lo-Fi Studio OS <nao-responda@lofistudiox.com>
```

**Substitua `re_xxxxxxxxx` pela sua chave real do Resend. Não envie a chave pelo chat, não coloque no JavaScript do navegador e não faça commit dela.** O worker rejeita a chave de exemplo.

Autentique `lofistudiox.com` no Resend antes de usar o remetente do domínio. Mantenha o plano gratuito e não habilite upgrades ou cobrança por excedentes. A criação de conta/verificação de domínio e o envio real continuam pendentes. O plano e limites efetivos devem ser conferidos na conta.

O worker chama `POST https://api.resend.com/emails`, inclui chave de idempotência baseada no ID da fila e registra o identificador retornado. O estado `sent` significa aceito pelo provedor, não comprova recebimento na caixa de entrada. Resultado incerto permanece para revisão; não há retry automático nem envio simultâneo por SMTP. SMTP continua disponível se `STUDIO_EMAIL_PROVIDER=smtp` for selecionado explicitamente.

## Seu exemplo JavaScript

O código está em `examples/resend/send-test.mjs`, com o SDK fixado e tratamento de resultado. Ele usa `onboarding@resend.dev` e o destinatário solicitado `conraderp@gmail.com`. O domínio de teste do Resend limita destinatários conforme a conta; para usuários do aplicativo, use o domínio autenticado.

Após configurar a chave, **o comando abaixo envia um e-mail real**. Ele não foi executado com credenciais nesta implementação:

```sh
node --env-file=.env examples/resend/send-test.mjs
```

Instale as dependências do exemplo, se necessário, em `examples/resend` com `npm ci`. O exemplo é executado no servidor/terminal; não é incluído no frontend.

Para o serviço de confirmação/reset, iniciar `python -m studio.email_worker` com as variáveis de ambiente carregadas. Manter signup desabilitado até validar entrega e links HTTPS. A configuração do Resend substitui a preparação anterior de Brevo.

Fontes: [Node.js](https://resend.com/docs/send-with-nodejs), [API e idempotência](https://resend.com/docs/api-reference/emails/send-email).
