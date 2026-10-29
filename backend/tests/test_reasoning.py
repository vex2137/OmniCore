import asyncio
import json

import httpx
import pytest

from omnicore.text.engines import LlamaEngine
from omnicore.text.reasoning import ThinkParser
from omnicore.text.types import GenerationParameters


@pytest.mark.parametrize("model", ["LFM3-1.7B-Q8_0", "Qwen_Qwen3.5-4B-Q8_0"])
@pytest.mark.parametrize("split", range(1, 9))
def test_think_tags_split_at_any_token_boundary(model, split):
    # Model-labelled protocol regressions, not proof of weight compatibility.
    raw = "<think>The user asks for help.</think>Final answer."
    parser = ThinkParser()
    answer, thought = "", ""
    for start in range(0, len(raw), split):
        a, r = parser.feed(raw[start : start + split])
        answer += a
        thought += r
        assert "<think>" not in a and "</think>" not in a
    a, r = parser.feed("", final=True)
    answer += a
    thought += r
    assert answer == "Final answer." and thought == "The user asks for help."


@pytest.mark.parametrize("model", ["LFM3", "Qwen3.5"])
def test_reasoning_length_and_multiline_sse_preserve_usage_and_finish(model):
    def handler(request):
        body = json.loads(request.content)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["reasoning_effort"] == "none"
        return httpx.Response(
            200,
            content=(
                ': heartbeat\n\ndata: {"choices":\n'
                'data: [{"delta":{"content":"<thi"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"nk>The user asks..."}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"length"}],'
                '"usage":{"completion_tokens":300}}\n\ndata: [DONE]\n\n'
            ),
        )

    async def exercise():
        engine = LlamaEngine()
        engine.model = model
        engine.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://localhost"
        )
        try:
            chunks = [
                c async for c in engine.stream(model, [], GenerationParameters(max_tokens=300))
            ]
            assert "".join(c.content for c in chunks) == ""
            assert "".join(c.reasoning_content for c in chunks) == "The user asks..."
            assert chunks[-1].finish_reason == "length" and chunks[-1].output_tokens == 300
        finally:
            await engine.stop()

    asyncio.run(exercise())


def test_incomplete_marker_is_hidden_and_comparisons_remain_text():
    parser = ThinkParser()
    assert parser.feed("3 < 4") == ("3 < 4", "")
    assert parser.feed("<thin") == ("", "")
    assert parser.feed("", final=True) == ("", "")
