# SDD WP-01 — revisão versionada de roteiros e montagem

Esta entrega implementa uma primeira parte do WP-01. Ela não declara o pacote completo nem altera o SDD original.

## Lacuna observada

`creator_plans` mantinha um único `data` mutável. Salvar uma edição de storyboard substituía o conteúdo anterior sem uma revisão consultável e sem detectar que outra janela havia salvado uma alteração mais recente.

## Mudança nesta entrega

- `creator_plans.revision` identifica a revisão atual.
- `creator_plan_revisions` guarda snapshots da proposta e das decisões de montagem com SHA-256 do JSON canônico.
- Ao inicializar, os registros legados com conteúdo recebem um snapshot da versão atual. Isso não inventa histórico anterior nem aprova conteúdo antigo.
- Salvar uma edição existente requer `draft_revision`. Alterar identidade, trilha, áreas da cena ou máscaras também exige a revisão exibida e cria uma nova revisão quando o conteúdo muda. Uma revisão vencida retorna conflito para a interface recarregar.
- A tela de montagem lê a revisão junto com o estado do roteiro e envia esse número ao salvar essas decisões. Uploads e aprovações de arquivos continuam vinculados ao hash dos próprios artefatos e não criam revisão da proposta.
- Endpoints de leitura listam revisões e recuperam um snapshot. A conexão e o schema do workspace continuam sendo os limites de acesso.
- As rotas de storyboard retornam a revisão; a lista de roteiros salvos também a inclui.

## Critérios cobertos

- **G1-05 / G1-06:** versões anteriores consultáveis e gravação protegida contra sobrescrita concorrente.
- **G3-03:** edição do storyboard cria uma revisão explícita da proposta.
- **G4-01:** o snapshot tem identificador de revisão e hash de conteúdo.
- **G4-11:** os snapshots residem no mesmo schema de workspace das entidades atuais.

## Limites e aceite pendente

Esta fatia não completa WP-01. Aprovações vinculadas a hashes, proveniência completa de referências, migração de todos os vínculos de artefatos e revisão ponta a ponta de permissões permanecem para auditoria/implementação própria. Alterações operacionais em mídias e estados de execução não criam uma revisão de proposta. Testes de banco precisam executar contra PostgreSQL descartável; testes aprovados não substituem inspeção visual, homologação ou produção.

Verificações automatizadas previstas: revisão inicial e nova, recuperação do snapshot anterior, SHA-256 estável, gravação sem número de revisão rejeitada e escrita concorrente obsoleta rejeitada. Nenhum provedor pago, arquivo de mídia, YouTube, `main` ou VPS é alterado por esta entrega.
