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
