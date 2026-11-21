"""Google Gemini native API (``models/{model}:generateContent``) with the key/proxy/model rotation of the base class.

The key travels only in the ``x-goog-api-key`` header, never in the URL, so it cannot leak through httpx error texts."""

from __future__ import annotations

import json

from app.ai.providers.base import JSON_INSTRUCTION, ChatResult, LLMError, LLMProvider, register_provider
from app.ai.proxy_scheme import resolve


def _contents(messages: list[dict]) -> tuple[list[dict], str]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    return contents, system


@register_provider
class GeminiProvider(LLMProvider):
    name = "gemini"

    def _url(self, path: str) -> str:
        return self.cfg.base_url.rstrip("/") + path

    def _headers(self, key: str | None) -> dict[str, str]:
        h = {"Content-Type": "application/json", **self.cfg.headers}
        if key:
            h["x-goog-api-key"] = key
        return h

    async def chat(self, messages, response_schema=None, temperature=0.2, max_tokens=2048, timeout=None,
                   validate=None):
        contents, system = _contents(messages)
        if response_schema is not None:
            instruction = JSON_INSTRUCTION.format(schema=json.dumps(response_schema, ensure_ascii=False))
            system = f"{system}\n\n{instruction}" if system else instruction
        gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if response_schema is not None:
            gen["responseMimeType"] = "application/json"
        body: dict = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        async def attempt(model: str, key: str | None, proxy: str | None) -> ChatResult:
            resp = await self._request("POST", self._url(f"/models/{model}:generateContent"), json_body=body,
                                       headers=self._headers(key), timeout=timeout, proxy=proxy, attempts=1)
            if resp.status_code != 200:
                try:
                    msg = str(resp.json().get("error", {}).get("message", ""))[:200]
                except ValueError:
                    msg = resp.text[:200]
                raise LLMError(f"Gemini вернул ошибку {resp.status_code}: {msg}".rstrip(": "))
            try:
                data = resp.json()
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError("ответ Gemini не соответствует формату generateContent") from exc
            if not text.strip():
                raise LLMError("Gemini вернул пустой ответ")
            meta = data.get("usageMetadata") or {}
            usage = {"prompt_tokens": int(meta.get("promptTokenCount") or 0),
                     "completion_tokens": int(meta.get("candidatesTokenCount") or 0),
                     "total_tokens": int(meta.get("totalTokenCount") or 0)}
            return ChatResult(content=text, model=model, usage=usage,
                              json_mode="object" if response_schema is not None else "none")

        return await self._rotate(attempt, validate)

    async def list_models(self) -> list[str]:
        key = self.cfg.keys[0] if self.cfg.keys else None
        proxy = None
        if self.cfg.proxies:
            proxy = await resolve(self.cfg.proxies[0], set())
        resp = await self._request("GET", self._url("/models"), headers=self._headers(key), proxy=proxy, attempts=1)
        if resp.status_code != 200:
            raise LLMError(f"список моделей Gemini недоступен: HTTP {resp.status_code}")
        return [str(m.get("name", "")).removeprefix("models/") for m in resp.json().get("models", []) if m.get("name")]
