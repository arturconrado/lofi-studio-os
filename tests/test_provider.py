import base64
import json
import pytest
from studio import provider


def test_parse_message_audio():
    expected=b'RIFFabcdWAVE'
    message={'choices':[{'message':{'audio':{'data':base64.b64encode(expected).decode()}}}]}
    assert provider.collect_stream(['data: '+json.dumps(message),'data: [DONE]'])[0]==expected


def test_parse_data_uri():
    assert provider.decode_chunk('data:audio/mpeg;base64,'+base64.b64encode(b'ID3abcd').decode())==b'ID3abcd'


def test_reject_text_only():
    with pytest.raises(provider.PartialGenerationError):
        provider.collect_stream(['data: '+json.dumps({'choices':[{'message':{'content':'Hello'}}]}),'data: [DONE]'])


def test_paid_block(monkeypatch):
    monkeypatch.setattr(provider.runtime,'settings',lambda:{'enabled':False})
    monkeypatch.setattr(provider.runtime,'key',lambda:pytest.fail('Disabled generation must not access a key'))
    with pytest.raises(RuntimeError,match='desativada'):
        provider.generate('music','google/lyria-3-pro-preview')
