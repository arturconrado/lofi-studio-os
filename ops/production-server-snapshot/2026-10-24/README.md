# Snapshot do código em produção — 2026-10-24

Captura somente de arquivos de código e artefatos web dentro de `/app` nos containers ativos. Não inclui banco de dados, volumes, `.env`, tokens ou configurações secretas. Esta pasta é um registro de recuperação e auditoria; os arquivos canônicos na raiz continuam baseados na `main`.

## Commit de referência

`main` no momento da captura: `30d41110fbf806e973815f04034582e92ede9e1f`.

## Imagens observadas por leitura SSH

- `studio` e `export-worker`: imagem `lofi-studio-os:halloween-bounded-encoder-20261024`, ID `sha256:b9d537c7702c9dbb66b35e7444bfe8763b518f745fd96c807c28cc46faac434b`, label de revisão `1789d4d4cf77917436aaf68a6636c8143fd91738`.
- `creator`: imagem `lofi-studio-os:production-30d4111`, ID `sha256:049b64cecbc696871efa73e57a392d551e37c9346b4f06aae1949e8acf24912d`, label de revisão `1789d4d4cf77917436aaf68a6636c8143fd91738`.
- `radio`: imagem `lofi-studio-os:production-2f454da`, ID `sha256:699130ac9e0274ae8c8e6f30e38081a05ce98235e1748c0ea2f119464f6c6b84`, label de revisão `1789d4d4cf77917436aaf68a6636c8143fd91738`.

Cada diretório de serviço contém `studio/`, `web/` e `requirements.txt` como lidos no container. `studio-export-worker` representa ambos porque usavam o mesmo ID de imagem na captura. `manifest.sha256.json` contém SHA-256 de cada arquivo capturado.
