"""核心调度：抓取论文 → 构建合规 AITDA Prompt → AI 生成各平台短视频脚本。"""

import logging
import re
from datetime import date, timedelta
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
        #style="口语化，面向普罗大众，压迫感强、一针见血、恨铁不成钢的商业导师风。直接刺痛B端老板转型焦虑，以高姿态进行认知降维打击",
        duration="约60秒",
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


# ── 商业赛道模式：各段字数比例（行动段为固定 CTA，不参与比例分配）────────────
_BIZ_RATIO_HOOK    = 0.15   # 反常识商业论断，抓住老板眼球
_BIZ_RATIO_INTEREST = 0.20  # 一句话点明颠覆性技术
_BIZ_RATIO_TRUST   = 0.25   # 期刊出处 + 核心数据，建立信任
_BIZ_RATIO_DESIRE  = 0.40   # 市场天花板 + 入局时机，激发欲望


def _compute_biz_sections(total: int) -> tuple[int, int, int, int]:
    """商业模式按比例分配正文字数（不含固定 CTA）。"""
    hook     = round(total * _BIZ_RATIO_HOOK)
    interest = round(total * _BIZ_RATIO_INTEREST)
    trust    = round(total * _BIZ_RATIO_TRUST)
    desire   = total - hook - interest - trust
    return hook, interest, trust, desire


# ── 商业赛道：系统 Prompt ─────────────────────────────────────────────────────
BUSINESS_SYSTEM_PROMPT = """你是一位深谙一二级市场、专注大健康与生命科学赛道的顶级商业分析师兼投资人。
你的受众是身价千万以上、正在寻找新赛道转型机会的企业家和高净值投资者。
你的内容将由商业分析师形象的数字人通过短视频平台口播，是真人在镜头前说话，不是写文章。

【核心定位】
用"降维打击"的商业视角，将晦涩的前沿医学研究，翻译成激动人心的"财富密码"和"商业蓝海"。
你不是在做健康科普，你是在发布一份微型"行业投研报告"。

【核心叙事逻辑（必须严格遵守）】
1. 痛点重塑：不讲个人健康痛点，讲传统行业内卷、增长乏力、富豪们的抗衰/续命焦虑。
2. 学术降维：引用 PubMed 最新论文，不是为了治病，而是为了证明"这项技术已经迎来商业化拐点"，这是极高技术壁垒的蓝海。
3. 降维打击：强调前沿科技（如微生态、细胞自噬、干细胞、基因检测）对传统美业、养生、大健康行业的降维打击。
4. 圈层过滤：大量使用商业术语（红利期、技术护城河、生命周期管理、蓝海市场、马太效应、商业化拐点）。

【严格禁止内容】
1. 绝对不提"能治好X病"，改为"颠覆了传统的健康干预逻辑"或"开启了商业化窗口"。
2. 绝对不教人怎么吃穿用度，老板不缺这些基础知识。
3. 语气绝不卑微，要用平视甚至俯视的"智囊团"口吻。
4. 不做疗效承诺，聚焦技术壁垒和市场机会的描述。

【口语化写作要求——这是最重要的一条】
你写的是真人对着镜头说的话，不是文章，必须做到：
- 句子短，最多20字一句，多用逗号断句，少用句号，少用分号
- 用"你看"、"说真的"、"我跟你讲"、"想想看"、"对吧"等真人口头语自然穿插
- 绝对禁止书面化表达：不用"然而"、"因此"、"综上所述"、"值得注意的是"
- 数字要口语化："三分之一"说成"30%"，"显著增加"说成"翻了将近一倍"
- 说话有节奏感，像说相声一样有抑扬，能让人听进去
- 必须包含权威出处（如：《Nature Medicine》最新数据显示……）
- 严格按照指定格式输出，不添加任何额外说明文字"""


# ── 商业赛道：用户 Prompt 模板 ────────────────────────────────────────────────
BUSINESS_USER_PROMPT_TEMPLATE = """以下是 {date_label} 在 PubMed 上发表的前沿科学研究（共 {count} 篇）。
请为每篇撰写适合【{platform_name}】平台的商业赛道 AITDA 口播脚本。

【平台风格】{style}
【目标时长】{duration}，每篇总字数约 {total_words} 字

【论文清单】
{paper_list}

【AITDA 结构要求】
每篇脚本包含以下六段，用标签标注，严格控制字数。
每一段都必须是真人对着镜头说话的口吻，像顶级顾问在和老板私下交流，不是写投研报告：
▶ 钩子 Hook（约{hook}字）：第一句是反常识的商业论断，句子短、语气重，让老板立刻停下来。
  示例："当你们还在传统美业里卷价格，硅谷那帮人已经在这件事上砸进去五百亿美元了……"
▶ 兴趣 Interest（约{interest}字）：用一两句口语点明这篇论文揭示的商业化信号，像在私下透露内部消息。
▶ 信任 Trust（约{trust}字）：口语化说出期刊名称和年份，用"数据显示"或"科学家发现"引导，绝不堆砌术语。
▶ 欲望 Desire（约{desire}字）：直接说市场天花板、入局时间窗口、为什么先行者赢家通吃，像在给老板指路。
▶ 行动 Action（约{action}字）：结合本篇论文，像顶级顾问发出私人邀约，自然引出"1V1 商业诊断 / 定制方案"；结尾固定为"主页私信【诊断】，我们一对一聊。"
▶ 完整串讲：将以上五段整合为一段连续的口播文字，句子短、节奏快，读起来像真人在说话，不含任何标签。

【输出格式】（严格按此格式，不要添加任何额外内容）
===PAPER:1===
▶ 标题
（为本篇内容起一个符合{platform_name}平台风格、吸引目标受众点击的短标题，不超过20字）
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


# ── 系统 Prompt：合规规则 ─────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位严谨、专业的医学健康科普内容创作者，服务于一个医学与健康知识科普频道。
你的受众是普通大众，你的内容将由数字人朗读传播，是真人对着镜头说话，不是写文章。

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

【口语化写作要求——这是最重要的一条】
你写的是真人对着镜头说的话，不是文章，必须做到：
- 句子短，最多20字一句，多用逗号断句，少用长句
- 用"你知道吗"、"说真的"、"我告诉你"、"你想想"、"对不对"等真人口头语自然穿插
- 绝对禁止书面化表达：不用"然而"、"因此"、"综上所述"、"值得注意的是"、"研究表明"改说"科学家发现"
- 数字口语化："显著增加"说成"多了将近一倍"，"降低风险"说成"少踩这个坑"
- 说话有节奏，像跟朋友聊天，能让人听进去
- 每项研究结论须注明来源：期刊名称 + 发表年份
- 结尾固定加上免责提示"""

# ── AITDA Prompt 模板 ─────────────────────────────────────────────────────────
AITDA_USER_PROMPT_TEMPLATE = """以下是 {date_label} 在 PubMed 上发表的 {count} 篇医学研究，请为每篇撰写适合【{platform_name}】平台的 AITDA 结构短视频脚本。

【平台风格】{style}
【目标视频时长】{duration}，总字数约 {total_words} 字

【论文清单】
{paper_list}

【AITDA 结构要求】
每篇脚本包含以下六段，用标签标注，严格控制字数。
每一段都必须是真人说话的口吻，像主播对着镜头聊天，不是写文章：
▶ 钩子 Hook（约{hook}字）：强烈反问、悬念或反常识开头，让观众停下来。句子要短，第一句就要抓人。
▶ 兴趣 Interest（约{interest}字）：贴近日常生活，引发共鸣，让人觉得"这个跟我有关"。
▶ 信任 Trust（约{trust}字）：口语化地说出论文期刊名和年份，用"科学家发现"、"数据显示"引导，不堆砌术语。
▶ 欲望 Desire（约{desire}字）：说出对普通人的实际意义，激发改变意愿，像在给朋友出主意。
▶ 行动 Action（约{action}字）：引导互动，结尾必须是"如有健康问题，请咨询专业医生。"
▶ 完整串讲：将以上五段整合为一段连续的口播文字，句子短、节奏快，不含任何标签，读起来像真人在说话。

【输出格式】（严格按此格式，不要添加任何额外内容）
===PAPER:1===
▶ 标题
（为本篇内容起一个符合{platform_name}平台风格、吸引目标受众点击的短标题，不超过20字）
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
        self._content_mode = cfg.content_mode
        # 按配置文件字数 + 固定比例，构建各平台运行时配置
        self._platforms: dict[str, PlatformConfig] = {
            "douyin":      _make_platform_config("douyin",      cfg.douyin_words),
            "shipinghao":  _make_platform_config("shipinghao",  cfg.shipinghao_words),
            "xiaohongshu": _make_platform_config("xiaohongshu", cfg.xiaohongshu_words),
        }

    def generate(self, target_date: date, platforms: list[str],
                 topic: str = "", days_back: int = 1) -> str:
        if self._content_mode == "business":
            return self._generate_business(target_date, platforms, topic, days_back)
        return self._generate_health(target_date, platforms, topic, days_back)

    def _fetch_papers(self, target_date: date, topic: str, days_back: int) -> list[Paper]:
        """根据是否指定专题，决定调用按天查询还是专题时间范围查询。"""
        if topic:
            return self._pubmed.fetch_by_topic(topic, days_back)
        return self._pubmed.fetch_by_date(target_date)

    def _make_date_label(self, target_date: date, topic: str, days_back: int) -> str:
        """生成日期标签。专题模式显示时间范围，单日模式显示具体日期。"""
        if topic:
            end = target_date
            start = end - timedelta(days=days_back - 1)
            return f"{start.strftime('%Y年%m月%d日')} ~ {end.strftime('%Y年%m月%d日')}"
        return target_date.strftime("%Y年%m月%d日")

    # ── 健康科普模式 ──────────────────────────────────────────────────────────
    def _generate_health(self, target_date: date, platforms: list[str],
                         topic: str = "", days_back: int = 1) -> str:
        date_label = self._make_date_label(target_date, topic, days_back)

        papers = self._fetch_papers(target_date, topic, days_back)
        if not papers:
            return (
                f"=== {date_label} ===\n\n"
                "未检索到符合主题的 PubMed 论文，请检查网络连接或稍后重试。"
            )

        paper_list = _format_paper_list(papers)
        header = _build_header(target_date, papers, [self._platforms[k] for k in platforms],
                               topic=topic, days_back=days_back)

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

    # ── 商业赛道模式（多平台） ────────────────────────────────────────────────
    def _generate_business(self, target_date: date, platforms: list[str],
                           topic: str = "", days_back: int = 1) -> str:
        date_label = self._make_date_label(target_date, topic, days_back)

        papers = self._fetch_papers(target_date, topic, days_back)
        if not papers:
            return (
                f"=== {date_label} 商业赛道版 ===\n\n"
                "未检索到符合主题的 PubMed 论文，请检查网络连接或稍后重试。"
            )

        paper_list = _format_paper_list(papers)
        topic_tag = f"专题：{topic} | " if topic else ""
        platform_names = "、".join(self._platforms[k].name for k in platforms)
        header = (
            f"=== PubMed 每日商业赛道脚本（AITDA·商业版）===\n"
            f"{topic_tag}日期：{date_label}\n"
            f"检索论文数：{len(papers)} 篇\n"
            f"生成平台：{platform_names}\n"
            + "=" * 40
        )

        platform_sections: list[str] = []
        for platform_key in platforms:
            pcfg = self._platforms[platform_key]
            hook, interest, trust, desire = _compute_biz_sections(pcfg.total_words)
            action = pcfg.total_words - hook - interest - trust - desire
            logger.info(
                "[商业模式] 【%s】%d字（钩子%d/兴趣%d/信任%d/欲望%d/行动%d），共%d篇，正在调用 AI...",
                pcfg.name, pcfg.total_words, hook, interest, trust, desire, action, len(papers),
            )
            user_prompt = BUSINESS_USER_PROMPT_TEMPLATE.format(
                date_label=date_label,
                count=len(papers),
                platform_name=pcfg.name,
                style=pcfg.style,
                duration=pcfg.duration,
                total_words=pcfg.total_words,
                hook=hook,
                interest=interest,
                trust=trust,
                desire=desire,
                action=action,
                paper_list=paper_list,
            )
            raw = self._ai.chat(BUSINESS_SYSTEM_PROMPT, user_prompt).strip()
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
        # 提取标题段
        title_match = re.search(r"▶\s*标题\s*\n+([\s\S]+?)(?=\n▶|\Z)", body)
        title = title_match.group(1).strip() if title_match else ""
        # 只保留「完整串讲」段落
        match = re.search(r"▶\s*完整串讲\s*\n+([\s\S]+?)(?=\n▶|\Z)", body)
        narrative = match.group(1).strip() if match else body
        blocks.append(
            f"【第{idx}篇】{f'  📌 {title}' if title else ''}\n"
            f"{narrative}\n"
            f"来源：《{p.journal}》{p.year} | {link}"
        )

    platform_header = (
        f"{'=' * 40}\n"
        f"  {pcfg.name}  |  {pcfg.duration}  |  {pcfg.total_words}字"
        f"  （钩子{pcfg.hook}/兴趣{pcfg.interest}/信任{pcfg.trust}/欲望{pcfg.desire}/行动{pcfg.action}）\n"
        f"{'=' * 40}"
    )
    return platform_header + "\n\n" + "\n\n".join(blocks)


def _build_header(target_date: date, papers: list[Paper],
                  platform_cfgs: list[PlatformConfig],
                  topic: str = "", days_back: int = 1) -> str:
    seen: set[str] = set()
    journals: list[str] = []
    for p in papers:
        if p.journal and p.journal not in seen:
            seen.add(p.journal)
            journals.append(p.journal)
            if len(journals) >= 5:
                break

    platform_names = "、".join(pc.name for pc in platform_cfgs)

    if topic:
        end = target_date
        start = end - timedelta(days=days_back - 1)
        date_str = f"{start.strftime('%Y年%m月%d日')} ~ {end.strftime('%Y年%m月%d日')}"
        topic_line = f"专题：{topic}\n"
    else:
        date_str = target_date.strftime('%Y年%m月%d日')
        topic_line = ""

    return (
        f"=== PubMed 健康科普脚本（AITDA 结构）===\n"
        f"{topic_line}日期：{date_str}\n"
        f"检索论文数：{len(papers)} 篇\n"
        f"生成平台：{platform_names}\n"
        f"来源期刊（部分）：{'、'.join(journals)}\n"
        + "=" * 40
    )
