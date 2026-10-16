"""A normal-speed window of the exact full-program plan, not a separate study."""
from copy import deepcopy


def window(compiled, assembly, start, seconds=10):
    if seconds!=10 or start<0 or start+seconds>compiled['duration_seconds']:
        raise ValueError('Preview outside program')
    segments=[]
    for original in assembly['segments']:
        left=max(start,original['start']);right=min(start+seconds,original['end'])
        if right<=left:continue
        segment=deepcopy(original)
        segment.update(start=left-start,end=right-start,
                       source_offset_seconds=left-original['start'])
        segments.append(segment)
    if not segments or any(not s.get('asset_sha256') for s in segments):
        raise ValueError('Reviewed clips missing for this preview window')
    spec=deepcopy(compiled)
    spec.update(duration_seconds=seconds,clock_offset_seconds=start,audio_offset_seconds=start,
                preview_only=True,parent_duration_seconds=compiled['duration_seconds'])
    result=deepcopy(assembly)
    result.update(segments=segments,duration_seconds=seconds,planned_timeline_seconds=seconds,
                  assets_ready=True,render_started=False,eligible_for_live=False)
    return spec,result
