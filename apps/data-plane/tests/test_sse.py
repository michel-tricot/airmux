"""The shared SSE machine, tested where it lives: one fix here fixes every adapter.

The adapters' own suites prove integration over recorded provider logs; this file proves the
spec corners those providers never emit, so a provider that starts emitting them tomorrow
already works."""

from __future__ import annotations

import pytest

from data_plane.egress.base import RawEvent, StreamState, frame_sse


def fold(log: bytes, size: int) -> list[RawEvent]:
    state = StreamState()
    return [event for i in range(0, len(log), size) for event in frame_sse(log[i : i + size], state)]


def test_a_named_event_dispatches_on_the_blank_line():
    events = fold(b'event: message_start\ndata: {"a": 1}\n\n', 64)
    assert events == [RawEvent(data=b'{"a": 1}', name="message_start")]


def test_the_event_name_resets_after_dispatch():
    events = fold(b"event: one\ndata: x\n\ndata: y\n\n", 64)
    assert [(e.name, e.data) for e in events] == [("one", b"x"), (None, b"y")]


def test_multiple_data_lines_concatenate_with_newlines():
    events = fold(b"data: first\ndata: second\n\n", 64)
    assert events == [RawEvent(data=b"first\nsecond")]


def test_comment_lines_are_ignored():
    events = fold(b": keepalive\ndata: x\n: another\n\n", 64)
    assert events == [RawEvent(data=b"x")]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_every_terminating_line_ending_the_spec_allows(ending):
    log = ending.join([b"data: x", b"", b"data: y", b"", b""])
    assert [e.data for e in fold(log, 64)] == [b"x", b"y"]


def test_cr_only_lines_mid_stream():
    """CR-only endings work while the stream continues. Only a lone CR as the very last byte
    stays held, because without a next chunk the machine cannot know a newline never follows."""
    log = b"data: x\r\rdata: y\n\n"
    assert [e.data for e in fold(log, 3)] == [b"x", b"y"]


@pytest.mark.parametrize("size", [1, 2, 3, 7])
def test_a_crlf_split_across_chunks_is_one_line_break(size):
    """The trailing carriage return holds in the buffer until the next chunk says whether a
    newline follows; without that, one line break reads as two and events dispatch early."""
    log = b"data: first\r\ndata: second\r\n\r\n"
    assert fold(log, size) == fold(log, len(log))
    assert fold(log, size) == [RawEvent(data=b"first\nsecond")]


def test_an_event_does_not_dispatch_before_its_blank_line():
    state = StreamState()
    assert list(frame_sse(b"data: held\n", state)) == []
    assert list(frame_sse(b"\n", state)) == [RawEvent(data=b"held")]
