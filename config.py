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
    # 每次从 PubMed 最多抓取的论文篇数（默认 30）
    pubmed_max_results: int = field(default_factory=lambda: int(os.environ.get("PUBMED_MAX_RESULTS", "30")))
    # 生成哪些平台的脚本：all 或逗号分隔的平台列表（douyin、shipinghao、xiaohongshu）
    platforms: str = field(default_factory=lambda: os.environ.get("PLATFORMS", "all"))
    # 各平台 AITDA 脚本总字数（AITDA 各段按比例自动计算：钩子10%/兴趣25%/信任31%/欲望25%/行动~9%）
    douyin_words: int = field(default_factory=lambda: int(os.environ.get("DOUYIN_WORDS", "240")))
    shipinghao_words: int = field(default_factory=lambda: int(os.environ.get("SHIPINGHAO_WORDS", "300")))
    xiaohongshu_words: int = field(default_factory=lambda: int(os.environ.get("XIAOHONGSHU_WORDS", "210")))

    def validate(self) -> None:
        if not self.deepseek_api_key:
            raise ValueError("未设置 DEEPSEEK_API_KEY，请在 .env 文件或环境变量中配置")
        if not self.pubmed_email:
            raise ValueError("未设置 PUBMED_EMAIL，NCBI 要求提供联系邮箱（不用注册，任意邮箱即可）")
