# SDD v2 — correções de continuidade e recuperação

Esta entrega altera o código existente. **Não declara o SDD inteiro concluído, nem contém novos gestos aprovados, publicação, geração paga ou homologação de 4/8 horas.** Produção permanece na versão anterior até um deploy específico.

## Implementado

- Registro versionado dos três episódios aprovados pelo responsável (Snowy, Greenhouse, Autumn), com hashes de imagem, movimento, vídeo e visual silencioso. O selo de referência visual exige o recibo do vídeo exato; não concede direitos comerciais nem aprova novos movimentos.
- Bloqueio do asset 8-bit rejeitado por chave e por hashes conhecidos, preservando arquivos e histórico. A seleção do ciclo antigo na live também é bloqueada. Não troca um vídeo já em transmissão.
- Conferência por streaming dos bytes do visual reutilizado antes de produzir novas músicas. Referência de movimento paga deve usar a identidade e a imagem-fonte do mesmo episódio canônico; capas com lettering não substituem a imagem original. Outros canais continuam isolados e podem importar/revisar seus próprios action clips; a geração paga por esse endpoint exige uma referência canônica disponível no próprio canal.
- Escolha das referências canônicas no editor avançado e importação do clipe original de digitação, sem geração. O clipe entra para revisão de enquadramento, props e costura; não vira automaticamente uma biblioteca de onze gestos.
- Preset novo com carinho/respiração em 15/45 e celular em 30 minutos. A agenda legada permanece explicitamente selecionável; seu hash criativo anterior é preservado. Cada evento declara poses de entrada/saída e posição de mãos, celular e gato; o compilador rejeita conflitos. Isso não certifica os movimentos nos pixels.
- Recoloração local opcional de blusa/almofada por máscaras, com exclusão de rosto/cabelo, gato e mãos/celular. Interface exige revisão das regiões em todos os clipes. A revisão das regiões e das máscaras é vinculada aos hashes dos clipes. Trocar os clipes invalida essa revisão. **Máscaras fixas não são tracking automático:** movimentos fora dessas regiões devem manter as cores originais até existirem máscaras animadas revisadas.
- Diagnóstico de áudio sem alterar catálogo, originais, masters ou aprovações; disponível na tela da faixa. Novas composições no batch passam pelo gate técnico; rejeições interrompem o lote sem retentativa paga. Aprovação artística continua separada.
- Mixagem derivada com crossfade para novos pedidos do Creator (1,5s por padrão), duração medida depois da sobreposição, fontes preservadas. Estimativa e parada do lote descontam a sobreposição. Pedidos antigos sem essa configuração mantêm concatenação legada; nenhum catálogo existente foi remasterizado. Um teto insuficiente pausa o pedido; não é aumentado automaticamente.
- BPM explícito no descritivo é respeitado no prompt; continua sendo intenção, não BPM medido.
- Prévia de 10s de uma janela do mesmo plano, com hashes, clipes, fase do loop, áudio e relógio ambiental absolutos. Janelas 0/15/30/45 no portal. Requer materiais aprovados do trecho, áudio e regiões; não exige inventar as outras ações ausentes. O corte inicial de uma amostra não substitui a revisão da costura com o trecho anterior no vídeo completo. Prévia não pode aprovar um programa completo.
- Checkpoints de segmentos com vínculo aos inputs, formato, versão do renderizador, integridade e quadro anterior. Retomada explícita no portal, no mesmo job; mudanças de materiais/revisões bloqueiam retomada. Segmento corrompido é refeito. Fontes/checkpoints são retidos em falha e limpos depois de upload concluído. Jobs anteriores a esta versão não ganham checkpoints retroativos.
- Relatório local registra tempo decorrido, bytes de saída e segmentos recuperados; custo de infraestrutura permanece desconhecido, não zero.
- Perfil versionado de cena, música e referências por canal, aplicável e editável no formulário sem fork. Revisões antigas ficam disponíveis por hash; perfis de outro canal não podem ser vinculados. Não herda orçamento nem autorização e não fornece poses ou assets ausentes.
- Jornada prioriza reutilizar antes de cotar IA. Retomar roteiro sincroniza a seleção de duração com o valor salvo.

## O que ainda impede a conclusão integral

1. **Assets articulados faltantes:** clipes completos de aproximação/carinho, saída/retorno do gato, celular e poses intermediárias. As bases existentes são reutilizadas; novos assets exigem cotação, produção e revisão visual de contato/anatomia. Nenhum deles foi fingido por deformação local.
2. **Tracking animado e biblioteca de poses/câmeras por personagem:** máscaras estáticas só atendem regiões que realmente permanecem fixas. A configuração versionada por canal existe; a biblioteca de poses/câmeras e a geração governada de novas ações ainda não estão completas.
3. **Backup integral externo e recuperação:** esta mudança não cria armazenamento externo imutável nem duplica o catálogo completo. A cópia local de inputs da auditoria e os arquivos existentes continuam preservados. Não chamar cache de disaster recovery.
4. **Proveniência/licenças e audição integral:** os registros ausentes continuam ausentes; um diagnóstico técnico não os substitui. O catálogo anterior não foi aprovado em massa.
5. **Capacidade/homologação longa:** não foi feito render de produção de 4/8h nem teste de transmissão. Limites de CPU/disco apontados na auditoria continuam relevantes. Cache de jobs falhos ocupa disco até retomada ou manutenção deliberada.
6. Métricas completas de custo por vídeo aprovado e retenção não são inferidas a partir de testes curtos.

## Validação e rollback

Os testes cobrem mídia local real com FFmpeg, integridade/retomada/corrupção, offsets da prévia, máscaras, crossfade e duração, diagnóstico sem mutação, isolamento, CSRF e contratos de interface. A jornada de criação foi exercitada em portal local logado, com PostgreSQL descartável, sem workers de geração ou transmissão.

Não alterar os workers de rádio/publisher para instalar esta entrega. Uma atualização futura deve usar API/Creator/exportador específicos, somente com filas inativas, preservando a imagem anterior para rollback. Nenhuma migração destrutiva foi acrescentada. Um job/checkpoint novo deve ser inspecionado antes de retornar a um worker antigo, que não conhece retomada. O JSON de decisões visuais é versionado no Git; qualquer revisão futura deve ser explícita e manter os arquivos originais.
