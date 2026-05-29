"""配置加载：从 .env 文件或环境变量读取。"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()  # 优先加载当前目录的 .env


@dataclass
class Config:
    deepseek_api_key: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    deepseek_model: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))
    pubmed_api_key: str = field(default_factory=lambda: os.environ.get("PUBMED_API_KEY", ""))
    pubmed_email: str = field(default_factory=lambda: os.environ.get("PUBMED_EMAIL", ""))
    output_dir: str = field(default_factory=lambda: os.environ.get("OUTPUT_DIR", ""))
    # 将解说词拆分为几个短视频片段（每段约 80-130 字，对应 15-30 秒）
    # 设为 1 则生成完整长文（450-650 字）
    digest_segments: int = field(default_factory=lambda: int(os.environ.get("DIGEST_SEGMENTS", "1")))

    def validate(self) -> None:
        if not self.deepseek_api_key:
            raise ValueError("未设置 DEEPSEEK_API_KEY，请在 .env 文件或环境变量中配置")
        if not self.pubmed_email:
            raise ValueError("未设置 PUBMED_EMAIL，NCBI 要求提供联系邮箱（不用注册，任意邮箱即可）")
