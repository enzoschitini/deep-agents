"""Modelo falso com streaming: reaproveita o roteiro do `ScriptedChat` mas emite tokens (`_stream`)."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from tests.fakes import ScriptedChat


class StreamingScriptedChat(ScriptedChat):
    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self._generate(messages, stop=stop).generations[0].message   # consome o roteiro como o _generate
        if reply.tool_calls:
            chunks = [
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(reply.tool_calls)
            ]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
        else:
            words = str(reply.content).split(" ")
            for i, w in enumerate(words):
                text = w + (" " if i < len(words) - 1 else "")
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
                if run_manager:
                    run_manager.on_llm_new_token(text, chunk=chunk)
                yield chunk
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="", chunk_position="last",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ))
