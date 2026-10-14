# Aceitação dos motores de vídeo

O contrato compartilhado está em studio/video_guardrails.py. Duração do áudio não comprova duração visual. Repetir partículas ou pequenos gestos é permitido; repetir um ciclo curto não comprova evolução temporal de oito horas.

Cada motor deve entregar um relatório vinculado ao SHA-256 do MP4 final, com duração visual medida, decodificação completa, cobertura da linha temporal real, preservação das fontes e revisão humana de movimento perceptível, evolução de tempo e transições contínuas. A revisão deve identificar o operador e o hash exato revisado. Métricas de pixels não substituem a revisão artística nem comprovam retenção.

O harness mede o arquivo com ffprobe e o decodifica com ffmpeg. Evidências externas não podem sobrescrever essas medições. Ausência de evidência reprova; não inicia novas gerações nem retentativas pagas.

Uso: python -m studio.video_guardrails arquivo.mp4 --target-seconds 28800 --evidence revisao.json --output relatorio.json

Código de saída 0: contrato atendido. Código 2: reprovação com motivos no relatório. Falhas de leitura ou ferramentas também impedem sucesso.

Integração atual: novos pacotes do creator registram o contrato no manifesto; a API de início manual bloqueia novos pacotes reprovados. Registros legados sem contrato conservam sua revisão histórica e NÃO estão certificados por este contrato. O motor de episódios ambient e as rotas legadas ainda precisam migrar para o contrato antes de se afirmar cobertura universal. Não migrar aprovações históricas implicitamente.

A prévia de 64 segundos é um estudo acelerado. O renderizador de uma jornada real de oito horas permanece pendente; este contrato não cria esse renderizador.

## Roteiro audiovisual com ações

`production_harness.py` compila um roteiro gratuito de 1–8h para cidade ao entardecer, montanhas com estrelas ou varanda ao amanhecer. As pausas e interações repetem a cada hora; iluminação evolui uma vez e mantém o estado final, evitando reinício brusco. As durações não informadas no pedido ficam em `assumptions`. A blusa e a almofada usam a mesma cor. Texto da almofada é uma camada local rastreada, evitando depender de letras geradas por IA.

Cada ação produz uma tarefa de clipe condicionado às referências. A chave de reutilização inclui identidade, cenário, cor e ação, mas NÃO comprova existência de cache. O executor futuro deve verificar assets no armazenamento do próprio workspace, preço atual e teto antes de enviar qualquer solicitação. O adaptador de geração de ações ainda não existe; todos os clipes são declarados ausentes. A API recusa enviar esse roteiro ao antigo renderer de chuva/vapor.

`assess_delivery` exige duração visual e musical, revisão de identidade/objetos/contato, comprovação dos eventos no hash final e revisão do estilo musical. Não certifica engajamento nem retenção. As séries podem usar direção 8-bit, jazz ou livre sem o antigo prompt fixo de Rhodes. Geração completa de áudio continua sujeita ao orçamento e à duração real, sem faixas repetidas para declarar horas inéditas.

Editor: Criar → Direção de cena, ações e música. Preparar e salvar não chama provedor. Roteiros são salvos em creator_plans no workspace atual e podem ser retomados/editados. Não altera live, mídia, aprovação ou agenda existentes.

## Piloto de movimento no portal

`motion_validation.py` disponibiliza um teste isolado de oito segundos com imagem de uma cena do próprio canal, via OpenRouter Veo 3.1 Lite. Consulta capacidades/preços atuais, reserva o maior SKU por segundo conhecido e exige confirmação do valor apresentado. O orçamento de validação desta etapa soma no máximo US$2 em reservas duráveis de factory_tasks, incluindo pedidos incertos. A reserva também passa pelo limite financeiro geral. Não há retentativa de submissão.

A atualização de resultado apenas consulta o mesmo job e salva o MP4 privado com hash, decodificação e indicação demo_only. Não altera cenas aplicadas, áudio ou lives. O piloto testa contato e articulação; não executa todas as ações do roteiro nem certifica anatomia ou duração de oito horas. O motor completo continua bloqueado até seus assets e integração estarem prontos.
