"""PubMed E-utilities 客户端，基于 Biopython Bio.Entrez。"""

import time
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from Bio import Entrez, Medline

logger = logging.getLogger(__name__)

# ── PubMed 检索式 ────────────────────────────────────────────────────────────
# 涵盖：免疫/自愈、营养、睡眠/运动/生活方式、心理健康、肠道菌群、衰老、慢性病预防
TOPICS_QUERY = """(
  immunity[MeSH Terms] OR "immune system"[MeSH Terms] OR "self healing"[Title/Abstract] OR
  nutrition[MeSH Terms] OR diet[MeSH Terms] OR "dietary pattern"[Title/Abstract] OR
  sleep[MeSH Terms] OR "physical activity"[MeSH Terms] OR exercise[MeSH Terms] OR
  "life style"[MeSH Terms] OR "lifestyle"[Title/Abstract] OR
  "mental health"[MeSH Terms] OR stress[MeSH Terms] OR "stress, psychological"[MeSH Terms] OR
  "gastrointestinal microbiome"[MeSH Terms] OR "gut microbiota"[Title/Abstract] OR
  "gut microbiome"[Title/Abstract] OR
  aging[MeSH Terms] OR longevity[MeSH Terms] OR "healthy aging"[Title/Abstract] OR
  "primary prevention"[MeSH Terms] OR "disease prevention"[Title/Abstract]
) AND humans[MeSH Terms] AND hasabstract[text] AND English[Language]"""

MAX_RESULTS = 30  # 每次最多抓取的论文篇数


@dataclass
class Paper:
    pmid: str
    title: str
    abstract: str
    journal: str
    year: str
    authors: str  # "First Author et al."


class PubMedClient:
    """封装 Bio.Entrez 的 PubMed 检索与抓取。"""

    def __init__(self, email: str, api_key: str = ""):
        """
        Args:
            email:   NCBI 要求的联系邮箱（任意邮箱即可，无需注册）。
            api_key: PubMed API Key（可选）。有 key 时请求频率上限从 3/s 提升至 10/s。
                     免费申请：https://www.ncbi.nlm.nih.gov/account/
        """
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key

    def fetch_by_date(self, target_date: date) -> list[Paper]:
        """检索指定日期发表的相关论文并返回解析结果。"""
        date_str = target_date.strftime("%Y/%m/%d")
        logger.info("正在检索 PubMed，日期：%s", date_str)

        # 第一步：esearch 获取 WebEnv / QueryKey
        with Entrez.esearch(
            db="pubmed",
            term=TOPICS_QUERY,
            datetype="pdat",
            mindate=date_str,
            maxdate=date_str,
            retmax=MAX_RESULTS,
            usehistory="y",
        ) as handle:
            search_result = Entrez.read(handle)

        total = int(search_result.get("Count", 0))
        logger.info("检索命中：%d 篇（最多抓取 %d 篇）", total, MAX_RESULTS)

        if total == 0:
            return []

        web_env = search_result["WebEnv"]
        query_key = search_result["QueryKey"]

        # NCBI 建议相邻请求间隔 ≥ 0.34s（无 key）
        time.sleep(0.4)

        # 第二步：efetch 拉取详情（MEDLINE 格式，解析最稳定）
        with Entrez.efetch(
            db="pubmed",
            webenv=web_env,
            query_key=query_key,
            rettype="medline",
            retmode="text",
            retmax=MAX_RESULTS,
        ) as handle:
            records = list(Medline.parse(handle))

        papers = [self._parse_record(r) for r in records]
        # 过滤掉没有摘要或标题的条目
        papers = [p for p in papers if p.title and p.abstract]

        logger.info("有效论文（含摘要）：%d 篇", len(papers))
        return papers

    # ── 内部解析 ────────────────────────────────────────────────────────────
    @staticmethod
    def _parse_record(record: dict) -> Paper:
        pmid = record.get("PMID", "")
        title = record.get("TI", "").strip()

        # 摘要：MEDLINE 格式中摘要字段为 "AB"
        abstract = record.get("AB", "").strip()
        # 截断至 500 字符，避免 AI prompt 过长
        if len(abstract) > 500:
            abstract = abstract[:500] + "..."

        journal = record.get("JT", "") or record.get("TA", "")  # 全称 / 缩写

        # 发表年份从 DP (Date of Publication) 字段取前 4 位
        dp = record.get("DP", "")
        year = dp[:4] if len(dp) >= 4 else ""

        # 作者列表：AU 字段为 ["Last FM", ...]
        au_list: list[str] = record.get("AU", [])
        if au_list:
            first = au_list[0]
            authors = f"{first} et al." if len(au_list) > 1 else first
        else:
            authors = ""

        return Paper(
            pmid=pmid,
            title=title,
            abstract=abstract,
            journal=journal,
            year=year,
            authors=authors,
        )
