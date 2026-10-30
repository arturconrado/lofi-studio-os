#!/usr/bin/env python3
"""Raise only the export worker's resources, without recreating its container.

Run by the reviewed GitHub workflow as root. Private Compose data stays on the
host. The same lock as auto-deploy protects the persistent configuration.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

COMPOSE = Path('/opt/lofi-studio-os-releases/d877875/compose.production-final.private.json')
CONTAINER = 'lofi-vibe-coding-export-worker-1'
PROJECT = 'lofi-vibe-coding'
CPU = 4
MEMORY = 4 * 1024**3
SWAP = 2 * MEMORY  # Docker counts RAM plus swap here; this is not reserved RAM.


def docker(*args):
    # Never relay Docker errors containing private Compose values to Actions.
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Docker operation failed; inspect it on the host')
    return result.stdout


def inspect():
    return json.loads(docker('inspect', CONTAINER))[0]


def identity(info):
    state = info['State']
    if not state['Running'] or state.get('Restarting'):
        raise RuntimeError('Export worker must already be running')
    return info['Id'], info['Image'], state['Pid'], state['StartedAt']


def target_runtime(info):
    h = info['HostConfig']
    return h['NanoCpus'] == CPU * 10**9 and h['Memory'] == MEMORY and h['MemorySwap'] == SWAP


def apply():
    before = inspect()
    before_identity = identity(before)
    labels = before['Config'].get('Labels', {})
    if labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.service') != 'export-worker':
        raise RuntimeError('Unexpected container identity')
    h = before['HostConfig']
    if h['NanoCpus'] not in (200_000_000, CPU * 10**9) or h['Memory'] not in (384 * 1024**2, 1024**3, MEMORY) or h['MemorySwap'] not in (768 * 1024**2, 2 * 1024**3, SWAP):
        raise RuntimeError('Unexpected resource configuration; review before changing')
    if h['CpuQuota'] or h['CpuPeriod'] or h['CpusetCpus']:
        raise RuntimeError('Conflicting CPU controls require review')
    if len(os.sched_getaffinity(0)) != CPU:
        raise RuntimeError('This policy is reviewed for the four-core production host')
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    # Account for the complete new limit plus 1 GiB for host/other-service growth.
    # Existing worker RAM is already counted as used: this is conservative.
    if not target_runtime(before) and available < MEMORY + 1024**3:
        raise RuntimeError('Insufficient host memory headroom')
    if not COMPOSE.is_file() or COMPOSE.is_symlink():
        raise RuntimeError('Unexpected Compose file')
    original = COMPOSE.read_bytes()
    config = json.loads(original)
    service = config['services']['export-worker']
    if any(key in service for key in ('cpu_quota', 'cpu_period', 'cpuset', 'deploy')):
        raise RuntimeError('Conflicting Compose resources require review')
    if str(service.get('cpus')) not in ('0.20', '0.2', '4', '4.0') or service.get('mem_limit') not in ('384m', '1g', '4g') or service.get('memswap_limit') not in (None, '2g', '8g'):
        raise RuntimeError('Unexpected persistent resource configuration')
    updated = copy.deepcopy(config)
    updated['services']['export-worker'].update(cpus='4.0', mem_limit='4g', memswap_limit='8g')
    if updated != config:
        metadata = COMPOSE.stat()
        descriptor, candidate_name = tempfile.mkstemp(prefix='.export-capacity-', suffix='.private.json', dir=COMPOSE.parent)
        candidate = Path(candidate_name)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
                stream.write((json.dumps(updated, indent=2) + '\n').encode())
                stream.flush()
                os.fsync(stream.fileno())
            docker('compose', '-p', PROJECT, '--project-directory', str(COMPOSE.parent), '-f', str(candidate), 'config', '--quiet')
            # Keep an exact private backup; never upload this file to GitHub.
            digest = hashlib.sha256(original).hexdigest()[:16]
            backup = COMPOSE.with_name(f'compose.pre-export-capacity-{digest}.private.json')
            if backup.exists():
                if backup.read_bytes() != original:
                    raise RuntimeError('Backup mismatch')
            else:
                with backup.open('xb') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
            if COMPOSE.read_bytes() != original:
                raise RuntimeError('Compose changed concurrently')
            candidate.replace(COMPOSE)
        finally:
            candidate.unlink(missing_ok=True)
    # Both are increases. Never roll back to a smaller RAM limit while a render
    # may be using the new capacity. A failed apply can be retried idempotently.
    if not target_runtime(before):
        docker('update', '--cpus', str(CPU), '--memory', str(MEMORY), '--memory-swap', str(SWAP), CONTAINER)
    after = inspect()
    if identity(after) != before_identity or not target_runtime(after):
        raise RuntimeError('Live resource verification failed; do not restart the worker')
    print(json.dumps({'service': 'export-worker', 'cpus': CPU, 'memory_bytes': MEMORY,
                      'container_restarted': False, 'persistent_configuration': True}))


if __name__ == '__main__':
    # No deployment, jobs, assets, database rows or other containers are changed.
    with open('/var/lock/lofi-auto-deploy.lock', 'a') as lock:
        for attempt in range(30):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == 29:
                    raise SystemExit('Deployment lock busy; retry the workflow later')
                time.sleep(2)
        apply()
