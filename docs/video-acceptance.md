# Aceitação dos motores de vídeo

O contrato compartilhado está em studio/video_guardrails.py. Duração do áudio não comprova duração visual. Repetir partículas ou pequenos gestos é permitido; repetir um ciclo curto não comprova evolução temporal de oito horas.

Cada motor deve entregar um relatório vinculado ao SHA-256 do MP4 final, com duração visual medida, decodificação completa, cobertura da linha temporal real, preservação das fontes e revisão humana de movimento perceptível, evolução de tempo e transições contínuas. A revisão deve identificar o operador e o hash exato revisado. Métricas de pixels não substituem a revisão artística nem comprovam retenção.

O harness mede o arquivo com ffprobe e o decodifica com ffmpeg. Evidências externas não podem sobrescrever essas medições. Ausência de evidência reprova; não inicia novas gerações nem retentativas pagas.

Uso: python -m studio.video_guardrails arquivo.mp4 --target-seconds 28800 --evidence revisao.json --output relatorio.json

Código de saída 0: contrato atendido. Código 2: reprovação com motivos no relatório. Falhas de leitura ou ferramentas também impedem sucesso.

Integração atual: novos pacotes do creator registram o contrato no manifesto; a API de início manual bloqueia novos pacotes reprovados. Registros legados sem contrato conservam sua revisão histórica e NÃO estão certificados por este contrato. O motor de episódios ambient e as rotas legadas ainda precisam migrar para o contrato antes de se afirmar cobertura universal. Não migrar aprovações históricas implicitamente.

A prévia de 64 segundos é um estudo acelerado. O renderizador de uma jornada real de oito horas permanece pendente; este contrato não cria esse renderizador.
