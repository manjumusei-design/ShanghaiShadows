import json
import logging
from typing import Any, Dict, List, Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None

from .config import get_setting


logger = logging.getLogger(__name__)

AI_ENDPOINT = "https://ai.hackclub.com/proxy/v1/chat/completions"


class AIClient:
    def __init__(self):
        self.api_key = get_setting("HACKCLUB_API_KEY")
        self.model = get_setting("HACKCLUB_MODEL", "qwen/qwen3-32b")
        self._failure_warned = False

    def _warn_once(self, detail: str) -> None:
        if self._failure_warned:
            return
        self._failure_warned = True
        logger.warning(
            "AI request failed (%s); falling back to local text generation for model %s",
            detail,
            self.model,
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        timeout_seconds: float = 4.0,
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            logger.info("AI request skipped reason=missing_api_key model=%s", self.model)
            return None
        if aiohttp is None:
            logger.info("AI request skipped reason=aiohttp_unavailable model=%s", self.model)
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
        }
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        try:
            logger.info(
                "AI request sent endpoint=%s model=%s timeout_seconds=%s",
                AI_ENDPOINT,
                self.model,
                timeout_seconds,
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(AI_ENDPOINT, headers=headers, json=payload) as response:
                    if response.status != 200:
                        self._warn_once(f"http status {response.status}")
                        return None
                    logger.info(
                        "AI response received endpoint=%s model=%s status=%s",
                        AI_ENDPOINT,
                        self.model,
                        response.status,
                    )
                    return await response.json()
        except Exception as error:
            self._warn_once(f"{type(error).__name__}: {error}")
            return None

    async def chat_text(
        self,
        messages: List[Dict[str, str]],
        timeout_seconds: float = 4.0,
    ) -> Optional[str]:
        payload = await self.chat(messages, timeout_seconds=timeout_seconds)
        if not payload:
            logger.info("AI text response unavailable reason=no_payload")
            return None
        try:
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                logger.info("AI text response rejected reason=empty_content")
                return None
            logger.info("AI text response accepted response_chars=%s", len(content))
            return content
        except (KeyError, IndexError, TypeError):
            logger.info("AI text response rejected reason=invalid_shape")
            return None

    async def chat_json(self,messages: List[Dict[str, str]],timeout_seconds: float = 4.0,) -> Optional[Dict[str, Any]]:
        content = await self.chat_text(messages, timeout_seconds=timeout_seconds)
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
