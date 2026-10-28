from pathlib import Path
import json
base=Path('/cache').resolve();freed=0;removed=0
for name in ('continuity-test-v2-20261023','continuity-test-20261023','validation45-20261023'):
 folder=(base/name/'render').resolve()
 assert folder.is_relative_to(base) and folder.parent.name==name
 # Preserve every final output, source clip, report, soundtrack and configuration.
 for f in folder.glob('chunk-*.mp4'):
  assert f.resolve().parent==folder and f.is_file() and not f.is_symlink()
  freed+=f.stat().st_size;f.unlink();removed+=1
print(json.dumps({'temporary_chunks_removed':removed,'bytes_freed':freed}))
