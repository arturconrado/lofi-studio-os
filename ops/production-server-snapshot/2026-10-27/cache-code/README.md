# Captura dos arquivos de código em `/cache` — 2026-10-27

Captura somente de arquivos com extensão `.py`, `.js`, `.html` e `.css` no bind mount `/srv/lofi-vibe-coding/cache` observado nos serviços `radio` e `channel-radio`. A captura é arquivística; ela não altera nem remove arquivos da VPS.

- 383 arquivos copiados e conferidos por SHA-256 contra o mount no servidor: 363 Python, 8 JavaScript, 6 HTML e 6 CSS; 383/383 correspondem, sem ausências, extras ou divergências.
- Comparação por conteúdo com arquivos versionados em `main` e nos branches de recuperação dos PRs #67/#68: 55 caminhos não têm conteúdo idêntico nessas referências; isso inclui 47 conteúdos Python distintos. Os caminhos estão em diretórios de validação, testes e operações históricas. Hash diferente não prova que um script esteja ativo nem que deva ser promovido a código canônico.
- Uma varredura local de padrões conhecidos para chaves e tokens comuns não encontrou correspondências. Não é uma auditoria completa de segredos.

`manifest.sha256` registra os hashes dos arquivos copiados. A captura não contém arquivos JSON, outros dados de projeto, MP4/MP3, imagens, fontes, logs, `.env`, segredos, banco, volumes adicionais ou conteúdo fora do cache. O mount observado tinha aproximadamente 16 GiB e 1.361 arquivos no total; o cache inteiro permanece na VPS sem alteração. Esta cópia parcial de código não é um backup do cache, não é código canônico e não deve ser implantada ou executada diretamente.

O repositório contém uma auditoria anterior de 15 pares cache/S3 de três episódios aprovados, conferidos em 2026-10-15. Essa evidência vale para aquela amostra e data; não demonstra backup ou integridade atual de todos os itens do cache.
