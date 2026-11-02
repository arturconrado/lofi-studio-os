# Protocolo para agentes de desenvolvimento

Vale para Claude Code, Codex e qualquer outro agente que trabalhe neste repositório, em paralelo ou em sequência.

## Fonte de verdade

- Escopo e estado: `docs/harness-matrix-2026-11-02.md` (matriz existente/parcial/ausente e etapas). Atualize a linha da área quando entregar.
- Contratos do harness que todo trabalho respeita:
  - **Perfil de nicho** vive na receita (`RecipeData.profile`, `studio/niche_profiles.py`). Não crie outra fonte de verdade para nicho, idioma, elenco ou regras editoriais.
  - **Direção resolvida** (`studio/orchestration.resolved_direction`): qualquer agente do produto que faça chamada paga grava `direction_sha256` no payload da tarefa e aparece em `AGENTS`/`plan_steps`.
  - **Custo:** chamadas pagas só depois de `require_spend_permission`, confirmação de custo e `financial.check_available`. Testes nunca chamam provedores pagos.
  - **Sem vidIQ.** Dados externos entram só por API oficial autorizada ou captura humana com origem registrada.

## Antes de começar

1. Rode `git fetch origin`, `gh pr list --state open` e `git worktree list`.
2. Se outro PR aberto toca os mesmos arquivos (`gh pr view <n> --json files`), coordene pelo PR antes de editar.
3. Reivindique a tarefa abrindo cedo um **PR em rascunho** com o título `[<agente>] etapa <n>: <tema>` e uma checklist. O PR aberto é o quadro de tarefas, e não há arquivo de quadro no repositório.
4. Trabalhe em uma branch e em um worktree próprios: `git worktree add ../lofi-studio-os-<tema> -b <agente>/<tema> origin/main`.

## Regras

- Nunca faça commit direto na `main` nem force-push na branch de outro agente. Rebase sobre `origin/main` antes de pedir revisão.
- Faça a menor mudança completa. Preserve hashes, prompts e aprovações existentes: quando um texto enviado a provedor mudar, prove a igualdade do caminho legado com um teste byte a byte.
- Commits e PRs não levam `Co-Authored-By` nem assinatura de agente.
- Não implante, não publique mídia e não gaste créditos sem autorização explícita do proprietário na sessão.

## Validação obrigatória

```
python -m pytest -q tests test_qc.py          # com LOFI_TEST_DATABASE_URL apontando para um PostgreSQL descartável
cd frontend && npx tsc --noEmit && npx vitest run && npx vite build
git diff --exit-code -- web/app                # o bundle versionado precisa corresponder ao código
```

## Passagem de bastão (descrição do PR)

```
## Contexto
<pedido, etapa e área da matriz>
## Estado
- Implementado: …
- Validado localmente: <comandos e resultados>
- Implantado: não | <evidência>
## Contratos tocados
<perfil, direção, orçamento, aprovações, publicação>
## Pendências e impedimentos
<o que falta, o que depende do proprietário ou de serviço externo>
```

Quem retomar o trabalho lê o PR, a matriz e `git log origin/main..HEAD` antes de editar.

## Novo agente no produto

1. Registre o agente em `studio/orchestration.py` (`AGENTS`), com o módulo que executa e a classe de custo.
2. Calcule `resolved_direction` antes da chamada e grave `direction_sha256` no payload.
3. Inclua a etapa em `plan_steps`, com status derivado do estado real e não de suposições.
4. Escreva os testes: direção no payload, bloqueio sem pré-requisito e nenhuma chamada paga no teste.
