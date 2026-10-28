# G4-11 / TEST-37 — escopo explícito de workspace por requisição

## Lacuna reproduzida

`active_workspace()` usava `WORKSPACE.get() or LOFI_WORKSPACE_ID`. Como a API deixava o contexto em `None` para uma sessão `platform_admin` sem workspace e para Basic admin, o valor destinado a workers podia selecionar implicitamente um tenant durante uma requisição HTTP.

Em PostgreSQL descartável, criei um registro privado em um workspace, configurei `LOFI_WORKSPACE_ID` para esse workspace e consultei a API com sessão `platform_admin`. Antes da correção, a resposta continha o registro privado. O mesmo cenário também cobria Basic admin.

## Correção proposta

- O contexto `WORKSPACE` distingue “não vinculado” do escopo público explícito.
- Processos de worker sem contexto continuam usando `LOFI_WORKSPACE_ID` como padrão.
- O middleware da API define o workspace a partir da sessão autenticada ou define escopo público explícito para rotas públicas, `platform_admin` sem workspace e Basic admin.
- Callbacks e rotinas que selecionam um schema explicitamente continuam podendo vincular o workspace correto.

## Evidência automatizada

- Regressão integrada: sessão de workspace vê o próprio registro; `platform_admin` e Basic admin não herdam um workspace apenas por variável de processo.
- Regressões unitárias: worker sem contexto herda o valor padrão; contexto público explícito não herda; a API não recebe fila nem cliente de armazenamento com prefixo de tenant, enquanto o contexto de worker continua recebendo ambos isolados.
- Suíte `tests/` em PostgreSQL descartável: 282 testes aprovados, 3 avisos de depreciação.

## Limites

Isso comprova o contrato local entre middleware e resolução de schema. Não demonstra a configuração do ambiente implantado, nem substitui matriz completa de autorização por endpoint, verificação de armazenamento/filas ou homologação de cada papel. TEST-37 e WP-00 permanecem parciais até a revisão integral e a confirmação do runtime.
