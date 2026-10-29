"""Incremental think-tag filtering. Reasoning never becomes a final answer."""

from omnicore.text.types import TextChunk, TextError


class ThinkParser:
    def __init__(self, reasoning=False, fixed=False):
        self.reasoning, self.fixed = reasoning, fixed
        self.pending = ""

    def feed(self, text, *, final=False):
        self.pending += text
        answer, reasoning = [], []
        while self.pending:
            tag = next(
                (tag for tag in ("<think>", "</think>") if self.pending.startswith(tag)), None
            )
            if tag:
                if not self.fixed:
                    self.reasoning = tag == "<think>"
                self.pending = self.pending[len(tag) :]
                continue
            if any(tag.startswith(self.pending) for tag in ("<think>", "</think>")):
                if final:
                    # Drop incomplete markers, but preserve a literal comparison character.
                    if self.pending == "<":
                        (reasoning if self.reasoning else answer).append("<")
                    self.pending = ""
                break
            next_tag = self.pending.find("<", 1)
            length = next_tag if next_tag >= 0 else len(self.pending)
            # A normal prefix followed by a partial marker must wait for the next chunk.
            part = self.pending[:length]
            (reasoning if self.reasoning else answer).append(part)
            self.pending = self.pending[length:]
        return "".join(answer), "".join(reasoning)


async def normalize_stream(source):
    content = ThinkParser()
    reasoning = ThinkParser(reasoning=True, fixed=True)
    async for chunk in source:
        answer, thought = content.feed(chunk.content)
        _, separate = reasoning.feed(chunk.reasoning_content)
        yield chunk.model_copy(update={"content": answer, "reasoning_content": thought + separate})
    answer, thought = content.feed("", final=True)
    _, separate = reasoning.feed("", final=True)
    if answer or thought or separate:
        yield TextChunk(content=answer, reasoning_content=thought + separate)


async def sse_data(response):
    """SSE data lines form one event; comments and metadata are not JSON payloads."""
    data, size = [], 0
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield "\n".join(data)
            data, size = [], 0
        elif line.startswith("data:"):
            value = line[5:].removeprefix(" ")
            size += len(value)
            if size > 2_000_000:
                raise TextError("engine_invalid_response", 502)
            data.append(value)
    if data:
        yield "\n".join(data)
