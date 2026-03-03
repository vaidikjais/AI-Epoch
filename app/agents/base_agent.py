"""Base agent with LLM invocation, JSON parsing, retry logic, and prompt loading."""

from __future__ import annotations

import asyncio
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Union

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("agents.base")

_MAX_JSON_RETRIES = 2
_MAX_INVOKE_RETRIES = 2
_INVOKE_BACKOFF_SECS = [1, 2]
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=64)
def _read_prompt_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_prompt(agent_name: str, prompt_name: str, **kwargs: Any) -> str:
    """Load ``app/prompts/{agent_name}/{prompt_name}.txt``, optionally interpolating *kwargs*."""
    path = _PROMPTS_DIR / agent_name / f"{prompt_name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    template = _read_prompt_file(str(path))
    if kwargs:
        return template.format_map(kwargs)
    return template


class BaseAgent:
    """Base class for all LLM-powered pipeline agents."""

    def __init__(self, model: Optional[str] = None, temperature: float = 0.2, max_tokens: int = 8192):
        self._model = model or settings.CURATOR_AGENT_MODEL or settings.NVIDIA_MODEL
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client: Optional[ChatNVIDIA] = None

    @property
    def client(self) -> ChatNVIDIA:
        if self._client is None:
            api_key = getattr(settings, "NVIDIA_API_KEY", None)
            if not api_key or not api_key.strip():
                raise ValueError("NVIDIA_API_KEY is required for agent LLM calls.")
            self._client = ChatNVIDIA(
                model=self._model,
                api_key=api_key,
                temperature=self._temperature,
                top_p=0.8,
                max_tokens=self._max_tokens,
            )
            logger.info(f"Agent LLM client initialised: model={self._model}, temp={self._temperature}")
        return self._client

    async def _invoke(self, system_prompt: str, user_prompt: str) -> str:
        """Send [system, user] messages to the LLM with automatic retry on transient failures."""
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        loop = asyncio.get_running_loop()
        last_err: Exception | None = None

        for attempt in range(_MAX_INVOKE_RETRIES + 1):
            try:
                start = time.time()
                response = await loop.run_in_executor(None, self.client.invoke, messages)
                elapsed = time.time() - start
                text = response.content if hasattr(response, "content") else str(response)

                if not text or not text.strip():
                    for attr in ("reasoning_content", "thinking_content", "reasoning"):
                        alt = getattr(response, attr, None)
                        if alt and str(alt).strip():
                            text = str(alt)
                            break
                    if (not text or not text.strip()) and hasattr(response, "additional_kwargs"):
                        ak = response.additional_kwargs or {}
                        for key in ("reasoning_content", "thinking_content", "reasoning"):
                            if key in ak and ak[key]:
                                text = str(ak[key])
                                break

                if not text or not text.strip():
                    logger.warning(f"LLM returned empty content after {elapsed:.2f}s")

                logger.debug(f"LLM invoke completed in {elapsed:.2f}s ({len(text)} chars)")
                return text
            except Exception as exc:
                last_err = exc
                if attempt < _MAX_INVOKE_RETRIES:
                    wait = _INVOKE_BACKOFF_SECS[attempt]
                    logger.warning(f"LLM invoke attempt {attempt + 1} failed: {exc}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)

        raise last_err  # type: ignore[misc]

    async def _invoke_json(self, system_prompt: str, user_prompt: str) -> Union[dict, list]:
        """Invoke LLM, parse response as JSON. Retries with a repair prompt on failure."""
        last_raw = ""
        for attempt in range(1, _MAX_JSON_RETRIES + 2):
            if attempt == 1:
                raw = await self._invoke(system_prompt, user_prompt)
            else:
                repair_prompt = load_prompt("common", "json_repair", last_raw=last_raw, user_prompt=user_prompt)
                raw = await self._invoke(system_prompt, repair_prompt)

            last_raw = raw
            parsed = self._extract_json(raw)
            if parsed is not None:
                return parsed

            logger.warning(f"JSON parse attempt {attempt}/{_MAX_JSON_RETRIES + 1} failed. Raw: {raw[:300]}")

        raise ValueError(f"LLM returned unparseable JSON after {_MAX_JSON_RETRIES + 1} attempts. Last: {last_raw[:500]}")

    @staticmethod
    def _extract_json(text: str) -> Optional[Union[dict, list]]:
        """Extract a JSON object or array from *text*, handling markdown fences and prose."""
        text = text.strip()

        fence_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
        match = fence_pattern.search(text)
        if match:
            text = match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        attempts = []
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start_idx = text.find(start_char)
            if start_idx == -1:
                continue
            end_idx = text.rfind(end_char)
            if end_idx <= start_idx:
                continue
            attempts.append((start_idx, text[start_idx : end_idx + 1]))

        attempts.sort(key=lambda t: t[0])
        for _, candidate_text in attempts:
            try:
                return json.loads(candidate_text)
            except json.JSONDecodeError:
                continue

        return None
