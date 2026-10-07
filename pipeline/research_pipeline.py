#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:50
# software:Vscode
# brief :编排采集分析、日报信号保存和可选历史回测

import logging
import os
from datetime import datetime, timedelta, timezone

from backtest.sentiment_backtest import run_sentiment_backtest
from crawler.news_pipeline import run_news_pipeline
from market_data.market_pipeline import run_market_pipeline
from market_data.market_loader import load_market_data
from private_module.project_config import load_analysis_config, load_project_config
from private_module.project_io import project_path, read_json, write_json_atomic, write_text_atomic
from processor.news_analyzer import analysis_fingerprint, run_analysis_pipeline
from processor.news_focus import classify_news_focus
from reporting.daily_report import build_daily_report, render_report_markdown
from reporting.market_report import build_market_comparison, render_market_comparison_markdown
from signals.sentiment_signal import build_research_signals


logger = logging.getLogger(__name__)


def build_research_report(analyses, config, now=None):
    """
    组装新闻、社区、采集覆盖和行情报告，不写文件或调用模型。

    :param analyses: 已保存的新闻分析记录
    :param config: 已注入币种与报价资产的流程配置
    :param now: 有时区的观察时刻，为空时获取 UTC 当前时间
    :return: 报告字典和已校验行情列表
    """
    report = build_daily_report(analyses, config["report"], now or datetime.now(timezone.utc))
    news_config = load_project_config("news")
    news_path = project_path(news_config["output_parts"])
    report["collection"] = []
    if os.path.exists(news_path):
        analysis_config = load_analysis_config()
        as_of = datetime.fromisoformat(report["as_of"])
        window_start = as_of - timedelta(hours=config["report"]["lookback_hours"])
        records = [record for record in read_json(news_path)
                   if window_start <= datetime.fromisoformat(record["publish_time"]) <= as_of]
        successful_keys = {(record["id"], record.get("fingerprint")) for record in analyses if record.get("status") == "success"}
        pending_ids = {record["id"] for record in records
                       if (record["id"], analysis_fingerprint(record, analysis_config)) not in successful_keys
                       and classify_news_focus(record, analysis_config, as_of)["selected"]}
        for symbol in config["symbols"]:
            mentions = [record for record in records if symbol in record["mention_symbol"]]
            report["collection"].append({"symbol": symbol,
                                         "news_count": sum(record.get("content_kind") != "community" for record in mentions),
                                         "community_count": sum(record.get("content_kind") == "community" for record in mentions),
                                         "pending_count": sum(record["id"] in pending_ids for record in mentions)})
    social_config = load_project_config("social")
    source_status_path = project_path(social_config["status_parts"])
    report["source_statuses"] = read_json(source_status_path) if os.path.exists(source_status_path) else []
    market_path = project_path(config["market_parts"])
    prices = load_market_data(market_path) if os.path.exists(market_path) else []
    report["market"] = build_market_comparison(prices, config["symbols"],
                                               datetime.fromisoformat(report["as_of"]), config["market_report"])
    return report, prices


def save_research_results(report, signals, config):
    """
    保存日报、当前信号和实际生成时点的信号历史，并记录业务汇总。

    :param report: 完整研究报告
    :param signals: 当前研究信号，保存前补充实际生成时间
    :param config: 输出路径配置
    :return: 合并后的信号历史列表
    """
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
    for coin in report["social_coins"]:
        logger.info("%s：社区帖子有效分析 %s 条；社区情绪分数 %s",
                    coin["symbol"], coin["usable_count"], coin["sentiment_score"])
    return history


def run_optional_backtest(history, prices, config):
    """
    在明确启用回测时使用真实行情和已积累信号，缺少行情返回说明。

    :param history: 已保存的信号历史
    :param prices: 真实行情列表
    :param config: 币种、行情路径和回测成本配置
    :return: 已保存的回测结果
    """
    market_path = project_path(config["market_parts"])
    if not os.path.exists(market_path):
        backtest_result = {"status": "missing_market_data", "required_path": market_path,
                           "message": "尚未接入历史行情，不生成虚构收益"}
        logger.warning("回测未执行：缺少真实历史行情 %s", market_path)
    else:
        usable_signals = [signal for signal in history if signal["target_weight"] is not None]
        backtest_result = run_sentiment_backtest(usable_signals, prices, config["backtest"])
    write_json_atomic(project_path(config["backtest_parts"]), backtest_result)
    return backtest_result


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
    config = load_project_config("pipeline")
    config["report"]["symbols"] = config["symbols"]
    config["backtest"]["symbols"] = config["symbols"]
    config["market_report"]["quote_asset"] = load_project_config("market")["quote_asset"]
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
    report, prices = build_research_report(analyses, config)
    signals = build_research_signals(report, config["signals"])
    history = save_research_results(report, signals, config)
    backtest_result = run_optional_backtest(history, prices, config) if backtest else None
    return {"report": report, "signals": signals, "backtest": backtest_result}
