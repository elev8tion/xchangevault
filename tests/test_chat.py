import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import chat


def test_estimate_tokens():
    text = "Hello world this is a test"
    tokens = chat.estimate_tokens(text)
    assert tokens > 0
    assert isinstance(tokens, int)


def test_truncate_to_tokens():
    long_text = "word " * 10000
    truncated = chat.truncate_to_tokens(long_text, 100)
    assert len(truncated) < len(long_text)
    assert chat.estimate_tokens(truncated) <= 150  # allow some margin


def test_build_extractor_context_no_plan():
    ctx = chat.build_extractor_context("help me")
    assert "REQUEST: help me" in ctx
    assert "INSTRUCTIONS" in ctx


def test_save_and_load_history(tmp_path):
    with patch.object(chat, "HISTORY_DIR", tmp_path):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        chat.save_history("proj1", msgs)
        loaded = chat.load_history("proj1")
        assert loaded == msgs


def test_clear_history_removes_disk(tmp_path):
    with patch.object(chat, "HISTORY_DIR", tmp_path):
        chat.save_history("proj2", [{"role": "user", "content": "test"}])
        pid_file = tmp_path / f"{chat._sanitize_pid('proj2')}.json"
        assert pid_file.exists()
        chat.PROJECT_HISTORIES["proj2"] = [{"role": "user", "content": "test"}]
        chat.clear_history("proj2")
        loaded = chat.load_history("proj2")
        assert loaded == []


def test_get_history_loads_from_disk(tmp_path):
    with patch.object(chat, "HISTORY_DIR", tmp_path):
        msgs = [{"role": "user", "content": "persisted"}]
        chat.save_history("proj3", msgs)
        # Clear in-memory
        chat.PROJECT_HISTORIES.pop("proj3", None)
        h = chat.get_history("proj3")
        assert h == msgs
