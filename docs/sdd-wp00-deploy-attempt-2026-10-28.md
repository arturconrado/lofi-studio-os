# WP-00 — resultado do deploy após o PR #63 (28/10/2026)

## Evidência observada

- O PR #63 foi integrado à `main` no commit `b1a9bff1ad4738526ac976acb6c6649d68fab266`.
- O workflow `Checks` desse commit concluiu com sucesso (run `40774014126`).
- O PR #73 foi integrado ao commit `f499ac9a33d9c741a76c0c58c876151e6fb72ad2`; o run `Checks` da `main` para esse commit ainda estava em execução às 21:45 UTC.
- O deploy iniciado para o commit `f499ac9a33d9c741a76c0c58c876151e6fb72ad2` falhou no passo `Verify installed deployer protocol` (run `40774487361`). A chamada SSH terminou com código 2.

## Interpretação e limite

O passo de verificação ocorre antes da criação e do envio do arquivo de release. O run falhou nesse passo e não chegou ao comando de deploy. Portanto, esse run não enviou um pacote de aplicação à VPS e não comprova uma implantação do conteúdo da `main`.

O resultado é compatível com a evidência anterior do WP-00: o comando fixo instalado na VPS ainda não anuncia `LOFI_DEPLOY_PROTOCOL=2`. O PR #63 alterou o workflow/script no GitHub, mas o run de deploy não conseguiu executar o script novo no host. Não houve alteração manual na VPS durante esta verificação.

## Próximo gate

Antes de tratar a `main` como implantada, é preciso estabelecer, dentro da política de mudança exclusivamente via GitHub, um bootstrap compatível com o comando SSH atualmente instalado. Depois, validar a atualização de forma isolada e comprovar rollback conforme TEST-27. Até esses gates passarem, os merges seguintes podem atualizar o repositório, mas não devem ser apresentados como implantados em produção.
