#!/usr/bin/env bash
# Automatic production deploy, run on the VPS as the forced command of the GitHub deploy key.
#
# Input: SSH_ORIGINAL_COMMAND="deploy <sha>" and a tar of studio/, web/ and requirements.txt on stdin.
# Updates studio, creator, export-worker and youtube-publisher. Radio, channel-radio and the music
# worker stay manual. Exits 75 (try later) while work is in progress, and rolls back on a failed
# health check.
set -euo pipefail

ROOT=/opt/lofi-studio-os-releases
COMPOSE_DIR=$ROOT/d877875
COMPOSE=$COMPOSE_DIR/compose.production-final.private.json
PROJECT=lofi-vibe-coding
SERVICES=(studio creator export-worker youtube-publisher)
BACKUPS=/srv/lofi-backups
PG=clipbr-vps-postgres-1

say() { echo "[auto-deploy] $*"; }
fail() { say "ERRO: $1"; exit "${2:-1}"; }

request="${SSH_ORIGINAL_COMMAND:-}"
[[ "$request" =~ ^deploy\ ([0-9a-f]{7,40})$ ]] || fail "uso: deploy <sha>" 2
FULL_SHA=${BASH_REMATCH[1]}
SHA=${FULL_SHA:0:7}

exec 9>/var/lock/lofi-auto-deploy.lock
flock -n 9 || fail "outro deploy em andamento" 75

sql() { docker exec -i "$PG" sh -c 'psql -U "$POSTGRES_USER" -d lofi_studio -tA' ; }

# 1. Never interrupt renders, exports, paid batches, uploads or a live broadcast.
busy=$(sql <<'EOF'
SELECT (SELECT count(*) FROM production_batches WHERE state IN ('queued','producing','waiting'))
     + (SELECT count(*) FROM export_jobs WHERE state IN ('queued','running'))
     + (SELECT count(*) FROM factory_tasks WHERE status IN ('QUEUED','RUNNING','SUBMITTING'))
     + (SELECT count(*) FROM youtube_publications WHERE state='uploading')
     + (SELECT count(*) FROM radio_channels WHERE desired='live')
     + (SELECT count(*) FROM broadcast_control WHERE desired='live');
EOF
)
[ "${busy:-1}" = "0" ] || fail "produção ocupada ($busy itens em andamento); tente mais tarde" 75

current=$(docker inspect lofi-vibe-coding-studio-1 --format '{{.Config.Image}}')
all_current=1
for s in "${SERVICES[@]}"; do
  container="lofi-vibe-coding-$s-1"
  image=$(docker inspect "$container" --format '{{.Config.Image}}' 2>/dev/null || true)
  revision=$(docker inspect "$container" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true)
  { [ "$image" = "lofi-studio-os:production-$SHA" ] && [ "$revision" = "$FULL_SHA" ]; } || all_current=0
done
[ "$all_current" = 1 ] && { say "versão $SHA já está em todos os serviços gerenciados"; exit 0; }

# 2. Unpack the release.
R=$ROOT/$SHA
rm -rf "$R.tmp" && mkdir -p "$R.tmp" && tar -x -C "$R.tmp"
[ -d "$R.tmp/studio" ] && [ -d "$R.tmp/web/app" ] || fail "pacote sem studio/ ou web/app"
rm -rf "$R" && mv "$R.tmp" "$R"

# 3. Dependencies changed: the incremental image would miss them. Manual deploy required.
if ! docker run --rm --entrypoint cat "$current" /app/requirements.txt 2>/dev/null | cmp -s - "$R/requirements.txt"; then
  fail "requirements.txt mudou; faça o deploy manual (imagem completa)" 3
fi

# Transmitter code is never deployed automatically; report when it is now behind.
radio_image=$(docker inspect lofi-vibe-coding-radio-1 --format '{{.Config.Image}}')
behind=""
for f in programming.py continuous.py continuous_radio.py program_radio.py channel_radio.py radio.py miniobs.py; do
  if ! docker run --rm --entrypoint cat "$radio_image" "/app/studio/$f" 2>/dev/null | cmp -s - "$R/studio/$f"; then behind="$behind $f"; fi
done

# 4. Backup, then build on top of the image in production.
umask 077
TS=$(date -u +%Y%m%dT%H%M%SZ)
dump=$BACKUPS/lofi-db-$TS-pre-$SHA.dump
docker exec "$PG" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc lofi_studio' > "$dump"
# Consume the complete listing: grep -q can close the pipe early and make
# pg_restore/docker fail with SIGPIPE under pipefail even for a valid dump.
listing="$dump.list"
docker exec -i "$PG" pg_restore --list < "$dump" > "$listing" || fail "backup ilegível: pg_restore falhou"
grep 'TABLE DATA' "$listing" > /dev/null || fail "backup sem dados de tabelas"
say "backup listado e verificado: $dump"
printf 'FROM %s\nLABEL org.opencontainers.image.revision="%s"\nUSER root\nCOPY studio /app/studio\nCOPY web /app/web\nUSER 10002\n' "$current" "$FULL_SHA" > "$R/Dockerfile.incremental"
nice -n 10 docker build -q -f "$R/Dockerfile.incremental" -t "lofi-studio-os:production-$SHA" "$R" >/dev/null
docker run --rm "lofi-studio-os:production-$SHA" python -c 'import studio.api,studio.exports,studio.creator_service,studio.youtube_publish' \
  || fail "a imagem nova não importa os módulos; nada foi trocado"

# 5. Swap the managed services, keeping the previous compose for rollback.
cp -p "$COMPOSE" "$COMPOSE_DIR/compose.production-final.private.before-$SHA.private.json"
python3 - "$COMPOSE" "$SHA" <<'EOF'
import json,sys
path,sha=sys.argv[1],sys.argv[2];d=json.load(open(path))
for s in ('studio','creator','export-worker','youtube-publisher'):d['services'][s]['image']='lofi-studio-os:production-'+sha
json.dump(d,open(path,'w'),indent=2)
EOF
docker compose -p "$PROJECT" -f "$COMPOSE" up -d --no-deps "${SERVICES[@]}" >/dev/null 2>&1

healthy() {
  for s in "${SERVICES[@]}"; do
    [ "$(docker inspect lofi-vibe-coding-$s-1 --format '{{.State.Running}}')" = "true" ] || return 1
    [ "$(docker inspect lofi-vibe-coding-$s-1 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$FULL_SHA" ] || return 1
  done
  docker exec lofi-vibe-coding-studio-1 python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=5).status==200 else 1)" 2>/dev/null
}
ok=0
for _ in $(seq 1 30); do sleep 3; if healthy; then ok=1; break; fi; done
if [ "$ok" != 1 ]; then
  cp -p "$COMPOSE_DIR/compose.production-final.private.before-$SHA.private.json" "$COMPOSE"
  docker compose -p "$PROJECT" -f "$COMPOSE" up -d --no-deps "${SERVICES[@]}" >/dev/null 2>&1
  fail "saúde não confirmada; voltei para $current"
fi

cat > "$R/DEPLOY-RECORD.txt" <<EOF
deployed_at=$(date -u +%FT%TZ)
commit=$FULL_SHA (automatic, after CI)
image=lofi-studio-os:production-$SHA
services_updated=${SERVICES[*]}
previous_image=$current
db_backup=$dump
transmitter_code_behind=${behind:-none}
rollback: cd $COMPOSE_DIR && cp compose.production-final.private.before-$SHA.private.json compose.production-final.private.json && docker compose -p $PROJECT -f compose.production-final.private.json up -d --no-deps ${SERVICES[*]}
EOF
chmod 600 "$R/DEPLOY-RECORD.txt"

# 6. Disk: drop production images that no container uses, keeping the 4 newest for rollback.
used=$(docker ps -a --format '{{.Image}}' | sort -u)
docker image ls lofi-studio-os --format '{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}' | grep ':production-' | sort -r | awk -F'\t' 'NR>4{print $2}' |
while read -r image; do
  grep -qx "$image" <<<"$used" || docker image rm "$image" >/dev/null 2>&1 || true
done
docker builder prune -f --filter until=72h >/dev/null 2>&1 || true
find "$BACKUPS" -name 'lofi-db-*.dump' -mtime +21 -delete 2>/dev/null || true

say "versão $SHA nos serviços gerenciados (antes: ${current#lofi-studio-os:production-})"
[ -n "$behind" ] && say "AVISO: código dos transmissores mudou ($behind ); radio/channel-radio precisam de deploy manual"
say "disco: $(df -h / | awk 'NR==2{print $5" usado, "$4" livres"}')"
exit 0
