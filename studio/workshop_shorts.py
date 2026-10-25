"""Short-form story contract and portrait render for the Visual Workshop.

The source clips and soundtrack remain content-addressed in the existing project.
This module only composes a derived file for the existing human review flow.
"""
import hashlib
import json
import math
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import Field, model_validator

from .visual_workshop import Strict


class ShortSegment(Strict):
    clip_id: str = Field(pattern=r'^[0-9a-fA-F-]{36}$')
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    occurrence_minute: float = Field(ge=0, le=1440)
    source_start_seconds: float = Field(default=0, ge=0, le=180)
    duration_seconds: float = Field(ge=2, le=180)
    beat: Literal['opening', 'turn', 'resolution']


class ShortCaption(Strict):
    start_seconds: float = Field(ge=0, le=180)
    end_seconds: float = Field(gt=0, le=180)
    text: str = Field(min_length=1, max_length=90)
    position: Literal['top', 'bottom'] = 'top'


class ShortSpec(Strict):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=5000)
    story_title: str = Field(min_length=1, max_length=120)
    story_summary: str = Field(min_length=20, max_length=1200)
    parent_video_id: str = Field(pattern=r'^[A-Za-z0-9_-]{11}$')
    audio_start_seconds: float = Field(ge=0, le=86400)
    segments: list[ShortSegment] = Field(min_length=2, max_length=8)
    captions: list[ShortCaption] = Field(min_length=1, max_length=12)

    @model_validator(mode='after')
    def complete_story_and_captions(self):
        beats = {segment.beat for segment in self.segments}
        if not {'opening', 'turn', 'resolution'} <= beats:
            raise ValueError('Inclua abertura, virada e resolução nos movimentos escolhidos')
        duration = sum(segment.duration_seconds for segment in self.segments)
        if duration > 180:
            raise ValueError('O perfil atual de Shorts aceita até 3 minutos')
        previous_end = -1
        for caption in self.captions:
            if caption.end_seconds <= caption.start_seconds or caption.end_seconds > duration:
                raise ValueError('Cada legenda precisa estar dentro da duração da história')
            if caption.start_seconds < previous_end:
                raise ValueError('As legendas não podem se sobrepor')
            previous_end = caption.end_seconds
        return self

    @property
    def seconds(self):
        return sum(segment.duration_seconds for segment in self.segments)

    def content_hash(self):
        return hashlib.sha256(json.dumps(self.model_dump(mode='json'), sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()


def _font(size):
    for candidate in (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/Library/Fonts/Arial Bold.ttf',
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _caption_image(caption, folder, index, width=1080, height=1920):
    image = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _font(45)
    words = caption['text'].split()
    lines = []
    current = ''
    for word in words:
        proposed = f'{current} {word}'.strip()
        if current and draw.textbbox((0, 0), proposed, font=font)[2] > width - 180:
            lines.append(current)
            current = word
        else:
            current = proposed
    if current:
        lines.append(current)
    if len(lines) > 2:
        lines = textwrap.wrap(caption['text'], width=30)[:2]
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_height = max((box[3] - box[1] for box in boxes), default=50)
    pad_x, pad_y, gap = 28, 18, 8
    box_width = min(width - 120, max((b[2] - b[0] for b in boxes), default=1) + 2 * pad_x)
    box_height = len(lines) * line_height + max(0, len(lines) - 1) * gap + 2 * pad_y
    # Store only the caption card, not a full 1080x1920 transparent frame. The
    # full-frame PNG inputs used to multiply several hundred MB of FFmpeg buffers
    # on the small production worker.
    image = Image.new('RGBA', (box_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, box_width, box_height), radius=24, fill=(12, 14, 22, 188))
    cursor_y = pad_y
    for line, bounds in zip(lines, boxes):
        text_width = bounds[2] - bounds[0]
        draw.text(((box_width - text_width) / 2, cursor_y), line, font=font, fill=(255, 250, 239, 255),
                  stroke_width=0)
        cursor_y += line_height + gap
    path = Path(folder) / f'caption-{index:02}.png'
    image.save(path)
    return path


def render_short(spec, sources, audio, audio_sha256, destination, folder):
    """Compose source motion in a synced blurred 9:16 canvas with timed captions."""
    from .timeline_compositor import file_hash, measure

    destination = Path(destination)
    folder = Path(folder)
    if destination.exists():
        raise ValueError('Output already exists')
    if file_hash(audio) != audio_sha256:
        raise ValueError('A trilha original mudou')
    audio_length, _ = measure(audio, 'audio')
    seconds = spec.seconds
    if spec.audio_start_seconds + seconds > audio_length + .01:
        raise ValueError('A trilha aprovada não cobre este trecho')
    required = math.ceil(seconds * 1080 * 1920 * 3 / 8 + 256 * 1024**2)
    if shutil.disk_usage(folder).free < required:
        raise ValueError('Espaço local insuficiente para compor o Short')

    args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '1', '-filter_complex_threads', '1']
    for segment in spec.segments:
        source = Path(sources[segment.clip_id])
        if file_hash(source) != segment.source_sha256:
            raise ValueError('Um movimento fonte mudou')
        length, _ = measure(source, 'video')
        if segment.source_start_seconds + segment.duration_seconds > length + .05:
            raise ValueError('O movimento fonte não contém o intervalo pedido')
        args += ['-i', str(source)]
    audio_index = len(spec.segments)
    args += ['-ss', str(spec.audio_start_seconds), '-t', str(seconds), '-i', str(audio)]
    caption_start = audio_index + 1
    caption_paths = [_caption_image(c.model_dump(), folder, i) for i, c in enumerate(spec.captions)]
    for path in caption_paths:
        args += ['-loop', '1', '-framerate', '30', '-i', str(path)]

    filters = []
    clip_labels = []
    cursor = 0.0
    for i, segment in enumerate(spec.segments):
        source_index = i
        start = segment.source_start_seconds
        length = segment.duration_seconds
        filters.extend([
            f'[{source_index}:v]trim=start={start}:duration={length},setpts=PTS-STARTPTS,fps=30,split=2[bg{i}][fg{i}]',
            f'[bg{i}]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:12,eq=brightness=-0.16[back{i}]',
            f'[fg{i}]scale=1080:1920:force_original_aspect_ratio=decrease[front{i}]',
            f'[back{i}][front{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[clip{i}]',
        ])
        clip_labels.append(f'[clip{i}]')
        cursor += length
    if len(clip_labels) == 1:
        filters.append(f'{clip_labels[0]}null[story]')
    else:
        filters.append(''.join(clip_labels) + f'concat=n={len(clip_labels)}:v=1:a=0[story]')
    current = 'story'
    for i, caption in enumerate(spec.captions):
        label = f'captioned{i}'
        idx = caption_start + i
        y = '370' if caption.position == 'top' else 'H-h-450'
        filters.append(f'[{current}][{idx}:v]overlay=x=(W-w)/2:y={y}:enable=\'between(t,{caption.start_seconds},{caption.end_seconds})\':eof_action=pass:repeatlast=0[{label}]')
        current = label
    final_label = 'shortout'
    filters.append(f'[{current}]format=yuv420p[{final_label}]')
    fade_out = max(0, seconds - .8)
    audio_filter = f'afade=t=in:st=0:d=0.25,afade=t=out:st={fade_out}:d=0.8,atrim=duration={seconds},asetpts=PTS-STARTPTS'
    args += ['-filter_complex', ';'.join(filters), '-map', f'[{final_label}]', '-map', f'{audio_index}:a:0',
             '-t', str(seconds), '-af', audio_filter, '-c:v', 'libx264', '-threads:v', '1',
             '-preset', 'veryfast', '-crf', '19',
             '-pix_fmt', 'yuv420p', '-r', '30', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
             '-movflags', '+faststart', str(destination)]
    subprocess.run(args, check=True, timeout=max(180, int(seconds * 15)),
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    actual, video_info = measure(destination, 'video')
    audio_seconds, _ = measure(destination, 'audio')
    if abs(actual - seconds) > .15 or abs(audio_seconds - seconds) > .15:
        raise ValueError('Duração de áudio ou vídeo diferente do roteiro')
    if (int(video_info['width']), int(video_info['height'])) != (1080, 1920):
        raise ValueError('Perfil vertical incorreto')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(destination), '-f', 'null', '-'],
                   check=True, timeout=max(90, int(seconds * 6)), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return {'sha256': file_hash(destination), 'seconds': actual, 'audio_seconds': audio_seconds,
            'width': 1080, 'height': 1920, 'fps': 30, 'profile': 'youtube_shorts_9x16',
            'composition': 'same-frame-blurred-background', 'captions': [c.model_dump(mode='json') for c in spec.captions],
            'segments': [{'clip_id': s.clip_id, 'source_sha256': s.source_sha256,
                          'source_start_seconds': s.source_start_seconds,
                          'duration_seconds': s.duration_seconds, 'beat': s.beat}
                         for s in spec.segments], 'audio_sha256': audio_sha256,
            'full_decode_pass': True, 'final_review_required': True}
