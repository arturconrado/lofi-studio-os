"""Bounded, secret-safe encoder messages. Never log process arguments."""
import re
from collections import deque
from threading import Thread

def sanitize(line,secret=''):
 line=line.replace(secret,'[redacted]') if secret else line
 line=re.sub(r'(?i)rtmps?://[^\s\]\)]+','[stream endpoint]',line)
 line=re.sub(r'(?i)(authorization|api[_-]?key|token|password)\s*[:=]\s*\S+',r'\1=[redacted]',line)
 return ''.join(c for c in line if c.isprintable() or c==' ').strip()[:240]

def monitor(pipe,secret=''):
 lines=deque(maxlen=4)
 def read():
  try:
   for raw in iter(pipe.readline,b''):
    text=sanitize(raw.decode(errors='replace'),secret)
    if text:lines.append(text)
  except (ValueError,OSError):pass
 thread=Thread(target=read,daemon=True);thread.start();return thread,lines
