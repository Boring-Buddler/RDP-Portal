from unittest.mock import Mock

import pytest
import pywintypes

from shared import status_pipe


@pytest.mark.parametrize("reply", [b'{"ok":true}', b'{"ok":false,"message":"denied"}'])
def test_ack_disconnect_preserves_received_response(monkeypatch, reply):
    handle = Mock()
    monkeypatch.setattr(status_pipe, "_open_pipe", lambda *_: handle)
    write = Mock(side_effect=[None, pywintypes.error(233, "GetOverlappedResult", "pipe closed")])
    monkeypatch.setattr(status_pipe, "write_message", write)
    monkeypatch.setattr(status_pipe, "read_message", Mock(return_value=reply))
    result = status_pipe._exchange("REMOTE", b"LOGOFF/1")
    assert result == status_pipe.json.loads(reply)
    handle.Close.assert_called_once()
    assert write.call_count == 2


@pytest.mark.parametrize("failure", [pywintypes.error(233, "GetOverlappedResult", "pipe closed"),
                                     TimeoutError(), ValueError("invalid JSON")])
def test_lost_reply_is_uncertain_and_command_is_not_repeated(monkeypatch, failure):
    handle = Mock()
    monkeypatch.setattr(status_pipe, "_open_pipe", lambda *_: handle)
    write = Mock()
    monkeypatch.setattr(status_pipe, "write_message", write)
    monkeypatch.setattr(status_pipe, "read_message", Mock(side_effect=failure))
    with pytest.raises(status_pipe.AgentResponseLostError):
        status_pipe._exchange("REMOTE", b"LOGOFF/1")
    write.assert_called_once_with(handle, b"LOGOFF/1")
    handle.Close.assert_called_once()


def test_rejection_is_not_converted_to_an_uncertain_reply(monkeypatch):
    monkeypatch.setattr(status_pipe, "_exchange", Mock(return_value={"ok": False, "message": "denied"}))
    with pytest.raises(PermissionError, match="denied"):
        status_pipe.request_agent_logoff("REMOTE", 3, "user", "time", "user")


def test_failure_before_sending_is_not_reported_as_sent(monkeypatch):
    monkeypatch.setattr(status_pipe, "_open_pipe", Mock(side_effect=PermissionError("denied")))
    with pytest.raises(PermissionError):
        status_pipe._exchange("REMOTE", b"LOGOFF/1")
