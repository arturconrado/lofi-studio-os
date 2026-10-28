# Bootstrap controlado do deployer de produção

O workflow **Bootstrap production deployer protocol 2** existe para instalar, por uma execução manual do GitHub Actions, a cópia revisada de ops/auto-deploy.sh no caminho fixo usado pela chave de deploy da VPS. Ele não faz deploy da aplicação, não reinicia serviços e não altera banco, volumes, mídia ou dados.

## Pré-requisitos do GitHub

1. Criar o Environment production-bootstrap, restringir sua implantação à branch main e configurar aprovação de revisor antes do início do job.
2. Adicionar nesse Environment o segredo VPS_BOOTSTRAP_KEY: uma chave SSH privada que já tenha acesso root ao servidor. Nunca adicionar chave privada ao repositório, issue, comentário ou workflow.
3. Confirmar os segredos existentes VPS_HOST, VPS_KNOWN_HOSTS e VPS_DEPLOY_KEY. O último continua limitado pelo comando forçado normal de deploy.

O segredo de bootstrap concede acesso root ao workflow. A aprovação e a restrição de branch do Environment devem estar ativas antes de executar. Se a organização não puder fornecer esse segredo e essa proteção, não execute o bootstrap.

## Execução

Depois do merge deste workflow, abrir Actions → Bootstrap production deployer protocol 2 → Run workflow na branch main. Exigir:

- Confirmação: INSTALL_PROTOCOL_2
- SHA-256 instalado esperado: 4b97425d9c53e5250de228aa01cbe48faa7a91e3b3a88871226a2272d8793a43

O segundo valor é o hash completo observado na captura read-only do WP-00 em 28/10/2026. Se o script atual no servidor tiver outro hash, o job falha sem substituí-lo; faça nova auditoria antes de qualquer tentativa.

O job copia apenas ops/auto-deploy.sh para o host, confirma o hash esperado do arquivo existente, guarda uma cópia com sufixo .pre-protocol2-<run_id>, instala o novo arquivo atomicamente e confirma o protocolo tanto no script quanto pelo comando SSH forçado. Se a troca falhar após a instalação, tenta restaurar a cópia anterior. Se o handshake da chave restrita falhar depois da troca, tenta restaurar atomicamente o backup via chave de bootstrap, desde que os hashes do candidato e do backup ainda correspondam aos esperados; preserva o candidato com falha e não apaga backups nem versões antigas.

## Limites após o bootstrap

Um handshake bem-sucedido prova apenas que a rotina de deploy protocol 2 está instalada e acessível pelo comando SSH forçado. Ele não publica a main, não prova restore/rollback (TEST-27), não resolve tarefas remotas UNCERTAIN, não valida a matriz de permissões em runtime, nem conclui WP-00. O deploy normal permanece em workflow separado, com gates próprios de CI e de produção ocupada.
