from __future__ import annotations

DOCUMENT_PARTS = {
    "openai_chat_completions": {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0="}},
    "anthropic": {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
    "openai_responses": {"type": "input_file", "file_data": "data:application/pdf;base64,JVBERi0="},
}
