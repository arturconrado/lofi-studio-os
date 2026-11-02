"""Exercise the actual backup check with complete, corrupt and failed listings."""
import os
import subprocess
from pathlib import Path
import pytest


@pytest.mark.skipif(os.name == 'nt', reason='Production deploy runs Bash on Linux')
@pytest.mark.parametrize('output,code,success', [('TABLE DATA public.example\n'*50000,0,True),('corrupt archive\n',0,False),('TABLE DATA public.example\n',1,False)], ids=['complete-list','missing-data','restore-error'])
def test_backup_listing_consumes_all_output_and_checks_restore_exit(tmp_path,output,code,success):
    script=Path('ops/auto-deploy.sh').read_text()
    check=script[script.index('listing="$dump.list"'):script.index('# 4b.')]
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


@pytest.mark.skipif(os.name == 'nt', reason='Production deploy runs Bash on Linux')
def test_installed_deployer_protocol_probe_is_read_only_and_required_before_release():
    script=Path('ops/auto-deploy.sh').resolve()
    env={**os.environ,'SSH_ORIGINAL_COMMAND':'lofi-deploy-protocol'}
    result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
    assert result.returncode==0
    assert result.stdout.strip()=='LOFI_DEPLOY_PROTOCOL=2'

    workflow=Path('.github/workflows/deploy.yml').read_text()
    assert 'name: Verify installed deployer protocol' in workflow
    assert workflow.index('name: Verify installed deployer protocol') < workflow.index('name: Deploy (waits while production is busy)')
    assert 'no release archive was sent.' in workflow


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


@pytest.mark.parametrize('mode,revision,requirements,expected', [
    ('', 'correct', 'different', 3),
    ('', 'correct', 'same', 0),
    ('full', 'correct', 'same', 0),
    ('full', 'wrong', 'same', 3),
    ('full', 'correct', 'different', 3),
    ('wrong-name', 'correct', 'same', 3),
])
def test_full_image_requires_matching_revision_and_requirements(tmp_path,mode,revision,requirements,expected):
    script=Path('ops/auto-deploy.sh').read_text()
    gate=script[script.index('full_image=${'):script.index('# Transmitter code')]
    (tmp_path/'requirements.txt').write_text('verified requirements\n')
    stub='''set -euo pipefail
fail() { exit "$2"; }
FULL_SHA=0123456789012345678901234567890123456789
SHA=0123456
current=previous-image
R="$TEST_RELEASE"
docker() {
  if [ "$1" = inspect ]; then
    if [ "$TEST_REVISION" = correct ]; then echo "$FULL_SHA"; else echo other; fi
  else
    [ "$5" = "$TEST_EXPECTED_IMAGE" ] || return 2
    if [ "$TEST_REQUIREMENTS" = same ]; then cat "$R/requirements.txt"; else echo different; fi
  fi
}
'''
    image={'full':'lofi-studio-os:full-0123456','wrong-name':'unrelated-image','':''}[mode]
    env={**os.environ,'LOFI_PREBUILT_IMAGE':image,'TEST_RELEASE':str(tmp_path),
         'TEST_REVISION':revision,'TEST_REQUIREMENTS':requirements,
         'TEST_EXPECTED_IMAGE':image or 'previous-image'}
    result=subprocess.run(['bash','-c',stub+gate],env=env,capture_output=True,text=True)
    assert result.returncode==expected, result.stderr


def test_full_deploy_builds_before_protected_activation():
    workflow=Path('.github/workflows/deploy-full.yml').read_text()
    build,deploy=workflow.split('  deploy:\n',1)
    assert 'environment:' not in build
    assert 'environment: production-bootstrap' in deploy
    assert 'needs: build' in deploy
    assert "github.ref == 'refs/heads/main'" in build
    assert 'event=push' in build and '$COMMIT success' in build
    assert 'docker build --build-arg "SOURCE_SHA=$sha"' in build
    assert 'python -m pip check' in build
    assert 'import langid,studio.api' in build
    assert 'actions/upload-artifact@v4' in build
    assert 'actions/download-artifact@v4' in deploy
    assert 'git/ref/heads/main' in deploy and 'sha256sum -c SHA256SUMS' in deploy
    assert 'LOFI_PREBUILT_IMAGE=' in deploy and 'bash ops/auto-deploy.sh < release.tar' in deploy
    assert 'VPS_BOOTSTRAP_KEY' in deploy
    assert 'docker compose' not in deploy  # Activation stays in the shared rollback-protected script.


def test_full_deploy_preflight_exits_before_image_or_service_changes():
    script=Path('ops/auto-deploy.sh').read_text()
    gate=script[script.index("busy=$(sql <<'EOF'"):script.index('\ncurrent=')]
    stub='''set -euo pipefail
sql() { cat >/dev/null; echo 0; }
say() { :; }
fail() { exit "$2"; }
'''
    env={**os.environ,'LOFI_DEPLOY_PREFLIGHT':'1'}
    result=subprocess.run(['bash','-c',stub+gate+'\nexit 99'],env=env,capture_output=True,text=True)
    assert result.returncode==0
