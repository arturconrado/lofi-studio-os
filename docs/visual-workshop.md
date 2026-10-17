# Criar vídeo — base, inserções e aprovação por trecho

Entrada: **Criar vídeo** no menu do estúdio (`/studio/criar-video`). O fluxo anterior de produção musical continua disponível.

1. Defina a duração total em minutos (1–480), tema, cenário, movimento do cenário e personagens. Cada personagem aceita descrição e imagens; referências de cenário e de inserções são opcionais.
2. Descreva o movimento-base e sua pose inicial/final. Gere a imagem, confira a identidade e aprove. Só então gere o vídeo, assista e aprove a continuidade do loop.
3. Crie inserções com nome, descrição livre e duração. As imagens de inserção usam automaticamente a imagem-base aprovada, além das referências opcionais. Cada imagem e cada vídeo têm sua própria aprovação.
4. Salve bases e inserções aprovadas na biblioteca. Reaproveitamento de outro contexto mantém o briefing, mas exige gerar/aprovar os novos pixels. Trocar tema não transforma magicamente um vídeo existente.
5. Adicione os horários: um trecho pode entrar várias vezes. O limite operacional é 200 trechos e 500 ocorrências por projeto. O servidor recusa sobreposição, IDs desconhecidos e inserções que terminem após o vídeo.
6. Monte: a base preenche todos os intervalos, cada inserção toca uma vez à velocidade original e o próximo intervalo reinicia a base. A duração total não é estendida pelas inserções. Horários são arredondados ao quadro mais próximo (24 fps), evitando acumulação de erro em agendas extensas.
7. A música é obrigatória. Por padrão usa a trilha aprovada mais recente do mesmo canal com duração suficiente; é possível selecionar outra. O áudio original não é alterado nem repetido para disfarçar falta de duração. Se não houver trilha suficiente, prepare e revise na produção musical existente. A montagem gera um MP4 privado para assistir, aprovar e baixar; não publica automaticamente.

## Garantias e versões

- PostgreSQL conserva rascunho com revisão otimista, mídia imutável, biblioteca e tarefas no schema do workspace. Arquivos usam o armazenamento já segregado por workspace.
- Aprovação é vinculada a hash dos bytes e assinatura do cenário/personagens/movimento/referências. Alterar tema, personagens ou imagem-base invalida os trechos afetados. Alterar nome, música ou horários não exige comprar novamente os mesmos pixels.
- Arquivos anteriores são preservados e selecionáveis no trecho. Nenhuma inserção ausente é substituída silenciosamente pela base.
- Imagem e vídeo usam os adaptadores OpenRouter com os modelos já utilizados no projeto. Capacidades/preços são conferidos antes da reserva. O usuário confirma cada gasto; o limite global existente é respeitado. Não há retry pago nem fallback de provedor.
- Pedidos concorrentes/duplicados usam ID persistido e bloqueio. Estados `UNCERTAIN` preservam a reserva e bloqueiam novo pedido do mesmo tipo/trecho até reconciliação operacional.
- Vídeos prontos são obtidos em **Atualizar andamento**. Não há polling pago; somente consulta do pedido já criado.
- O worker de exportação existente também processa a nova fila local. Ele baixa fontes com hash conferido, normaliza os clipes, monta em ordem, inclui música, mede áudio/vídeo e decodifica o arquivo completo. A reprodução de base usa ciclo em disco para limitar RAM.
- Aprovação final não equivale a publicação. O usuário precisa assistir aos movimentos, às transições e à música; a IA não garante por si só identidade visual ou anatomia correta.

## Operação e implantação

Implantar API, frontend e serviço `python -m studio.exports` da mesma revisão. As três tabelas `visual_projects`, `visual_media` e `visual_library` são criadas de forma aditiva por workspace no primeiro uso. Nenhum projeto antigo, arquivo, receita ou transmissão é alterado.

Requisitos: armazenamento S3 já configurado, FFmpeg/ffprobe, chave e orçamento OpenRouter existentes, worker de exportação ativo. O catálogo pode recusar durações não suportadas pelo modelo; 8 segundos é o valor inicial. Cada base/inserção pode ter até 60 segundos no domínio, mas a geração fica limitada às capacidades reais do modelo selecionado. A capacidade de 480 minutos é limite de planejamento, não benchmark de render homologado.

Antes do deploy: executar CI Linux com PostgreSQL e FFmpeg. Depois, validar um piloto curto com os provedores configurados e aprovação humana dos personagens, movimento e retorno à base. Esta implementação não faz chamadas pagas durante os testes, não altera o programa arquivado LOFI-F54401BB e não certifica um deploy existente.

## Contratos do provedor

- Imagens e referências: https://openrouter.ai/blog/tutorials/image-generation/
- Vídeos e primeiro frame: https://openrouter.ai/docs/api/api-reference/video-generation/create-videos

## Validação

`tests/test_visual_workshop.py` cobre agenda, retorno à base, duração total, repetição de um asset em vários horários, revisão inválida, troca de contexto, isolamento e concorrência otimista na API. Um teste FFmpeg real monta azul → vermelho → azul, mede a duração e o áudio e examina quadros em tempos absolutos. `frontend/src/__tests__/workshop.test.tsx` cobre envio dos horários e bloqueios antes de salvar/aprovar. A suíte de banco exige `LOFI_TEST_DATABASE_URL` descartável.
