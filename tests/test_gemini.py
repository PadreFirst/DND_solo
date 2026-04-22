"""Tests for Gemini client — response parsing and error handling."""
from __future__ import annotations

import pytest

from bot.services.gemini import GeminiClient, _unwrap_json_string


class TestExtractText:
    def test_normal_response(self):
        data = {"candidates": [{"content": {"parts": [{"text": "hello"}]}, "finishReason": "STOP"}]}
        assert GeminiClient._extract_text(data) == "hello"

    def test_empty_candidates(self):
        data = {"candidates": []}
        with pytest.raises(ValueError, match="No candidates"):
            GeminiClient._extract_text(data)

    def test_no_candidates_key(self):
        data = {"error": "something"}
        with pytest.raises(ValueError, match="No candidates"):
            GeminiClient._extract_text(data)

    def test_safety_blocked(self):
        data = {"candidates": [{"finishReason": "SAFETY"}]}
        with pytest.raises(ValueError, match="safety filter"):
            GeminiClient._extract_text(data)

    def test_no_content(self):
        data = {"candidates": [{"finishReason": "STOP"}]}
        with pytest.raises(ValueError, match="No content"):
            GeminiClient._extract_text(data)

    def test_empty_parts(self):
        data = {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}
        with pytest.raises(ValueError, match="Empty parts"):
            GeminiClient._extract_text(data)


class TestUnwrapJsonString:
    def test_plain_text(self):
        assert _unwrap_json_string("hello world") == "hello world"

    def test_json_string(self):
        assert _unwrap_json_string('"hello world"') == "hello world"

    def test_json_with_newlines(self):
        result = _unwrap_json_string('"line1\\nline2"')
        assert result == "line1\nline2"

    def test_not_valid_json(self):
        assert _unwrap_json_string('"unclosed') == '"unclosed'

    def test_json_object_not_unwrapped(self):
        s = '{"key": "value"}'
        assert _unwrap_json_string(s) == s
