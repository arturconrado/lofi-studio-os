"""Shared acceptance contract. Technical evidence never replaces artistic review.

Run: python -m studio.video_guardrails video.mp4 --target-seconds 28800
A failed report is a deliverable, never an instruction to retry a paid provider.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

VERSION = 1


def assess(evidence, target_seconds):
    failures = []
    def require(condition, code):
        if not condition:
            failures.append(code)
    require(target_seconds > 0, 'invalid_target')
    require(evidence.get('demo_only') is False, 'demo_or_unclassified')
    require(evidence.get('duration_seconds', 0) >= target_seconds, 'visual_duration_short')
    require(evidence.get('timeline_coverage_seconds', 0) >= target_seconds, 'temporal_coverage_short')
    require(evidence.get('full_decode_pass') is True, 'decode_unverified')
    require(len(evidence.get('sha256', '')) == 64, 'artifact_unbound')
    require(evidence.get('source_preserved') is True, 'source_preservation_unverified')
    require(evidence.get('continuous_transitions_reviewed') is True, 'transitions_unreviewed')
    require(evidence.get('perceptible_motion_reviewed') is True, 'motion_unreviewed')
    require(evidence.get('time_progression_reviewed') is True, 'time_progression_unreviewed')
    require(evidence.get('human_review_sha256') == evidence.get('sha256') and bool(evidence.get('reviewer')), 'human_review_unbound')
    return {'contract_version': VERSION, 'target_seconds': target_seconds,
            'eligible_for_long_live': not failures, 'failures': failures,
            'evidence': evidence, 'automatic_paid_retry': False}


def inspect(path):
    """Measure actual output; never infer visual coverage from the audio duration."""
    path = Path(path)
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)]))
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    decode = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path),
                             '-map', '0:v:0', '-f', 'null', '-'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return {'sha256': digest.hexdigest(), 'duration_seconds': float(video.get('duration', 0)),
            'width': video['width'], 'height': video['height'],
            'fps': video['avg_frame_rate'], 'full_decode_pass': decode.returncode == 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--target-seconds', type=float, required=True)
    parser.add_argument('--evidence', help='Timeline and human review evidence JSON')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    evidence = json.loads(Path(args.evidence).read_text()) if args.evidence else {}
    # A review is valid only for the exact file inspected. Measured values win.
    evidence.update(inspect(args.video))
    report = assess(evidence, args.target_seconds)
    Path(args.output).write_text(json.dumps(report, indent=2))
    raise SystemExit(0 if report['eligible_for_long_live'] else 2)


if __name__ == '__main__':
    main()
