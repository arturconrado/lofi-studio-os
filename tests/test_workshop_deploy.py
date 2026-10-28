"""Exercise the actual backup check with complete, corrupt and failed listings."""
import os
import subprocess
from pathlib import Path
import pytest


@pytest.mark.skipif(os.name == 'nt', reason='Production deploy runs Bash on Linux')
@pytest.mark.parametrize('output,code,success', [('TABLE DATA public.example\n'*50000,0,True),('corrupt archive\n',0,False),('TABLE DATA public.example\n',1,False)], ids=['complete-list','missing-data','restore-error'])
def test_backup_listing_consumes_all_output_and_checks_restore_exit(tmp_path,output,code,success):
    script=Path('ops/auto-deploy.sh').read_text()
    check=script[script.index('listing="$dump.list"'):script.index("printf 'FROM")]
    archive=tmp_path/'backup.dump';archive.write_bytes(b'fixture')
    listing=tmp_path/'restore-output.txt';listing.write_text(output)
    env={**os.environ,'TEST_DUMP':str(archive),'TEST_LISTING':str(listing),'TEST_EXIT':str(code)}
    stub='''set -euo pipefail
say() { echo "$*"; }
fail() { echo "$*"; exit 1; }
docker() { cat "$TEST_LISTING"; return "$TEST_EXIT"; }
dump="$TEST_DUMP"
PG=fixture
'''
    result=subprocess.run(['bash','-c',stub+check],env=env,capture_output=True,text=True)
    assert (result.returncode==0) is success
    if success: assert Path(str(archive)+'.list').read_text()==output


def test_youtube_publisher_deploy_is_versioned_and_upload_safe():
    script=Path('ops/auto-deploy.sh').read_text()
    assert 'SERVICES=(studio creator export-worker youtube-publisher)' in script
    assert "FROM youtube_publications WHERE state='uploading'" in script
    assert "'youtube-publisher'):d['services'][s]['image']" in script
    assert 'studio.youtube_publish' in script
    assert 'for s in "${SERVICES[@]}"; do' in script


def test_unresolved_paid_jobs_block_deployment(tmp_path):
    script=Path('ops/auto-deploy.sh').read_text()
    start=script.index("busy=$(sql <<'EOF'")
    end=script.index('\ncurrent=',start)
    gate=script[start:end]
    assert "status IN ('QUEUED','RUNNING','SUBMITTING','UNCERTAIN')" in gate

    env={**os.environ,'TEST_BUSY_COUNT':'1'}
    stub='''set -euo pipefail
sql() { cat >/dev/null; printf '%s' "$TEST_BUSY_COUNT"; }
fail() { exit "$2"; }
'''
    result=subprocess.run(['bash','-c',stub+gate],env=env,capture_output=True,text=True)
    assert result.returncode==75


@pytest.mark.parametrize('failure,success',[('none',True),('service',False),('compose',False)])
def test_deploy_rollback_restores_and_verifies_previous_services(tmp_path,failure,success):
    script=Path('ops/auto-deploy.sh').read_text()
    start=script.index('rollback() {')
    end=script.index('\nif ! docker compose',start)
    rollback=script[start:end]
    previous=tmp_path/'previous.json';previous.write_text('{"version":"old"}')
    current=tmp_path/'current.json';current.write_text('{"version":"new"}')
    env={**os.environ,'TEST_FAILURE':failure,'TEST_CURRENT':str(current)}
    stub='''set -euo pipefail
say() { :; }
fail() { exit 1; }
SERVICES=(studio creator export-worker youtube-publisher)
previous_images=(old-image old-image old-image old-image)
previous_revisions=(old-sha old-sha old-sha old-sha)
rollback_compose="$TEST_PREVIOUS"
COMPOSE="$TEST_CURRENT"
PROJECT=fixture
docker() {
  if [ "$1" = compose ]; then [ "$TEST_FAILURE" != compose ]; return; fi
  container="$2"; format="$4"; service=""
  for name in "${SERVICES[@]}"; do if [[ "$container" == *"$name-1" ]]; then service="$name"; fi; done
  case "$format" in
    '{{.State.Running}}') if [ "$TEST_FAILURE" = service ] && [ "$service" = creator ]; then echo false; else echo true; fi ;;
    '{{.Config.Image}}') echo old-image ;;
    '{{index .Config.Labels "org.opencontainers.image.revision"}}') echo old-sha ;;
    *) return 2 ;;
  esac
}
'''
    env['TEST_PREVIOUS']=str(previous)
    result=subprocess.run(['bash','-c',stub+rollback+'\nrollback'],env=env,capture_output=True,text=True)
    assert (result.returncode==0) is success
    assert current.read_text()==previous.read_text()
