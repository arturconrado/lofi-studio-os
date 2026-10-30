"""Choose encoder parallelism within the container's CPU and RAM limits."""
import os
from pathlib import Path


def encoder_threads():
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:
        cores = os.cpu_count() or 1
    # Production uses cgroup v2. Preserve the previous two-thread ceiling if
    # limits cannot be measured, rather than guessing the host's free memory.
    memory_ceiling = 2
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            cores = min(cores, max(1, int(quota) // int(period)))
        memory = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if memory != 'max' and int(memory) >= 1024**3:
            memory_ceiling = 4
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return max(1, min(4, cores, memory_ceiling))
