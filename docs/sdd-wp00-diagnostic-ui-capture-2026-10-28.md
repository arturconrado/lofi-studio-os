# WP-00 — Captura autenticada da tela Diagnóstico (28/10/2026)

## Escopo e método

- Tela observada: `/studio/diagnostico` no Lo-Fi Studio, com a sessão autenticada já aberta.
- Canal selecionado: **Lo-Fi Vibe Coding**.
- Captura observada em 28/10/2026, aproximadamente às 22:55 UTC.
- Leitura visual da interface. Nenhum formulário foi salvo, pedido retomado/cancelado, publicação iniciada ou configuração alterada.

## O que a tela mostrou

| Área | Valor observado | Interpretação limitada |
|---|---|---|
| Serviços | `database`, `redis`, `minio` e `worker` como `online`; `radio` com orientação para consultar Mini OBS; `video` como `not_implemented`; OpenRouter como `configured` | É o estado que a tela exibe; não substitui verificação independente de saúde, integração de rádio/vídeo ou revisão de configuração. |
| Orçamento | US$ 44,54 reservados de um limite acumulado de US$ 60,00 | Valor exibido para o canal selecionado, no momento da leitura. Não foi possível decompor reservas ou validar reconciliação apenas por esta tela. |
| Pedidos de música | A lista visível contém o pedido `Snowy Night Studio | 1 Hour of 8-Bit Lo-Fi for Coding · 010` em `UNCERTAIN`, com reserva de US$ 0,08 e custo exibido de US$ 0,00. Os demais pedidos visíveis nessa sequência estavam `COMPLETED`. | A tela mostra uma incerteza de pedido de música, registrada como 16 de outubro. Ela deve ser reconciliada sem repetir uma chamada paga. O custo zero exibido não prova custo terminal zero. |
| Auditoria | Eventos recentes de revisão/edição e reservas da oficina visual; também há registros de limpeza de mídia de publicações antigas | A lista confirma que esses tipos de evento aparecem no painel, mas não é uma verificação de integridade de cada mídia nem de conclusão de todos os fluxos. |

## Relação com os achados anteriores

A captura técnica anterior registrou **três tarefas `factory_tasks` em `UNCERTAIN`**, com reserva agregada de US$ 0,05. A linha vista nesta tela pertence à lista de **pedidos de música** e tem chave `LOFI-F54401BB-010`, reserva de US$ 0,08 e data exibida de 16 de outubro. São unidades e superfícies distintas; não somar nem tratar uma captura como resolução da outra sem conciliação de banco por IDs e origem.

## O que esta evidência não fecha

- Não demonstra a matriz de permissões por endpoint/papel em runtime (**TEST-37**), nem isolamento ponta a ponta para banco, fila e armazenamento.
- Não explica nem reconcilia as três tarefas visuais antigas ou o pedido musical `UNCERTAIN`.
- Não prova qual versão de código/imagem está instalada, paridade entre serviços, nem recuperação isolada de backup/rollback (**TEST-27**).
- Não prova publicação, processamento de vídeo ou operação do rádio; a tela sinaliza que o fluxo de vídeo ainda não está implementado e pede uma consulta ao Mini OBS.

## Próximos passos WP-00

1. Consultar a origem e o estado terminal do pedido musical incerto, sem reenviá-lo.
2. Fechar a atribuição dos escritores históricos/externos das tabelas sem DDL identificado.
3. Completar a matriz autenticada de rotas com papéis de teste autorizados, incluindo caminhos pagos e callbacks.
4. Validar revisão instalada e restauração/rollback em ambiente isolado, preservando os originais.

Esta captura acrescenta evidência de interface ao inventário. **WP-00 permanece parcial** até que seus gates sejam demonstrados; dados da interface, CI verde e inventário estático não equivalem a homologação.
