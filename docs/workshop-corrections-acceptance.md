# Criar vídeo: execução e aceite do plano consolidado

Projeto de homologação: `546e25bd-bcc2-4d9c-98a4-272afad79acb`.
PR de desenvolvimento: #44. Não integrar nem implantar como pacote homologado
antes de concluir os aceites abaixo. Nenhuma geração paga faz parte dos testes.

## Contratos implementados

- Uma base recorrente; inserções ocupam tempo dentro da duração total.
- Workshop/editor compartilham a agenda do Harness e o compositor/preview.
- Ocorrências guardam seleções de imagem/vídeo e proveniência de origem. Projetos
  antigos continuam válidos, pois os novos campos são opcionais e aditivos.
- Ações em horários com estados diferentes recebem variantes internas. O usuário
  não duplica clipes para resolver fases. A chave vincula origem, quadro, duração
  do ciclo, coreografia e base de retorno; a montagem usa a variante de cada ocorrência.
- Reaproveitamento de uma origem compatível evita geração nova. Cada emenda nos
  novos horários continua exigindo revisão; igualdade de um quadro não certifica
  movimento fluido. Aprovações legadas permanecem preservadas para homologação.
- O orçamento cobre todas as variantes novas antes do primeiro envio. Pedidos em
  lote são persistidos e processados pelo worker do workspace, mesmo com a página
  fechada. A reserva impede envio duplicado. Um envio SUBMITTING/UNCERTAIN nunca é
  repetido automaticamente. Pedidos ainda QUEUED cujo roteiro mudou são cancelados
  antes do provedor e liberam apenas sua reserva comprovadamente não enviada.
- A preparação visual baixa/normaliza cada origem uma vez por lote. A extração e
  a montagem compartilham a normalização de FPS e enquadramento, sem redesenhar
  imagens. A geração usa primeiro/último quadro conforme capacidades consultadas.
- Ações longas recebem proposta de durações aceitas com soma exata e poucas partes.
  O objetivo completo é preservado separadamente. A preparação/execução/retorno de
  cada parte são editáveis antes de aplicar. Aplicar salva roteiro e horários, sem
  gerar mídia. Não há inferência semântica de todas as ações descritas em linguagem
  livre: a pessoa revisa essa proposta antes de gastar.
- Partes são consecutivas e usam o vídeo disponível da parte anterior como origem.
  A continuação pode ser preparada antes da aprovação dessa parte, evitando o ciclo
  em que a prévia exige uma continuação que ainda não pode ser gerada. Todos os vídeos
  e emendas usados precisam de aprovação antes da montagem final.
- A prévia do loop-base independe das inserções ainda não geradas, inclusive quando
  uma ação está marcada em 00:00. Prévias de ação usam a timeline real e suas variantes.
- Duplicação remapeia referências e seleções de todas as ocorrências, compartilha
  bytes imutáveis e preserva aprovações de pixels somente quando a assinatura é
  reproduzível. As emendas da cópia precisam de revisão própria; o original não muda.

## Validação exigida

| Requisito | Evidência de software | Aceite real ainda necessário |
| --- | --- | --- |
| Agenda e duração | 62 min/base 8 s e combinação diferente; sobreposição recusada | Render completo nas duas configurações |
| Variantes | Horários diferentes, reuso, troca de fase e montagem por ocorrência | Conferir ação/identidade em todos os cortes |
| Partes | Soma exata, horários consecutivos, objetivos preservados e ausência de ciclo de aprovação | Revisar movimento entre todas as partes |
| Custos e recuperação | Cotação total, reserva única, idempotência, fila e cancelamento anterior ao envio | Piloto pago com orçamento autorizado |
| Aprovações | Prévias e aprovação por variante, invalidação apenas quando relevante | Quatro emendas: loop, entrada, partes e retorno |
| Duplicação | Referências/seleções remapeadas, pixels compatíveis, original preservado | Conferir cópia de projeto publicado |
| Implantação | Verificação integral da listagem do backup e revisão dos serviços | Logs do VPS, restauração isolada, rollback e revisão instalada |

## Limites que impedem declarar o pacote homologado

1. O provedor configurado recebe quadros, sem uma trajetória temporal real de entrada.
   Não inventar suporte a vídeo de referência nem trocar provedor/custo silenciosamente.
   Validar capacidade e piloto antes de prometer continuidade articulada automática.
2. A divisão proposta organiza duração e etapas; a adequação semântica do roteiro
   continua sujeita à revisão. Não apresentá-la como interpretação perfeita de uma ação longa.
3. Não foram acessados nem alterados os dados do projeto real. Seu inventário, cópia,
   personagens, gato, cenário, áudio e materiais aprovados devem ser homologados.
4. A hipótese do erro de backup precisa ser confrontada com os logs do VPS e com
   restauração real. Testes de listagem não substituem essa prova operacional.
5. A autonomia administrativa permanece fora deste pacote.

## Ordem para liberar

Revisão do código e CI Linux/PostgreSQL/FFmpeg -> cópia isolada do projeto real ->
verificações sem novas compras -> piloto de geração com custo autorizado -> revisão
das quatro emendas e usabilidade -> dois renders completos -> backup/restauração e
rollback -> autorização de implantação -> revisão registrada e tela conferida.
