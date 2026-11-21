"""OpenAI-compatible chat completions (OpenRouter, Gemini OpenAI endpoint, vLLM, LM Studio, llama.cpp server…)."""

from __future__ import annotations

import json

from app.ai.pool import NEMOTRON_LIGHTNING
from app.ai.providers.base import JSON_INSTRUCTION, ChatResult, LLMError, LLMProvider, register_provider


def _with_instruction(messages: list[dict], schema: dict) -> list[dict]:
    instruction = JSON_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False))
    if messages and messages[0]["role"] == "system":
        return [{"role": "system", "content": messages[0]["content"] + "\n\n" + instruction}, *messages[1:]]
    return [{"role": "system", "content": instruction}, *messages]


@register_provider
class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def _url(self, path: str) -> str:
        return self.cfg.base_url.rstrip("/") + path

    async def chat(self, messages, response_schema=None, temperature=0.2, max_tokens=2048, timeout=None,
                   validate=None):
        if not self.cfg.pooled:
            return await self._chat_once(self.cfg.model, self.cfg.api_key, None, messages, response_schema,
                                         temperature, max_tokens, timeout, attempts=None)

        async def attempt(model, key, proxy):
            return await self._chat_once(model, key, proxy, messages, response_schema, temperature, max_tokens,
                                         timeout, attempts=1)
        return await self._rotate(attempt, validate)

    def _headers(self, key: str | None) -> dict[str, str]:
        h = {"Content-Type": "application/json", **self.cfg.headers}
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    async def _chat_once(self, model, key, proxy, messages, response_schema, temperature, max_tokens, timeout,
                         attempts):
        modes = ["none"]
        if response_schema is not None:
            pref = self.cfg.json_mode
            modes = {"auto": ["schema", "object", "instruction"], "schema": ["schema", "instruction"],
                     "object": ["object", "instruction"], "instruction": ["instruction"]}.get(pref, ["instruction"])
        last_error = ""
        unsupported = False
        for mode in modes:
            if unsupported and mode != "instruction":
                continue
            body: dict = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                          "messages": messages}
            if model == NEMOTRON_LIGHTNING and response_schema is not None:
                # Even the 20-token connection probe needs its full budget for visible JSON.
                body["chat_template_kwargs"] = {"enable_thinking": False}
            if mode == "schema":
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "aisw_response", "schema": response_schema,
                                                           "strict": False}}
            elif mode == "object":
                body["response_format"] = {"type": "json_object"}
                body["messages"] = _with_instruction(messages, response_schema)
            elif mode == "instruction":
                body["messages"] = _with_instruction(messages, response_schema)
            resp = await self._request("POST", self._url("/chat/completions"), json_body=body,
                                       headers=self._headers(key), timeout=timeout, proxy=proxy, attempts=attempts)
            if resp.status_code == 400 and mode in ("schema", "object") and "response_format" in resp.text:
                last_error = resp.text[:200]
                unsupported = True  # server rejects response_format → instruction + parsing
                continue
            if resp.status_code != 200:
                raise LLMError(f"провайдер вернул HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"] or ""
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError("ответ провайдера не соответствует формату chat/completions") from exc
            usage = {k: int(v) for k, v in (data.get("usage") or {}).items() if isinstance(v, int)}
            return ChatResult(content=content, model=data.get("model") or model, usage=usage, json_mode=mode)
        raise LLMError(f"провайдер не принял ни один режим JSON: {last_error}")

    async def list_models(self) -> list[str]:
        resp = await self._request("GET", self._url("/models"), headers=self._auth_headers())
        if resp.status_code != 200:
            raise LLMError(f"список моделей недоступен: HTTP {resp.status_code}")
        return [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
