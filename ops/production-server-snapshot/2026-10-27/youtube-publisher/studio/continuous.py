"""One encoder session fed by independent, bounded block decoders.

Raw inputs let the session encoder own timestamps across block boundaries.
No destination or paid generation is selected by this module.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import time
from .stream_diagnostics import monitor

@dataclass(frozen=True)
class Block:
    id: str
    video: Path
    audio: Path
    seconds: float

    def validate(self):
        if not self.id or not 0 < self.seconds <= 86400:
            raise ValueError('Invalid block duration or identity')
        if not self.video.is_file() or not self.audio.is_file():
            raise ValueError('Block media unavailable')

class ContinuousSession:
    """Decoder changes never replace the encoder or its destination connection."""
    def __init__(self, destination, width=1280, height=720, fps=30, realtime=True):
        if width <= 0 or height <= 0 or width % 2 or height % 2 or not 1 <= fps <= 60:
            raise ValueError('Invalid encoding profile')
        self.destination = str(destination)
        self.width, self.height, self.fps = width, height, fps
        self.realtime = realtime
        self.transitions = []
        self.encoder_pid = None

    def run(self, next_block, cancelled=lambda: False, on_block=lambda block: None):
        """next_block resolves only future content; None explicitly ends the session.

        Files must be immutable and approved by the caller. Missing files fail
        before playback; the caller can choose approved reserve content instead.
        """
        video_read, video_write = os.pipe()
        audio_read, audio_write = os.pipe()
        encoder = decoder = None
        vr, ar = f'pipe:{video_read}', f'pipe:{audio_read}'
        args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
        if self.realtime: args += ['-re']
        # Raw inputs are fully described: no probing. Probing the video pipe first used to block
        # while the decoder filled the audio pipe (Linux 64 KiB) and waited: a two-process deadlock.
        raw = ['-probesize', '32', '-analyzeduration', '0', '-thread_queue_size', '1024']
        args += raw + ['-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', f'{self.width}x{self.height}',
                 '-r', str(self.fps), '-i', vr]
        if self.realtime: args += ['-re']
        args += raw + ['-f', 's16le', '-ar', '48000', '-ac', '2', '-i', ar,
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264',
                 '-preset', 'veryfast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
                 '-g', str(self.fps * 2), '-c:a', 'aac', '-b:a', '192k',
                 '-f', 'flv']
        if self.destination.startswith('rtmps://'):args += ['-tls_verify','1','-rw_timeout','15000000']
        args += [self.destination]
        try:
            encoder = subprocess.Popen(args, pass_fds=(video_read, audio_read),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.encoder_pid = encoder.pid
            et, errors = monitor(encoder.stderr)
            os.close(video_read); video_read = None
            os.close(audio_read); audio_read = None
            while not cancelled():
                block = next_block()
                if block is None: break
                block.validate()
                # Integer video frames and exact corresponding audio samples.
                frames = max(1, round(block.seconds * self.fps))
                seconds = frames / self.fps
                self.transitions.append({'block_id': block.id, 'encoder_pid': encoder.pid,
                                         'frames': frames, 'seconds': seconds})
                on_block(block)
                command = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                    '-stream_loop', '-1', '-i', str(block.video),
                    '-stream_loop', '-1', '-i', str(block.audio),
                    '-map', '0:v:0', '-vf', f'scale={self.width}:{self.height},fps={self.fps}',
                    '-frames:v', str(frames), '-pix_fmt', 'yuv420p', '-f', 'rawvideo',
                    f'pipe:{video_write}', '-map', '1:a:0', '-t', str(seconds),
                    '-af', 'aresample=48000', '-ar', '48000', '-ac', '2',
                    '-c:a', 'pcm_s16le', '-f', 's16le', f'pipe:{audio_write}']
                decoder = subprocess.Popen(command, pass_fds=(video_write, audio_write),
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                dt, diagnostics = monitor(decoder.stderr)
                deadline=time.monotonic()+max(60,seconds*2)
                while decoder.poll() is None:
                    if time.monotonic()>deadline:raise RuntimeError('Block decoder timeout')
                    if cancelled(): break
                    if encoder.poll() is not None:
                        raise RuntimeError('Encoder interrupted')
                    time.sleep(.02)
                if cancelled():
                    self._stop(decoder)
                    break
                dt.join(timeout=2)
                if decoder.returncode:
                    raise RuntimeError('Block decoder failed')
                decoder.stderr.close(); decoder = None
            os.close(video_write); video_write = None
            os.close(audio_write); audio_write = None
            try: encoder.wait(timeout=30)
            except subprocess.TimeoutExpired: raise RuntimeError('Encoder drain timeout')
            et.join(timeout=2)
            if encoder.returncode and not cancelled():
                raise RuntimeError('Encoder failed to finalize session')
            return self.transitions
        finally:
            if decoder is not None:
                self._stop(decoder)
                decoder.stderr.close()
            for fd in (video_read, audio_read, video_write, audio_write):
                if fd is not None: os.close(fd)
            if encoder is not None:
                self._stop(encoder)
                encoder.stderr.close()

    @staticmethod
    def _stop(process):
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
