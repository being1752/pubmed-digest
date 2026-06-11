"""PubMed E-utilities 客户端，并集成 EuropePMC 与 Unpaywall 获取全文全文。"""

import time
import logging
import requests
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from Bio import Entrez, Medline
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# ── PubMed 检索式 ────────────────────────────────────────────────────────────
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

MAX_RESULTS = 30  # 默认每次最多抓取的论文篇数（可通过构造函数覆盖）

@dataclass
class Paper:
    pmid: str
    title: str
    abstract: str
    journal: str
    year: str
    authors: str
    full_text: str = "" # 新增：用于存储抓取到的全文内容


class PubMedClient:
    """封装 Bio.Entrez 的 PubMed 检索，并自动尝试拉取全文。"""

    def __init__(self, email: str, api_key: str = "", max_results: int = MAX_RESULTS):
        self.email = email
        self.max_results = max_results
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
        self.headers = {'User-Agent': 'PubMed-Digest-Bot/1.0'}

    def fetch_by_date(self, target_date: date) -> list[Paper]:
        date_str = target_date.strftime("%Y/%m/%d")
        logger.info("正在检索 PubMed，日期：%s", date_str)

        with Entrez.esearch(
            db="pubmed",
            term=TOPICS_QUERY,
            datetype="pdat",
            mindate=date_str,
            maxdate=date_str,
            retmax=self.max_results,
            usehistory="y",
        ) as handle:
            search_result = Entrez.read(handle)

        total = int(search_result.get("Count", 0))
        logger.info("检索命中：%d 篇（最多抓取 %d 篇）", total, self.max_results)

        if total == 0:
            return []

        web_env = search_result["WebEnv"]
        query_key = search_result["QueryKey"]
        time.sleep(0.4)

        with Entrez.efetch(
            db="pubmed",
            webenv=web_env,
            query_key=query_key,
            rettype="medline",
            retmode="text",
            retmax=self.max_results,
        ) as handle:
            records = list(Medline.parse(handle))

        papers = []
        for r in records:
            paper = self._parse_record(r)
            if paper.title and paper.abstract:
                # 尝试获取全文，如果获取不到则回退到完整摘要
                logger.info(f"正在尝试获取全文 PMID: {paper.pmid}...")
                full_text = self._fetch_full_text(paper.pmid)
                paper.full_text = full_text if full_text else paper.abstract
                # print(f"[PMID {paper.pmid}] 全文内容：\n{paper.full_text}\n{'='*80}")
                # 对送给大模型的文本进行合理截断 (比如 8000 字符，防止 Token 超限，但足够包含核心机制)
                if len(paper.full_text) > 8000:
                    paper.full_text = paper.full_text[:8000] + "\n...[Content Truncated]..."
                
                papers.append(paper)

        logger.info("有效论文（含摘要/全文）：%d 篇", len(papers))
        return papers

    def fetch_by_topic(self, topic: str, days_back: int = 7) -> list[Paper]:
        """按专题关键词和回溯天数检索 PubMed。

        Parameters
        ----------
        topic : str
            专题关键词，如 "sleep"、"gut microbiome"
        days_back : int
            回溯天数，如 7 = 查最近 7 天

        Returns
        -------
        list[Paper]
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days_back - 1)
        logger.info(
            "正在检索 PubMed，专题：%s，日期范围：%s ~ %s",
            topic, start_date.strftime("%Y/%m/%d"), end_date.strftime("%Y/%m/%d"),
        )

        # 动态构建查询：专题关键词 + 公共过滤条件
        query = (
            f'({topic}[Title/Abstract] OR {topic}[MeSH Terms]) '
            f'AND humans[MeSH Terms] AND hasabstract[text] AND English[Language]'
        )

        with Entrez.esearch(
            db="pubmed",
            term=query,
            datetype="pdat",
            mindate=start_date.strftime("%Y/%m/%d"),
            maxdate=end_date.strftime("%Y/%m/%d"),
            retmax=self.max_results,
            usehistory="y",
        ) as handle:
            search_result = Entrez.read(handle)

        total = int(search_result.get("Count", 0))
        logger.info("检索命中：%d 篇（最多抓取 %d 篇）", total, self.max_results)

        if total == 0:
            return []

        web_env = search_result["WebEnv"]
        query_key = search_result["QueryKey"]
        time.sleep(0.4)

        with Entrez.efetch(
            db="pubmed",
            webenv=web_env,
            query_key=query_key,
            rettype="medline",
            retmode="text",
            retmax=self.max_results,
        ) as handle:
            records = list(Medline.parse(handle))

        papers = []
        for r in records:
            paper = self._parse_record(r)
            if paper.title and paper.abstract:
                logger.info(f"正在尝试获取全文 PMID: {paper.pmid}...")
                full_text = self._fetch_full_text(paper.pmid)
                paper.full_text = full_text if full_text else paper.abstract
                if len(paper.full_text) > 8000:
                    paper.full_text = paper.full_text[:8000] + "\n...[Content Truncated]..."
                papers.append(paper)

        logger.info("有效论文（含摘要/全文）：%d 篇", len(papers))
        return papers

    def _fetch_full_text(self, pmid: str) -> str:
        """策略：通过 Europe PMC 拉取结构化全文文本。"""
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {"query": f"ext_id:{pmid}", "resultType": "core", "format": "json"}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                results = response.json().get('resultList', {}).get('result', [])
                if results:
                    article = results[0]
                    if article.get('isOpenAccess') == 'Y' and 'pmcid' in article:
                        pmcid = article['pmcid']
                        return self._get_epmc_xml_body(pmcid)
        except Exception as e:
            logger.debug(f"Europe PMC 获取全文失败 PMID {pmid}: {e}")
        return ""

    def _get_epmc_xml_body(self, pmcid: str) -> str:
        """解析 XML 提取正文内容，摒弃无用的参考文献标记。"""
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                # 简单清洗 XML 提取文本
                root = ET.fromstring(response.content)
                body = root.find('.//body')
                if body is not None:
                    return "".join(body.itertext())
        except Exception:
            pass
        return ""

    @staticmethod
    def _parse_record(record: dict) -> Paper:
        pmid = record.get("PMID", "")
        title = record.get("TI", "").strip()
        
        # 提取完整摘要，不再进行 500 字符的粗暴截断
        abstract = record.get("AB", "").strip() 
        journal = record.get("JT", "") or record.get("TA", "")
        
        dp = record.get("DP", "")
        year = dp[:4] if len(dp) >= 4 else ""
        
        au_list: list[str] = record.get("AU", [])
        if au_list:
            authors = f"{au_list[0]} et al." if len(au_list) > 1 else au_list[0]
        else:
            authors = ""

        return Paper(pmid=pmid, title=title, abstract=abstract, journal=journal, year=year, authors=authors)