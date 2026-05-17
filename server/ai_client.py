import json
from typing import Any, Dict, List, Optional

try:
    import aiohttp
except ImportError: 
    aiohttp = None

from .config import get_setting


AI_ENDPOINT = "https://ai.hackclub.com/proxy/v1/chat/completions"


class AIClient:
    def __init__(self):
        self.api_key = get_setting("HACKCLUB_API_KEY")
        self.model = get_setting("HACKCLUB_MODEL", "qwen/qwen3-32b")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        timeout_seconds: float = 4.0,
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None
        if aiohttp is None:
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
        }
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(AI_ENDPOINT, headers=headers, json=payload) as response:
                    if response.status != 200:
                        return None
                    return await response.json()
        except Exception:
            return None
        
    async def chat_text(
            self,
            messages: List[Dict[str, str]],
            timeout_seconds: float = 4.0,
    ) -> Optional[str]:
        payload = await self.chat(messages, timeout_seconds=timeout_seconds)
        if not payload:
            return None
        try:
            return payload["choices"][0]["message"]["content"] //probs have to change in the future 
        except (KeyError, IndexError, TypeError):
            return None
        
    )
        
