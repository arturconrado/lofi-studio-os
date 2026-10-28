# WP-00 — captura pública do endpoint de saúde (2026-10-28)

## Evidência observada

Consulta somente de leitura à documentação servida pelo Studio em `/docs`, em 28/10/2026 às 22:09 UTC. A página informou `Lo-Fi Vibe Coding Cloud 1.5.0` e OpenAPI 3.1.

A operação `GET /health`, executada pela própria interface Swagger, respondeu HTTP 200 com `{"status":"ok"}`. Nenhuma credencial foi usada na chamada, e nenhum dado ou estado da aplicação foi alterado.

## Limites

Esta resposta confirma que o endpoint de saúde respondeu pela origem pública naquele momento; não comprova saúde de todos os serviços, prontidão funcional, identidade de revisão, nem autorização das demais rotas. A navegação direta para `/openapi.json` foi bloqueada pelo navegador, e esta captura não extraiu o catálogo completo de operações. A contagem estática de rotas da `main` não deve ser apresentada como contagem validada no runtime.

A matriz autenticada de papéis/rotas, a reconciliação de revisão instalada por serviço, a paridade dos handlers, a restauração isolada e a reversão do TEST-27 permanecem pendentes. Esta captura não fecha WP-00 ou TEST-27, nem autoriza deploy, snapshot, publicação ou remoção do portal antigo.
