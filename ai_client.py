"""DeepSeek AI 客户端，使用 OpenAI 兼容 SDK。"""

import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """调用 DeepSeek Chat Completions API。"""

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        self._model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """发送对话请求，返回助手回复文本。"""
        logger.info("调用 DeepSeek API，模型：%s", self._model)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=120,
        )
        return response.choices[0].message.content or ""
