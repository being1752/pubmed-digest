#!/usr/bin/env python3
"""
pubmed-digest — 每日 PubMed 健康科普解说词生成器
用法：
    python main.py                          # 生成昨天的解说词，输出到 stdout
    python main.py --date 2025-05-28        # 指定日期
    python main.py --outdir ./output        # 保存到文件（按日期命名）
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from config import Config
from digest_generator import DigestGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 PubMed 生成每日健康科普解说词")
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="目标日期（默认：昨天）",
    )
    parser.add_argument(
        "--outdir",
        metavar="DIR",
        help="输出目录（覆盖 OUTPUT_DIR 环境变量；留空则打印到 stdout）",
    )
    parser.add_argument(
        "--platform",
        metavar="PLATFORM",
        choices=["douyin", "shipinghao", "xiaohongshu", "all"],
        default=None,
        help="生成指定平台的脚本（douyin/shipinghao/xiaohongshu/all；覆盖 PLATFORMS 环境变量；默认 all）",
    )
    parser.add_argument(
        "--mode",
        choices=["health", "business"],
        default=None,
        help="内容模式：health（健康科普，默认）或 business（商业赛道·视频号口播）",
    )
    parser.add_argument(
        "--topic",
        metavar="KEYWORD",
        help='专题关键词，如 "sleep"、"gut microbiome"；指定后按专题+时间范围查询',
    )
    parser.add_argument(
        "--days",
        type=int,
        metavar="N",
        help="回溯天数（与 --topic 配合使用，默认 7）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 加载配置
    cfg = Config()
    # --mode 命令行参数优先于环境变量
    if args.mode is not None:
        cfg.content_mode = args.mode
    try:
        cfg.validate()
    except ValueError as e:
        logger.error("%s", e)
        sys.exit(1)

    # 确定目标日期
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error("日期格式错误，应为 YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = date.today() - timedelta(days=1)

    logger.info("目标日期：%s", target_date.strftime("%Y-%m-%d"))
    logger.info("内容模式：%s", cfg.content_mode)

    # 解析平台列表（两种模式均支持多平台）
    _ALL_PLATFORMS = ["douyin", "shipinghao", "xiaohongshu"]
    platform_raw = args.platform if args.platform is not None else cfg.platforms
    if platform_raw == "all":
        platforms = _ALL_PLATFORMS
    else:
        platforms = [p.strip() for p in platform_raw.split(",") if p.strip() in _ALL_PLATFORMS]
        if not platforms:
            logger.error("PLATFORMS 配置无效：%s，可选值：douyin、shipinghao、xiaohongshu、all", platform_raw)
            sys.exit(1)
    logger.info("生成平台：%s", "、".join(platforms))

    # 确定专题和时间范围（命令行参数优先于配置文件）
    topic = args.topic if args.topic is not None else cfg.pubmed_topic
    days_back = args.days if args.days is not None else cfg.pubmed_days_back
    if topic:
        logger.info("专题模式：%s，回溯 %d 天", topic, days_back)

    # 生成 AITDA 脚本
    generator = DigestGenerator(cfg)
    result = generator.generate(target_date, platforms=platforms,
                                topic=topic, days_back=days_back)

    # 确定输出目录（命令行参数 > 环境变量）
    output_dir = args.outdir or cfg.output_dir

    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        if topic:
            filename = f"{topic}_{target_date.strftime('%Y-%m-%d')}.txt"
        else:
            filename = f"{target_date.strftime('%Y-%m-%d')}.txt"
        file_path = out_path / filename
        file_path.write_text(result, encoding="utf-8")
        logger.info("解说词已保存至：%s", file_path)
        print(result)
    else:
        print(result)


if __name__ == "__main__":
    main()
