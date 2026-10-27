# Captura do youtube-publisher ativo — 2026-10-27

Registro de recuperação dos arquivos de aplicação encontrados no container ativo `lofi-vibe-coding-youtube-publisher-1`. A captura foi feita por leitura do container e não alterou a VPS.

- Imagem: `lofi-studio-os:production-ed85886`
- Label de revisão da imagem: `1789d4d4cf77917436aaf68a6636c8143fd91738`
- Arquivos incluídos: `studio/`, `web/` e `requirements.txt` (128 arquivos)
- Verificação: SHA-256 de cada arquivo comparado com o conteúdo ainda presente no container; 128 correspondências, sem ausências, extras ou divergências.
- Comparação com `origin/main` (`4ecfca1ee2c37a1b2c298fbc3e84b0faa3a5e165`) e com o snapshot `studio-export-worker` de 2026-10-24: 82 arquivos correspondem a ambos, 5 correspondem somente à `main`, 11 somente ao snapshot arquivado e 11 não correspondem a nenhum dos dois.

O snapshot `studio-export-worker` é uma captura histórica de outro serviço/imagem compartilhada e não representa uma captura anterior direta do `youtube-publisher`. Os arquivos que não correspondem a essas referências estão preservados para análise; isso não determina se suas mudanças são necessárias ou se podem ser reconstruídas.

A lista de hashes relativa a esta pasta está em `manifest.sha256`. A captura inclui os arquivos exatos observados em `/app`. Esta pasta é evidência de recuperação, não código canônico nem artefato de deploy. Não inclui `.env`, segredos, banco, volumes, estado de runtime, mídias fora de `/app` ou configuração externa. Um padrão local para chaves privadas e atribuições de credenciais não encontrou correspondências; isso não é uma auditoria completa de segredos.
