import uuid
import pytest
from studio.workspace_workers import REQUIRED,worker_environment,compose_plan,write_private


def test_worker_environment_excludes_admin_and_email_credentials():
    wid=str(uuid.uuid4())
    source={name:'test-'+name for name in REQUIRED}
    source.update(OPENROUTER_API_KEY='admin-key',RESEND_API_KEY='admin-email',
                  STUDIO_ADMIN_PASSWORD='admin-password',STUDIO_SIGNUP_ENABLED='1',
                  LOFI_WORKSPACE_ID=str(uuid.uuid4()),LOFI_CONTINUOUS_ENABLED='1')
    result=worker_environment(source,wid)
    assert result['LOFI_WORKSPACE_ID']==wid
    assert set(result)==set(REQUIRED)|{'LOFI_WORKSPACE_ID','RADIO_CACHE','LOFI_AUDIO_ONLY','LOFI_CONTINUOUS_ENABLED'}
    assert result['LOFI_CONTINUOUS_ENABLED']=='0'
    with pytest.raises(ValueError):worker_environment({},wid)
    with pytest.raises(ValueError):worker_environment(source,'../../admin')


def test_worker_plan_has_unique_cache_bounded_resources_and_no_host_access():
    first=compose_plan(uuid.uuid4(),'lofi-studio-os:staging','lofi-staging_default')
    second=compose_plan(uuid.uuid4(),'lofi-studio-os:staging','lofi-staging_default')
    assert first['name']!=second['name']
    for service in first['services'].values():
        assert service['read_only'] and service['cap_drop']==['ALL']
        assert 'ports' not in service and 'privileged' not in service
        assert float(service['cpus'])<=0.20
        assert 'docker.sock' not in str(service)
    assert first['services']['export']['volumes']==['cache:/cache']
    with pytest.raises(ValueError):compose_plan(uuid.uuid4(),'bad image','valid')


def test_secret_files_restrict_permissions_and_refuse_symlinks(tmp_path):
    target=tmp_path/'workers.env';write_private(target,'SECRET=test\n')
    assert target.stat().st_mode&0o777==0o600
    target.chmod(0o644);write_private(target,'SECRET=updated\n')
    assert target.stat().st_mode&0o777==0o600
    link=tmp_path/'link';link.symlink_to(target)
    with pytest.raises(OSError):write_private(link,'bad')
    assert target.read_text()=='SECRET=updated\n'
