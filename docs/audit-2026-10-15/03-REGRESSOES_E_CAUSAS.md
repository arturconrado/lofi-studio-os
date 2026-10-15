# 03 — Diagnóstico da regressão

Baseline: três episódios de 1h aprovados pelo responsável. Comparação problemática: imagem e loop originais de `LOFI-3A590745`, não o Greenhouse aplicado posteriormente ao player.

## Matriz causal

| Achado | Evidência | Causa sustentada / confiança | Correção mínima proposta | Teste | Esforço relativo |
|---|---|---|---|---|---|
| R1: composição/personagem diferentes | Imagem original da referência 8-bit; Creator original sem `input_references`; série aprovada com referência visual explícita | Perda de condicionamento visual entre dois caminhos distintos. **Alta** para o mecanismo; não atribuir toda diferença a um único parâmetro de prompt | Vincular novas variantes a assets aprovados e versionados; bloquear redesenho global como alternativa silenciosa | Imagem-base/hash obrigatórios e comparação da personagem antes de animar | Pequeno para bloqueio; médio para adaptação de estilo |
| R2: cabeça extra na almofada | A cabeça já existe em `scene.png`, anterior ao FFmpeg | Artefato da imagem de entrada. **Alta** de que não foi criado pela microanimação; não há prova de qual token específico provocou a alucinação | Reprovar/quarentenar somente esse asset; reutilizar baseline; não tentar ocultá-lo com efeitos | Comparar source com frame zero e rejeitar personagem extra | Pequeno |
| R3: movimentos fracos/ausentes | `scene_animation.py:10–64`: translações subpixel, chuva/vapor, 20s; sem trajetória de gato ou gesto de carinho | Escolha de motor incapaz de executar a interação pedida. **Alta** | Manter movimento da baseline; declarar ações novas como ausentes até haver clipe/pose revisado | Trecho em velocidade real início→ação→retorno; proibir marcar ação pronta com chuva/vapor | Médio |
| R4: ausência de progressão de hora | Loop legado de 20s; manifest original informa 60s; `production_spec=null` | Agenda avançada não foi usada nesse pedido. **Alta** | Mesmo manifest para preview e montagem; amostrar marcos reais, não repetir estudo ambiental como prova de hora | Parear frames/estado da prévia com segundos absolutos do episódio | Médio |
| R5: deformação aplicada fora da personagem | Máscaras geométricas fixas em `scene_animation.py:12–16`; protagonista da imagem 8-bit está deslocada para a direita | Incompatibilidade verificável de geometria. **Alta** para coordenadas; contribuição perceptiva exata exige comparação de frames | Máscaras específicas do asset, revisadas e com limites de transformação | Overlay das regiões e diff das áreas protegidas | Médio |
| R6: pixel art contradita pelo backend | Prompt persistido pede pixels; código original acrescenta `Original painterly lo-fi illustration` | Instruções visuais conflitantes. **Alta** quanto ao conflito; impacto individual não isolado | Separar estilo musical de perfil visual e preservar referência; adaptar estilo apenas com aprovação | Validador de plano não pode acrescentar estilo incompatível | Pequeno |
| R7: troca de roupa sem preservação seletiva | Cor é campo/prompt no harness; não foi localizado operador de recolor com máscara aprovada | Recolor seletivo **ausente** no caminho inspecionado. **Alta** para ausência no código; a cor violeta isoladamente não foi provada como causa do drift | Máscaras separadas de roupa/almofada; manter face, cabelo, pele, gato e fundo protegidos | Alterar só cor e verificar diff fora das máscaras com tolerância calibrada | Médio |
| R8: asset defeituoso continua selecionável | Programa atual tem Greenhouse como `video_key`, mas ciclo/scene antigos permanecem | Correção de seleção não equivale a rejeição do asset. **Alta** | Registrar rejeição e excluir de novas escolhas/reuso, preservando histórico e bytes | Asset rejeitado não pode virar default nem entrar em export novo | Pequeno |

## O que não foi demonstrado

- Não foi demonstrado que uma alteração global de FFmpeg ou uma biblioteca nova corrompeu os três episódios aprovados.
- Não foi demonstrado que mudar a cor da blusa, por si só, altera rosto/gato.
- Não foi demonstrado que o renderer local consiga movimentos L2/L3 a partir de uma imagem única.
- Hash igual comprova integridade de bytes; não comprova naturalidade, identidade semântica, originalidade musical ou retenção.

## Linha de alterações verificada

- `a08b901`: importação da base existente, incluindo caminhos locais de animação; portanto não se pode atribuir automaticamente seu aparecimento à última mudança de cor.
- `3fda505`, `d08ce8e`, `8580e0a`, `263a890`: contratos de ações, referência curta e planejamento/reuso.
- `a3a08c9`: montagem local de timeline com inputs revisados; sem gerador de clipes articulados ausentes.
- `a502d47` / `9982c25` / `7af6a06` / `a8957d6`: correção de início/retomada do Creator, consulta e cache da UI. Não corrigem a identidade do arquivo 8-bit já gerado.
- `bf5c851`: nova produção do fluxo legado exige episódio publicado como fonte visual e reutiliza seu vídeo. Teste específico confirma que não chama microanimação para recriar a personagem. Isso mantém a baseline, mas não implementa gestos adicionais ou uma conversão pixel art.

A data de criação dos scripts de geração da série e seus hashes são preservados como evidência operacional; não se atribui commit Git a scripts que estavam fora do repositório.

## Comparações

Ver `evidence/visual-comparison.png`, `evidence/mask-overlay.png` e a folha de contato de marcos temporais. A comparação entre a composição original e a 8-bit tem geometria diferente: um diff global não deve ser usado como escore automático de identidade. Crops e leitura humana são a evidência principal para o rosto extra e a troca de design.

## Movimento realmente documentado nos episódios aprovados

As requisições preservadas pedem digitação, respiração discreta, uma piscada, respiração/rabo/piscadas do gato e precipitação/vapor, com câmera fixa e retorno à postura inicial. Os assets de movimento existem e decodificam. Não pedem a sequência completa de carinho, celular, saída e retorno do gato nos marcos longos. O reuso desses clipes é uma base útil; não preencherá sozinho todas as ações futuras.

Os frames amostrados em 15/30/45 mostram composição muito próxima da inicial, coerente com ciclos repetidos. Isso não reprova os episódios aprovados e não demonstra um novo arco temporal ou execução da nova agenda. Métricas auxiliares em `frame-diagnostics.json`; sua interpretação é limitada à amostragem.
