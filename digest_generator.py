"""核心调度：抓取论文 → 构建合规 Prompt → AI 生成解说词。"""

import logging
from datetime import date

from config import Config
from pubmed_client import PubMedClient, Paper
from ai_client import DeepSeekClient

logger = logging.getLogger(__name__)

# ── 系统 Prompt：合规规则 ─────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位严谨、专业的医学健康科普内容创作者，服务于一个医学与健康知识科普频道。
你的受众是普通大众，你的内容将由数字人朗读传播。

【核心定位】
仅做知识科普，不提供任何医疗建议。聚焦以下领域：
- 人体自愈力与免疫系统
- 营养学与饮食科学
- 生活方式管理（睡眠、运动、压力管理）
- 心理健康与情绪调节
- 肠道微生物组与健康
- 抗衰老与健康长寿
- 慢性病风险因素预防

【严格禁止内容——合规红线，绝对不得出现】
1. 具体药物名称（任何处方药、非处方药、中草药、保健品品牌名）
2. 手术、外科、切除、移植、介入、穿刺等医疗操作描述
3. 剂量、用法用量、服药频率等任何服用指导
4. 化疗、放疗、靶向治疗、免疫治疗等临床治疗方案
5. 诊断性表述（"你患有……"、"这是……病的症状"、"确诊"）
6. 疾病治愈或根治宣称（"能治好"、"根治"、"特效"、"彻底消除"）
7. 最高级或绝对化用语（"最佳"、"唯一"、"100%有效"、"一定"）
8. 恐吓性表述（"不做X就会得XX病"、"导致死亡"等负面威胁语气）
9. 以科普替代就医建议（不能暗示自我调节可替代医疗）
10. 医疗器械、检测仪器推荐
11. 夸大研究结论（避免"科学已证明"等绝对表述，用"研究提示"、"数据显示"）
12. 儿童、孕妇等特殊人群的具体健康建议
13. 任何疫苗相关争议性内容

【写作要求】
- 语言通俗流畅，适合朗读，避免术语堆砌
- 每项研究结论须注明来源：期刊名称 + 发表年份
- 用"研究发现"、"科学家观察到"、"数据显示"等引导，而非"你应该"
- 结尾固定加上免责提示"""

# ── 用户 Prompt 模板：单段完整版 ─────────────────────────────────────────────
USER_PROMPT_TEMPLATE = """以下是 {date_label} 在 PubMed 上发表的医学研究（共 {count} 篇），请据此撰写数字人科普解说词。

【论文清单】
{paper_list}

【输出要求】
- 总长度：450–650字中文
- 自然分段，2–3段，不加编号或标题
- 选取最有科普价值、最贴近普通人生活的发现重点呈现
- 每引用一篇研究须标注：（来源：《期刊名》，发表于 XXXX 年）
- 语气温和、积极、有亲和力，适合数字人口播
- 结尾必须包含："以上内容仅供健康科普参考，如有健康问题，请及时咨询专业医生。"

请直接输出解说词正文，不要添加任何标题、序号或说明文字。"""

# ── 用户 Prompt 模板：多段短视频版 ───────────────────────────────────────────
SEGMENTED_USER_PROMPT_TEMPLATE = """以下是 {date_label} 在 PubMed 上发表的医学研究（共 {count} 篇），请据此撰写 {segments} 个独立的数字人科普短视频解说词。

【论文清单】
{paper_list}

【输出要求】
- 共 {segments} 段，每段独立成片，可单独播放
- 每段长度：80–130字中文（对应约 15–30 秒朗读时长）
- 每段聚焦 1 个研究发现，不跨段引用
- 每段引用须标注：（来源：《期刊名》，发表于 XXXX 年）
- 语气温和、积极、有亲和力，适合数字人口播
- 每段结尾必须包含："如有健康问题，请咨询专业医生。"
- 每段之间用 "===第X段===" 作为分隔标记（X 为序号数字）

请严格按格式直接输出，不要添加任何额外说明文字。"""

# ── 用户 Prompt 模板：逐篇独立总结版 ────────────────────────────────────────
PER_PAPER_USER_PROMPT_TEMPLATE = """以下是 {date_label} 在 PubMed 上发表的 {count} 篇医学研究，请为每篇论文分别撰写一段独立的科普解说词。

【论文清单】
{paper_list}

【输出格式】（严格按此格式，不要有任何额外内容）
===PAPER:1===
第1篇的科普段落正文

===PAPER:2===
第2篇的科普段落正文

……以此类推，共 {count} 篇，每篇一个 ===PAPER:序号=== 标记。

【每段要求】
- 每段长度约 {words} 字中文
- 仅基于该篇论文，不引用其他论文内容
- 用"研究发现"、"数据显示"等引导，注明期刊名和年份
- 语气温和、积极，适合数字人口播
- 结尾必须包含："如有健康问题，请咨询专业医生。"

请严格按格式直接输出，不要添加任何额外标题或说明文字。"""


class DigestGenerator:
    """拉取 PubMed 论文并调用 AI 生成合规解说词。"""

    def __init__(self, cfg: Config):
        self._pubmed = PubMedClient(email=cfg.pubmed_email, api_key=cfg.pubmed_api_key)
        self._ai = DeepSeekClient(
            api_key=cfg.deepseek_api_key,
            base_url=cfg.deepseek_base_url,
            model=cfg.deepseek_model,
        )

    def generate(
        self,
        target_date: date,
        segments: int = 1,
        per_paper: bool = False,
        words: int = 500,
    ) -> str:
        date_label = target_date.strftime("%Y年%m月%d日")

        papers = self._pubmed.fetch_by_date(target_date)
        if not papers:
            return (
                f"=== {date_label} ===\n\n"
                "当日未检索到符合主题的 PubMed 论文，请检查网络连接或稍后重试。"
            )

        header = _build_header(target_date, papers, segments, per_paper, words)
        paper_list = _format_paper_list(papers)

        if per_paper:
            logger.info("共 %d 篇论文，逐篇生成解说词（每段约 %d 字），正在调用 AI...", len(papers), words)
            user_prompt = PER_PAPER_USER_PROMPT_TEMPLATE.format(
                date_label=date_label,
                count=len(papers),
                paper_list=paper_list,
                words=words,
            )
            raw = self._ai.chat(SYSTEM_PROMPT, user_prompt).strip()
            script = _inject_links(raw, papers)
        elif segments > 1:
            logger.info("共 %d 篇论文，生成 %d 段解说词，正在调用 AI...", len(papers), segments)
            user_prompt = SEGMENTED_USER_PROMPT_TEMPLATE.format(
                date_label=date_label,
                count=len(papers),
                paper_list=paper_list,
                segments=segments,
            )
            script = self._ai.chat(SYSTEM_PROMPT, user_prompt).strip()
        else:
            logger.info("共 %d 篇论文，生成完整解说词，正在调用 AI...", len(papers))
            user_prompt = USER_PROMPT_TEMPLATE.format(
                date_label=date_label,
                count=len(papers),
                paper_list=paper_list,
            )
            script = self._ai.chat(SYSTEM_PROMPT, user_prompt).strip()

        return header + "\n\n" + script


def _format_paper_list(papers: list[Paper]) -> str:
    lines = []
    for i, p in enumerate(papers, 1):
        lines.append(f"{i}. 标题：{p.title}")
        if p.authors:
            lines.append(f"   作者：{p.authors}")
        lines.append(f"   期刊：{p.journal}（{p.year}）")
        
        # 将原本的 p.abstract 替换为 p.full_text
        if getattr(p, 'full_text', p.abstract):
            lines.append(f"   研究内容：{getattr(p, 'full_text', p.abstract)}")
        lines.append("")
    return "\n".join(lines)


def _inject_links(raw: str, papers: list[Paper]) -> str:
    """将 AI 输出中的 ===PAPER:N=== 标记替换为带序号标题和 PubMed 链接的段落。"""
    import re

    parts = re.split(r"===PAPER:(\d+)===", raw)
    # parts[0] 是首个标记之前的内容（通常为空），之后每两个元素为 (index_str, text)
    result_blocks: list[str] = []
    it = iter(parts[1:])
    for idx_str, text in zip(it, it):
        idx = int(idx_str)
        para = text.strip()
        if not para:
            continue
        if 1 <= idx <= len(papers):
            p = papers[idx - 1]
            link = f"https://pubmed.ncbi.nlm.nih.gov/{p.pmid}/"
            result_blocks.append(
                f"【第{idx}篇】\n"
                f"{para}\n"
                f"来源：《{p.journal}》{p.year} | {link}"
            )
        else:
            result_blocks.append(para)

    return "\n\n".join(result_blocks)


def _build_header(target_date: date, papers: list[Paper], segments: int = 1, per_paper: bool = False, words: int = 500) -> str:
    seen: set[str] = set()
    journals: list[str] = []
    for p in papers:
        if p.journal and p.journal not in seen:
            seen.add(p.journal)
            journals.append(p.journal)
            if len(journals) >= 5:
                break

    if per_paper:
        mode_info = f"模式：逐篇独立总结（共 {len(papers)} 段，每段约 {words} 字，含 PubMed 链接）\n"
    elif segments > 1:
        mode_info = f"模式：短视频分段（共 {segments} 段，每段约 15–30 秒）\n"
    else:
        mode_info = ""
    return (
        f"=== PubMed 每日健康科普解说词 ===\n"
        f"日期：{target_date.strftime('%Y年%m月%d日')}\n"
        f"检索论文数：{len(papers)} 篇\n"
        f"{mode_info}"
        f"来源期刊（部分）：{'、'.join(journals)}\n"
        + "=" * 40
    )
