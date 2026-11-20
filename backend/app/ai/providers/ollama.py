"""Native Ollama API (``/api/chat`` with ``format`` = JSON schema / ``json``)."""

from __future__ import annotations

from app.ai.providers.base import ChatResult, LLMError, LLMProvider, register_provider


@register_provider
class OllamaProvider(LLMProvider):
    name = "ollama"
    default_allow = {"localhost:11434", "127.0.0.1:11434", "ollama:11434"}

    def _url(self, path: str) -> str:
        return self.cfg.base_url.rstrip("/") + path

    async def chat(self, messages, response_schema=None, temperature=0.2, max_tokens=2048, timeout=None):
        body: dict = {"model": self.cfg.model, "messages": messages, "stream": False,
                      "options": {"temperature": temperature, "num_predict": max_tokens}}
        if response_schema is not None:
            body["format"] = response_schema if self.cfg.json_mode != "object" else "json"
        resp = await self._request("POST", self._url("/api/chat"), json_body=body, headers=self._auth_headers(),
                                   timeout=timeout)
        if resp.status_code != 200:
            raise LLMError(f"Ollama вернула HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError("ответ Ollama не соответствует формату /api/chat") from exc
        p, c = int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)
        return ChatResult(content=content, model=data.get("model") or self.cfg.model,
                          usage={"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c},
                          json_mode="schema" if isinstance(body.get("format"), dict) else body.get("format", "none"))

    async def list_models(self) -> list[str]:
        resp = await self._request("GET", self._url("/api/tags"), headers=self._auth_headers())
        if resp.status_code != 200:
            raise LLMError(f"список моделей Ollama недоступен: HTTP {resp.status_code}")
        return [m.get("name") for m in resp.json().get("models", []) if m.get("name")]
