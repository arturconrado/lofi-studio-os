# SDD — resumo público da descoberta WP-00 (2026-10-27)

Este documento registra conclusões de alto nível da descoberta para orientar a execução do SDD. Ele não contém inventários operacionais detalhados, identificadores de recursos, caminhos privados, IDs de registros, nomes de imagens, objetos, filas ou dados de usuários. O relatório original foi reduzido para evitar publicar detalhes internos da produção. O SDD original permanece inalterado.

## Escopo e limites

A auditoria combinou leitura estática do código, revisão dos PRs, navegação autenticada somente de leitura e observações autorizadas do ambiente de produção. Não houve alteração em VPS, banco, mídia, configuração ou publicação. Valores de credenciais não foram lidos nem registrados. O estado observado é uma amostra temporal e não prova que todos os serviços, dados ou rotas estejam completos, ativos, recuperáveis ou equivalentes ao código versionado.

Conclusões deste resumo descrevem classes de achados, não os valores ou recursos específicos que os sustentam. Evidências detalhadas de infraestrutura e dados devem permanecer em armazenamento privado com acesso restrito; não devem ser copiadas para este repositório público.

## Achados que orientam o plano

| Área | Conclusão segura | Relação com o SDD |
|---|---|---|
| Código e implantação | Parte do produto está versionada e implantada; serviços dedicados e caminhos de execução ainda precisam de reconciliação individual. Uma etiqueta de revisão ou CI verde não demonstra equivalência integral nem prontidão funcional. | G4-09; TEST-27; WP-00 e WP-03 |
| Recuperação | Há material arquivado para comparação, mas captura parcial não equivale a backup integral. Não há prova suficiente, neste registro, de restauração ponta a ponta nem de reversão exercitada sem perda das gravações posteriores. | G4-09; TEST-27; WP-00 e WP-02 |
| Dados e schema | Foram encontrados vínculos e estruturas que precisam de mapeamento antes de novas migrações. A sequência deve continuar incremental, reversível e baseada em evidência; não se deve presumir que um backup foi restaurado porque pôde ser listado. | G1-05/06; G4-01/09; WP-00 e WP-01 |
| Publicação | A reconciliação entre estados locais e a plataforma de publicação ainda exige verificação. Artefatos enviados não devem ser reenviados nem removidos durante a auditoria. | G1-03/04/09; G4-08; WP-00 e WP-03 |
| Shorts | Há uma lacuna a investigar entre revisão/aprovação do Short, sua apresentação na Biblioteca e sua publicação autorizada. A existência de um arquivo concluído não comprova essa jornada. | G1-12/13; G5-07; WP-00, WP-03 e WP-08 |
| Portal novo e antigo | Algumas capacidades administrativas e de operação ainda dependem de comparação de paridade. O portal antigo só pode ser removido após a verificação das jornadas e estados exigidos pelo SDD. | G1-01/02; G3; WP-00 e WP-03 |
| Observabilidade e Growth | Há leituras e métricas disponíveis, porém a cobertura, a proveniência e as comparações por idade/formato precisam ser demonstradas antes de alegar projeção ou causalidade. | G2; G4-06; WP-00, WP-06 e WP-11 |

## Estado do trabalho

- **WP-00 continua em andamento.** Os achados acima não encerram o inventário de rotas, dados, serviços, estados, permissões, migrações e jornadas reais.
- **WP-01 não está liberado por este documento.** O PR de versionamento de roteiros é uma fatia técnica e ainda requer política correta de retenção/redação, proveniência completa e verificação de permissões.
- **TEST-27 segue pendente.** É necessário backup verificável, restauração isolada, simulação de falha e conferência da revisão instalada, sem sobrescrever gravações novas.
- **Nenhum deploy ou publicação é autorizado por este resumo.** A aprovação de código, validação em homologação, prova de restauração e observação de produção são etapas distintas.

## Próximas ações

1. Guardar inventários detalhados de produção e dados em local privado, com acesso mínimo e retenção definida; manter no GitHub apenas conclusões generalizadas necessárias ao trabalho.
2. Concluir o mapa de código e dados sem expor segredos, valores de configuração, identificadores de recursos ou conteúdo de usuário.
3. Revisar cada mudança de schema e de exclusão com migração reversível, isolamento de dados e comportamento de retenção explícito.
4. Completar a evidência de TEST-27 em ambiente isolado antes de usar o caminho de deploy automático.
5. Exercitar as jornadas de criação, revisão, Biblioteca e publicação com artefatos existentes e publicador simulado; não alterar vídeos reais durante a validação.
6. Atualizar este resumo apenas com conclusões que permaneçam seguras para publicação. Evidência detalhada fica fora do repositório público.
