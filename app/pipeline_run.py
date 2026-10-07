#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:43
# software:Vscode
# brief :统一启动新闻研究报告信号及可选回测流程

import argparse
import logging
import os
import sys
from datetime import datetime, timezone


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

from app.news_run import run_news_pipeline
from app.market_run import run_market_pipeline
from backtest.sentiment_backtest import run_sentiment_backtest
from market_data.market_loader import load_market_data
from private_module.project_io import project_path, read_json, write_json_atomic, write_text_atomic
from processor.news_analyzer import run_analysis_pipeline
from reporting.daily_report import build_daily_report, render_report_markdown
from reporting.market_report import build_market_comparison, render_market_comparison_markdown
from signals.sentiment_signal import build_research_signals


logger = logging.getLogger(__name__)


def run_pipeline(refresh_news=False, analyze=False, backtest=False, limit=None, refresh_market=False):
    """
    生成研究报告和信号，可选择刷新新闻、调用模型或执行历史回测。

    :param refresh_news: 是否刷新公开新闻
    :param analyze: 是否调用模型分析新增候选
    :param backtest: 是否读取真实历史行情执行回测
    :param limit: 本次模型请求条数，为空时使用分析配置
    :param refresh_market: 是否刷新公共日线行情，不调用模型
    :return: 报告、信号和可选回测结果
    """
    config = read_json(project_path(["config", "pipeline_config.json"]))
    config["report"]["symbols"] = config["symbols"]
    config["backtest"]["symbols"] = config["symbols"]
    config["market_report"]["quote_asset"] = read_json(project_path(["config", "market_config.json"]))["quote_asset"]
    if refresh_news:
        run_news_pipeline()
        if not analyze:
            logger.warning("新闻已刷新，本次未分析新条目；报告继续使用已有分析结果")
    if analyze:
        run_analysis_pipeline(limit=limit)
    if refresh_market:
        run_market_pipeline()
    analyses = read_json(project_path(config["analysis_parts"]))
    if not isinstance(analyses, list):
        raise ValueError("新闻分析输入必须是列表")
    report = build_daily_report(analyses, config["report"], datetime.now(timezone.utc))
    market_path = project_path(config["market_parts"])
    prices = load_market_data(market_path) if os.path.exists(market_path) else []
    report["market"] = build_market_comparison(prices, config["symbols"],
                                               datetime.fromisoformat(report["as_of"]), config["market_report"])
    signals = build_research_signals(report, config["signals"])
    signal_generated_at = datetime.now(timezone.utc).isoformat()
    for signal in signals:
        signal["report_as_of"] = signal["as_of"]
        signal["as_of"] = signal_generated_at
    write_json_atomic(project_path(config["report_json_parts"]), report)
    markdown = render_report_markdown(report) + "\n\n" + render_market_comparison_markdown(report["market"])
    write_text_atomic(project_path(config["report_markdown_parts"]), markdown)
    write_json_atomic(project_path(config["signals_parts"]), signals)
    history_path = project_path(config["signal_history_parts"])
    history = read_json(history_path) if os.path.exists(history_path) else []
    if not isinstance(history, list):
        raise ValueError("信号历史格式错误")
    history.extend(signals)
    write_json_atomic(history_path, history)
    logger.info("报告与研究信号已生成：%s", project_path(config["report_markdown_parts"]))
    for signal in signals:
        logger.info("%s：%s；有效新闻 %s 条；情绪分数 %s",
                    signal["symbol"], signal["status"], signal["usable_count"], signal["sentiment_score"])
    backtest_result = None
    if backtest:
        if not os.path.exists(market_path):
            backtest_result = {"status": "missing_market_data", "required_path": market_path,
                               "message": "尚未接入历史行情，不生成虚构收益"}
            logger.warning("回测未执行：缺少真实历史行情 %s", market_path)
        else:
            usable_signals = [signal for signal in history if signal["target_weight"] is not None]
            backtest_result = run_sentiment_backtest(usable_signals, prices, config["backtest"])
        write_json_atomic(project_path(config["backtest_parts"]), backtest_result)
    return {"report": report, "signals": signals, "backtest": backtest_result}


if __name__ == "__main__":
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="SocialAlpha 新闻研究框架")
    parser.add_argument("--refresh-news", action="store_true", help="刷新公开新闻 RSS")
    parser.add_argument("--analyze", action="store_true", help="调用 LLM 分析新增候选，会产生 API 消耗")
    parser.add_argument("--limit", type=int, default=None, help="本次最多请求模型条数")
    parser.add_argument("--backtest", action="store_true", help="使用已保存的行情和时点信号回测")
    parser.add_argument("--refresh-market", action="store_true", help="采集六币种已完成日线，不消耗 LLM API")
    args = parser.parse_args()
    try:
        run_pipeline(args.refresh_news, args.analyze, args.backtest, args.limit, args.refresh_market)
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        logger.error("研究流程失败", exc_info=True)
        raise SystemExit(1)
