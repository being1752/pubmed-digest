"""核心调度：抓取论文 → 构建合规 AITDA Prompt → AI 生成各平台短视频脚本。"""

import logging
import re
from datetime import date
from dataclasses import dataclass

from config import Config
from pubmed_client import PubMedClient, Paper
from ai_client import DeepSeekClient

logger = logging.getLogger(__name__)

# ── AITDA 各段字数比例 ────────────────────────────────────────────────────────
# 行动段 = 总字数 - 其余四段之和，保证总和与配置字数精确一致
#   钩子 10% | 兴趣 25% | 信任 31% | 欲望 25% | 行动 ~9%
_RATIO_HOOK     = 0.10
_RATIO_INTEREST = 0.25
_RATIO_TRUST    = 0.31
_RATIO_DESIRE   = 0.25


def _compute_sections(total: int) -> tuple[int, int, int, int, int]:
    """按比例将总字数分配到 AITDA 各段；行动段取余数保证总和精确。"""
    hook     = round(total * _RATIO_HOOK)
    interest = round(total * _RATIO_INTEREST)
    trust    = round(total * _RATIO_TRUST)
    desire   = round(total * _RATIO_DESIRE)
    action   = total - hook - interest - trust - desire
    return hook, interest, trust, desire, action


# ── 平台静态元数据（字数从配置文件读取，不在这里写死）────────────────────────
@dataclass(frozen=True)
class _PlatformMeta:
    name: str
    style: str
    duration: str


_PLATFORM_META: dict[str, _PlatformMeta] = {
    "douyin": _PlatformMeta(
        name="抖音",
        style="年轻化、节奏感强，开头必须有强烈反问或反常识悬念，让人停下来看",
        duration="约60秒",
    ),
    "shipinghao": _PlatformMeta(
        name="视频号",
        style="专业、权威、温和，受众偏成熟，节奏稳健，有科学感和信任感",
        duration="约90秒",
    ),
    "xiaohongshu": _PlatformMeta(
        name="小红书",
        style="生活化、口语化、有亲切感，像朋友分享，轻松不说教",
        duration="约50秒",
    ),
}

# 供 main.py 等外部引用的平台 key 列表
ALL_PLATFORM_KEYS: list[str] = list(_PLATFORM_META.keys())


# ── 运行时平台配置（含从配置文件读入的字数 + 按比例计算的各段字数）────────────
@dataclass
class PlatformConfig:
    key: str
    name: str
    style: str
    duration: str
    total_words: int   # 来自配置文件
    hook: int          # 自动按比例计算
    interest: int
    trust: int
    desire: int
    action: int


def _make_platform_config(key: str, total_words: int) -> PlatformConfig:
    meta = _PLATFORM_META[key]
    hook, interest, trust, desire, action = _compute_sections(total_words)
    return PlatformConfig(
        key=key,
        name=meta.name,
        style=meta.style,
        duration=meta.duration,
        total_words=total_words,
        hook=hook,
        interest=interest,
        trust=trust,
        desire=desire,
        action=action,
    )


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

# ── AITDA Prompt 模板 ─────────────────────────────────────────────────────────
AITDA_USER_PROMPT_TEMPLATE = """以下是 {date_label} 在 PubMed 上发表的 {count} 篇医学研究，请为每篇撰写适合【{platform_name}】平台的 AITDA 结构短视频脚本。

【平台风格】{style}
【目标视频时长】{duration}，总字数约 {total_words} 字

【论文清单】
{paper_list}

【AITDA 结构要求】
每篇脚本包含以下六段，用标签标注，严格控制字数：
▶ 钩子 Hook（约{hook}字）：强烈反问、悬念或反常识开头，让观众停下来
▶ 兴趣 Interest（约{interest}字）：贴近日常生活，引发共鸣，"这个和你有关"
▶ 信任 Trust（约{trust}字）：引用论文发现，注明期刊名和年份，用"研究发现/数据显示"引导
▶ 欲望 Desire（约{desire}字）：转化为对普通人的健康意义，激发改变意愿
▶ 行动 Action（约{action}字）：引导互动 + 必须以"如有健康问题，请咨询专业医生。"结尾
▶ 完整串讲：将以上五段整合为一段自然流畅的连续文字，适合数字人完整朗读，不含任何标签或分段符号，语感顺畅、浑然一体

【输出格式】（严格按此格式，不要添加任何额外内容）
===PAPER:1===
▶ 钩子
（钩子内容）
▶ 兴趣
（兴趣内容）
▶ 信任
（信任内容）
▶ 欲望
（欲望内容）
▶ 行动
（行动内容）
▶ 完整串讲
（将以上五段整合为一段流畅文字）

===PAPER:2===
（同上格式）

……共 {count} 篇，每篇一个 ===PAPER:序号=== 标记。"""


class DigestGenerator:
    """拉取 PubMed 论文并调用 AI 生成各平台 AITDA 合规脚本。"""

    def __init__(self, cfg: Config):
        self._pubmed = PubMedClient(
            email=cfg.pubmed_email,
            api_key=cfg.pubmed_api_key,
            max_results=cfg.pubmed_max_results,
        )
        self._ai = DeepSeekClient(
            api_key=cfg.deepseek_api_key,
            base_url=cfg.deepseek_base_url,
            model=cfg.deepseek_model,
        )
        # 按配置文件字数 + 固定比例，构建各平台运行时配置
        self._platforms: dict[str, PlatformConfig] = {
            "douyin":      _make_platform_config("douyin",      cfg.douyin_words),
            "shipinghao":  _make_platform_config("shipinghao",  cfg.shipinghao_words),
            "xiaohongshu": _make_platform_config("xiaohongshu", cfg.xiaohongshu_words),
        }

    def generate(self, target_date: date, platforms: list[str]) -> str:
        date_label = target_date.strftime("%Y年%m月%d日")

        papers = self._pubmed.fetch_by_date(target_date)
        if not papers:
            return (
                f"=== {date_label} ===\n\n"
                "当日未检索到符合主题的 PubMed 论文，请检查网络连接或稍后重试。"
            )

        paper_list = _format_paper_list(papers)
        header = _build_header(target_date, papers, [self._platforms[k] for k in platforms])

        platform_sections: list[str] = []
        for platform_key in platforms:
            pcfg = self._platforms[platform_key]
            logger.info(
                "【%s】总字数 %d（钩子%d/兴趣%d/信任%d/欲望%d/行动%d），共 %d 篇，正在调用 AI...",
                pcfg.name, pcfg.total_words,
                pcfg.hook, pcfg.interest, pcfg.trust, pcfg.desire, pcfg.action,
                len(papers),
            )
            user_prompt = AITDA_USER_PROMPT_TEMPLATE.format(
                date_label=date_label,
                count=len(papers),
                platform_name=pcfg.name,
                style=pcfg.style,
                duration=pcfg.duration,
                total_words=pcfg.total_words,
                hook=pcfg.hook,
                interest=pcfg.interest,
                trust=pcfg.trust,
                desire=pcfg.desire,
                action=pcfg.action,
                paper_list=paper_list,
            )
            raw = self._ai.chat(SYSTEM_PROMPT, user_prompt).strip()
            section = _parse_and_inject(raw, papers, pcfg)
            platform_sections.append(section)

        divider = "\n\n" + "─" * 40 + "\n\n"
        return header + "\n\n" + divider.join(platform_sections)


def _format_paper_list(papers: list[Paper]) -> str:
    lines = []
    for i, p in enumerate(papers, 1):
        lines.append(f"{i}. 标题：{p.title}")
        if p.authors:
            lines.append(f"   作者：{p.authors}")
        lines.append(f"   期刊：{p.journal}（{p.year}）")
        content = getattr(p, "full_text", None) or p.abstract
        if content:
            lines.append(f"   研究内容：{content}")
        lines.append("")
    return "\n".join(lines)


def _parse_and_inject(raw: str, papers: list[Paper], pcfg: PlatformConfig) -> str:
    """解析 ===PAPER:N=== 标记，注入平台标题和 PubMed 来源链接。"""
    parts = re.split(r"===PAPER:(\d+)===", raw)
    blocks: list[str] = []

    it = iter(parts[1:])
    for idx_str, text in zip(it, it):
        idx = int(idx_str)
        body = text.strip()
        if not body or not (1 <= idx <= len(papers)):
            continue
        p = papers[idx - 1]
        link = f"https://pubmed.ncbi.nlm.nih.gov/{p.pmid}/"
        blocks.append(
            f"【第{idx}篇】\n"
            f"{body}\n"
            f"来源：《{p.journal}》{p.year} | {link}"
        )

    platform_header = (
        f"{'=' * 40}\n"
        f"  {pcfg.name}  |  {pcfg.duration}  |  {pcfg.total_words}字"
        f"  （钩子{pcfg.hook}/兴趣{pcfg.interest}/信任{pcfg.trust}/欲望{pcfg.desire}/行动{pcfg.action}）\n"
        f"{'=' * 40}"
    )
    return platform_header + "\n\n" + "\n\n".join(blocks)


def _build_header(target_date: date, papers: list[Paper], platform_cfgs: list[PlatformConfig]) -> str:
    seen: set[str] = set()
    journals: list[str] = []
    for p in papers:
        if p.journal and p.journal not in seen:
            seen.add(p.journal)
            journals.append(p.journal)
            if len(journals) >= 5:
                break

    platform_names = "、".join(pc.name for pc in platform_cfgs)
    return (
        f"=== PubMed 每日健康科普脚本（AITDA 结构）===\n"
        f"日期：{target_date.strftime('%Y年%m月%d日')}\n"
        f"检索论文数：{len(papers)} 篇\n"
        f"生成平台：{platform_names}\n"
        f"来源期刊（部分）：{'、'.join(journals)}\n"
        + "=" * 40
    )
