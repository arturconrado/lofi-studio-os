"""Viewer-facing copy: written for the person listening, not about how the session was made.

Descriptions keep to what the viewer gets (mood, scene, when to listen, chapters) and never
claim anything untrue about authorship. Paragraphs describing tooling or providers are
production notes; they stay in the platform's records, not on the video page.
"""
import re

PROCESS = re.compile(r'\b(AI|A\.I\.|artificial intelligence|generated|generative|Lyria|OpenRouter|Seedream|Veo|Gemini|prompt|model)\b', re.I)
LABELS = re.compile(r'^\s*(TITLE|DESCRIPTION|TRACKLIST)\s*$', re.I)
HASHTAGS = '#lofi #codingmusic #studymusic'


def organic(text, title=None):
    """Drop production-process paragraphs and stray template labels; keep everything else."""
    text = (text or '').replace('\r\n', '\n')
    lines = text.split('\n')
    if lines and LABELS.match(lines[0]):  # "TITLE\n<title>\n\nDESCRIPTION\n..." pasted from a draft
        lines = [l for l in lines if not LABELS.match(l) and l.strip() != (title or '').strip()]
    paragraphs = [p.strip() for p in '\n'.join(lines).split('\n\n')]
    kept = [p for p in paragraphs if p and not PROCESS.search(p)]
    return '\n\n'.join(kept).strip()


def chapter(line):
    """'02:14 Rain Between Pages · 031 (continued)' -> '02:14 Rain Between Pages'."""
    line = re.sub(r'\s*\(continued\)\s*$', '', line.strip())
    return re.sub(r'\s*·\s*\d+\s*$', '', line)


DEFAULT_TEMPLATE = ('Settle in at {scene_title} for {hours_label} of {style_title}: slow beats and warm melodies '
                    'to keep you company while you code, study or read.\n\n{idea}\n\n'
                    'Headphones on, notifications off. Leave it on loop for longer sessions.\n\n'
                    'What are you working on today? Tell us in the comments 👇\n'
                    'Subscribe for more cozy focus sessions.\n\n{hashtags}')
OLD_TEMPLATE = 'Original instrumental {style_title} for coding, studying and deep focus, set in {scene_title}.\n\n{idea}\n\n{hashtags}'
