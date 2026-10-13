import os,sys,base64,pytest
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from studio.provider import decode_audio,generate

def test_parse_message_audio():
    expected=b'RIFFabcdWAVE';x={'choices':[{'message':{'audio':{'data':base64.b64encode(expected).decode()}}}]}
    assert decode_audio(x)==expected

def test_parse_content_audio_data_uri():
    expected=b'ID3abcd';x={'choices':[{'message':{'content':[{'type':'audio','audio':{'data':'data:audio/mpeg;base64,'+base64.b64encode(expected).decode()}}]}}]}
    assert decode_audio(x)==expected

def test_reject_text_only():
    with pytest.raises(ValueError):decode_audio({'choices':[{'message':{'content':'Hello'}}]})

def test_paid_block(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only');monkeypatch.setenv('PAID_GENERATION_ENABLED','false')
    with pytest.raises(RuntimeError,match='paga bloqueada'):generate('music','google/lyria-3-pro-preview')
