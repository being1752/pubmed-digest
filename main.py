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
        "--segments",
        metavar="N",
        type=int,
        help="将解说词拆分为 N 个短视频片段，每段约 15–30 秒（覆盖 DIGEST_SEGMENTS 环境变量；默认 1）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 加载配置
    cfg = Config()
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

    # 生成解说词
    generator = DigestGenerator(cfg)
    segments = args.segments if args.segments is not None else cfg.digest_segments
    result = generator.generate(target_date, segments=segments, per_paper=True)

    # 确定输出目录（命令行参数 > 环境变量）
    output_dir = args.outdir or cfg.output_dir

    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / f"{target_date.strftime('%Y-%m-%d')}.txt"
        file_path.write_text(result, encoding="utf-8")
        logger.info("解说词已保存至：%s", file_path)
        print(result)
    else:
        print(result)


if __name__ == "__main__":
    main()
