# Captura do music-worker ativo — 2026-10-27

Registro de recuperação dos arquivos da aplicação encontrados no container ativo `lofi-vibe-coding-music-worker-1`. A captura foi feita por leitura do container e não alterou a VPS.

- Imagem: `lofi-studio-os:production-d877875`
- Label de revisão da imagem: `development`
- Arquivos incluídos: `studio/`, `web/` e `requirements.txt` (57 arquivos)
- Verificação: SHA-256 de cada arquivo comparado com o conteúdo ainda presente no container; 57 correspondências, sem ausências, extras ou divergências.
- Comparação com `origin/main` (`4ecfca1ee2c37a1b2c298fbc3e84b0faa3a5e165`) e com o snapshot de rádio de 2026-10-24: 26 arquivos correspondem a ambos; 4 correspondem apenas ao snapshot de rádio; 27 não correspondem a nenhum dos dois.

A lista de hashes relativa a esta pasta está em `manifest.sha256`. A captura inclui os arquivos exatos observados, inclusive `web/login-art.png`; não foi feita seleção nem remoção por tipo de arquivo.

Esta pasta é um arquivo histórico de recuperação e evidência. Ela não substitui o código canônico, não deve ser implantada diretamente e não prova por si só que o serviço pode ser reconstruído ou executado. Não inclui `.env`, segredos, banco de dados, volumes, estado de runtime, mídias fora de `/app` ou configuração externa. Um padrão local para chaves privadas e atribuições de credenciais não encontrou correspondências; isso não é uma auditoria completa de segredos.
