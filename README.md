# Lo-Fi Vibe Coding — Cloud Studio v1

MVP enxuto de catálogo e geração remota OpenRouter, usando **os serviços já contratados** na VPS SuperCorteLikes.

- FastAPI + portal responsivo: dashboard, biblioteca de 10 prompts, fila de geração, player e aprovação de direitos.
- PostgreSQL existente com banco e papel próprios (`lofi_studio` / `lofi_app`).
- Redis existente com chaves prefixadas `lofi:`.
- MinIO existente com bucket `lofi-vibe-coding` e credenciais de acesso restritas.
- Docker Compose com projeto independente e limites de CPU/RAM; acesso administrativo só por SSH.
- Endpoint de geração Lyria em OpenRouter. Apenas modelo gratuito por padrão; sem fallback pago.
- Gate humano obrigatório antes de faixas virarem `APPROVED`.

**Não incluído nesta versão:** streaming público, pipeline de vídeos ou alterações do Caddy e da observabilidade. Essas fases começam depois de confirmar a saúde do servidor e um primeiro áudio válido.

**Leia primeiro:** [docs/RUNBOOK.md](docs/RUNBOOK.md)

## Implantação assistida em modo coexistência

Consulte [`docs/EXECUCAO-UNICA.md`](docs/EXECUCAO-UNICA.md).

Executor: `bash scripts/go-live.sh {inspect|reduce|deploy|smoke|rollback}`.

**Aviso:** o executor não foi executado na VPS do usuário, não publica portas adicionais e não ativa a rádio 24/7; esta versão só entrega o portal/catalogação/worker de geração por API.
