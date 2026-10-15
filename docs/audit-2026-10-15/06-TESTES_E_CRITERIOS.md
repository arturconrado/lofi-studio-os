# 06 — Testes, amostragem e critérios

## Executado nesta auditoria

- **90 testes Python passaram** em PostgreSQL descartável, com 3 avisos de depreciação já existentes. Nenhum teste usou produção como fixture. Resultado integral em `evidence/python-tests.txt`.
- **6 verificações de interface passaram:** estado de storyboard, assistente de formulário, interface de estúdio, UI de catálogo, login e montagem temporal. Logs em `evidence/interface-tests.json`.
- Compilação sem geração de um roteiro de 1h: 32 eventos, 40 segmentos, 3.600s, nenhum overlap de intervalos e 11 tipos de clipes ausentes (`timeline-inspection.json`).
- Verificação de objetos/cópias, frames e áudio: resultados finais em `evidence/media-evidence.json`, sem nova geração ou alteração das fontes.

Esses testes não certificam qualidade artística nem disponibilidade de ações que não existem no catálogo. Não foi renderizado um novo vídeo longo para executar a auditoria.

## Amostragem visual e seus limites

Frames dos episódios: 0, 3, 7,46, 7,50, 719,96, 720, 900, 1800, 2700 e 3599,70s. O objetivo é confrontar início, fonte curta, fronteira do ciclo e marcos da hora. Não é inspeção de cada frame.

Comparar separadamente:

- Fonte estática aprovada × fonte 8-bit rejeitada: rosto, cabelo, gato e composição. Geometrias diferentes impedem interpretar um diff global como escore de identidade.
- Fonte 8-bit × frame zero: demonstrar que o rosto extra é anterior à animação.
- Antes/depois das costuras: diferença de pixels é diagnóstico auxiliar, não aprovação semântica de movimento.
- 0/15/30/45/final: medir luminância e observar estado; não atribuir uma progressão narrativa inexistente a pequenas variações do loop.

## Plano de regressão para a correção posterior

| Caso | Critério |
|---|---|
| Identidade | Baseline/hash declarados; revisão comparativa da garota e gato antes de animar; nenhum personagem extra |
| Recolor | Mudar somente a máscara de roupa/almofada; diff das regiões protegidas dentro de tolerância calibrada no corpus real |
| Ação | Clip cobre duração real e poses inicial/final; mãos não digitam e acariciam/seguram celular ao mesmo tempo |
| Agenda | Novo preset gera marcos 900/1800/2700; preset legado mantém seus tempos e hashes de aprovação |
| Ambiente | Luz contínua no relógio absoluto, sem corte de dia/noite; seam 24/7 validado separadamente |
| Preview | Mesmos IDs/hashes e eventos do manifest final; direção condensada e loop em tempo real são duas saídas distintas |
| Áudio | Decode completo, duração, true/sample peak, silêncio, loudness, duplicação e audição separados; thresholds editoriais calibrados |
| Cache | Alterar só playlist não reprocessa visual; trocar máscara invalida apenas derivados correspondentes |
| Recuperação | Interromper job somente em ambiente descartável; retomar do último segmento validado sem cobrança ou repetição automática |
| Privacidade | Assets de outro workspace/canal não podem ser escolhidos; erros e relatórios sem segredos |
| Exportação | Duração final ±1s do SDD, streams A/V corretos e hash estável; aprovação artística e publicação continuam explícitas |

## Não executado / não demonstrado

Teste perceptual de todas as 241 faixas, revisão de cada mão em todos os frames, recolor seletivo inexistente, rig L2/L3, nova execução 4/8h, retomada por checkpoints ainda não implementada, efeito em retenção e certificação jurídica de licenças. Não se usa “90 testes passaram” para preencher essas lacunas.

## Interpretação do áudio

As medições documentadas devem informar fonte e escopo. Recibos históricos de loudness só são reutilizados quando vinculados ao áudio cujo hash foi confrontado. Uma nova medição LUFS completa que não conclua dentro do limite operacional não é reportada como realizada; a auditoria pode complementar com análise de pico/silêncio e registrar a limitação. O limiar de silêncio diagnóstico não é um critério universal de aceitação.

## Recuperação local e preservação final

O snapshot do código foi extraído em diretório temporário e os hashes dos 23 arquivos de aplicação indexados coincidiram. Os três clipes-base copiados foram decodificados sem erro. As seis cópias locais de imagem/fonte de movimento coincidem com os hashes medidos em produção. Isso valida recuperação desses insumos, não um restore integral de desastre do catálogo.

A comparação antes/depois apresentou os mesmos digests de dados/configurações, mesmas contagens de tabelas, 256 jobs antes/depois, mesmos IDs de tarefas, publicações e estado do canal (`preservation-result.json`). Nenhum pedido de geração, publicação ou transmissão foi criado pela auditoria.
