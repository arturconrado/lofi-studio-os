# WP-00 — captura de paridade entre os portais (2026-10-28)

## Escopo e método

Leitura autenticada da interface em 28/10/2026, no canal selecionado, comparando as páginas visíveis de `/legacy` com as páginas equivalentes de `/studio`. A navegação foi somente leitura: não foram salvas configurações, aprovados materiais, iniciadas transmissões, alterados vídeos nem acionadas publicações. Nenhuma credencial, identificador interno, URL de mídia, texto secreto ou valor financeiro é registrado aqui.

Esta captura registra a interface observada nesta sessão, não prova a autorização de endpoints, a disponibilidade de todos os dados ou a paridade de cada função. Estados que não carregaram ficam como não observados, nunca como zero ou concluídos.

## Resultado por jornada

| Jornada | Portal antigo observado | Portal novo observado | Situação para WP-00 |
|---|---|---|---|
| Visão geral | Painel com prévia do programa, estado da live e atalhos de operação | Estúdio separado de Produzir, Biblioteca, Ao vivo, Revisão e Análises | A nova navegação separa as áreas; falta provar as transições de estado equivalentes e a recuperação de cada ação. |
| Criar | Presets de duração, assistente de ideia, etapas de ideia/cena/música/orçamento/produção, roteiros salvos e acesso à revisão | Construtor explícito de vídeo longo com cena/personagens, base, inserções, agenda, música, prévia e montagem; a interface distingue aprovação de vídeo longo de Shorts | Não é paridade visual/funcional demonstrada: o fluxo guiado antigo e os presets precisam de destino e aceite identificados na experiência nova. |
| Biblioteca | Filtros por programas, música, vídeos, visuais e MP4; busca, envio de imagem, ouvir/assistir, editar textos, exportar e ações de publicação | Produções com filtros por estado, tabela de publicações do YouTube e seção de programas anteriores | Lacuna candidata: não foi encontrada uma navegação equivalente aos filtros/ações do acervo de mídia antiga. Confirmar os contratos e dados antes de migrar ou remover qualquer funcionalidade. |
| Lives | A rota abriu o painel legado de operação, mas a leitura acessível informou estado de monitor desconhecido/indisponível | Prévia e programa, cenas/fontes, mixer, loop, controles e estado do transmissor | A nova interface expõe controles mais completos. Falta comparar cada operação e validar estados do monitor sem iniciar transmissão. |
| Canais | Identidade, adição de canal, troca/renovação/desconexão da conta YouTube, configurações, conexão de transmissão e atalho para biblioteca do canal | Receitas por canal, conexão YouTube e conexão de transmissão | O núcleo de conexão/receitas existe. A troca de conta e o atalho da biblioteca do canal não apareceram na ficha observada; verificar se foram substituídos por jornadas novas ou continuam ausentes. |
| Análises/Growth | A rota abriu, porém não apresentou métricas utilizáveis na leitura desta sessão | Captura de evidências do YouTube Studio, sinais do canal, métricas por vídeo, experimentos, referências, prioridades e dados de monetização | A nova tela oferece estrutura para Growth, mas não havia captura inicial. A tela antiga não pôde ser comparada funcionalmente; manter ambas até validar importação, edição, histórico e proveniência. |
| Configurações | Modelo, credencial, limites diário/acumulado, autorização explícita, consumo e atalhos de operação | Chave e um limite global de gasto para os motores de IA, com reserva/compromisso indicados | A simplificação do limite está presente na nova tela. Ainda falta comparar configurações não financeiras, histórico e ações avançadas e verificar que todos os motores usam a mesma fonte. |

## Lacunas e próximos passos

- **G1-01/G1-02, G3-03/G3-08:** percorrer com dados de teste a navegação, aprovação, retomada após reload e recuperação da mesma operação; a captura de tela não comprova os efeitos de backend nem idempotência.
- **G1-07/G1-12, G5-07:** inventariar por hash e vínculo os programas, músicas, visuais, exports e Shorts que o portal antigo apresenta; demonstrar como cada item e aprovação chegam à experiência nova. Não excluir mídia ou elementos durante esta auditoria.
- **G1-11/G4-03/G4-04:** provar por handlers e testes que cotação, reserva, consumo e reconciliação usam uma única fonte em todos os motores; uma tela com um limite global não prova o contrato financeiro completo.
- **G3-01…G3-09:** mapear cada etapa do assistente antigo para uma ação/contexto equivalente no canal e na proposta novos, preservando decisões e permissões humanas.
- **G4-02/G4-08/G4-11:** executar a matriz de papéis, canal/workspace, publicação e isolamento nos endpoints da revisão instalada; o login e a tela visível não são prova de autorização.
- **G4-09/TEST-27:** permanecer sem alteração de produção até demonstrar backup restaurável, teste isolado e reversão segura.
- Repetir Análises e monitoramento de Lives em contexto autenticado com estados carregados e registrar falhas como evidência separada; esta captura não permite inferir que esses recursos estejam ausentes.

## Conclusão

**A paridade não está comprovada e o portal antigo não está liberado para remoção.** A Biblioteca antiga expõe categorias e ações de mídia não observadas na Biblioteca nova; Criar, Canais e Growth também apresentam diferenças de jornada. São lacunas para descoberta e decisão de migração, não autorização para apagar ou substituir dados. WP-00 permanece aberto, assim como TEST-27 e a matriz dinâmica de permissões.
