#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:08
# software:Vscode
# brief :使用结构化 LLM 输出分析新闻情绪事件并缓存结果

import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from dotenv import load_dotenv
from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from processor.news_focus import classify_news_focus


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger = logging.getLogger(__name__)


class NewsAnalysis(BaseModel):
    """新闻情绪和事件的严格输出结构，无继承业务方法需要修改。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    sentiment: Literal["positive", "negative", "neutral", "mixed", "unknown"]
    event_type: Literal["regulation", "security", "adoption", "market", "macro", "technology", "other", "unknown"]
    symbols: list[Literal["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"]]
    confidence: float = Field(ge=0, le=1)
    summary: str
    rationale: str
    insufficient_context: bool


def load_analysis_config():
    """
    加载分析参数及环境配置，不修改已有环境变量。

    :return: 分析配置字典
    """
    load_dotenv(os.path.join(PROJECT_PATH, ".env"), override=False)
    with open(os.path.join(PROJECT_PATH, "config", "analysis_config.json"), encoding="utf-8") as config_file:
        config = json.load(config_file)
    config["model"] = os.getenv("OPENAI_MODEL", "").strip()
    config["api_key"] = os.getenv("OPENAI_API_KEY", "").strip()
    config["base_url"] = os.getenv("OPENAI_BASE_URL", "").strip() or None
    return config


def prepare_analysis_input(record, config):
    """
    只取新闻标题摘要及来源，不发送作者信息。

    :param record: 清洗后的新闻
    :param config: 分析配置
    :return: 发给模型的新闻字典
    """
    return {
        "title": record["title"],
        "content": record["content"][:config["max_content_chars"]],
        "source": record["source"],
        "publish_time": record["publish_time"],
    }


def analysis_fingerprint(record, config):
    """
    按输入、模型、提示词和输出结构生成缓存指纹。

    :param record: 清洗后的新闻
    :param config: 分析配置
    :return: SHA256 指纹
    """
    payload = {
        "input": prepare_analysis_input(record, config),
        "model": config["model"],
        "base_url": config["base_url"],
        "instructions": config["instructions"],
        "prompt_version": config["prompt_version"],
        "max_output_tokens": config["max_output_tokens"],
        "schema": NewsAnalysis.model_json_schema(),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def save_analysis_results(output_path, results):
    """
    原子保存分析进度，避免中断时破坏已有缓存。

    :param output_path: 输出文件绝对路径
    :param results: 分析状态列表或用量账本字典
    :return: 无
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(output_path),
                                         suffix=".tmp", delete=False) as output_file:
            temporary_path = output_file.name
            json.dump(results, output_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def analyze_news_record(client, record, config, usage=None):
    """
    请求结构化新闻分析，拒绝、不完整或非法输出均视为失败。

    :param client: OpenAI 客户端
    :param record: 清洗后的新闻
    :param config: 分析配置
    :param usage: 用于接收接口返回 token 数量的字典
    :return: 通过本地校验的分析字典
    """
    response = client.responses.create(
        model=config["model"],
        instructions=config["instructions"],
        input=json.dumps(prepare_analysis_input(record, config), ensure_ascii=False),
        text={"format": {"type": "json_schema", "name": "news_analysis", "strict": True,
                         "schema": NewsAnalysis.model_json_schema()}},
        max_output_tokens=config["max_output_tokens"],
        store=False,
    )
    if usage is not None and response.usage is not None:
        usage.update(input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
                     total_tokens=response.usage.total_tokens)
    if response.status != "completed" or not response.output_text:
        raise ValueError("模型拒绝或未完成结构化输出")
    return NewsAnalysis.model_validate_json(response.output_text).model_dump()


@contextmanager
def analysis_run_lock(config):
    """
    阻止多个分析进程同时修改预算和缓存。

    :param config: 分析配置
    :return: 锁持有期间的上下文
    """
    lock_path = os.path.join(PROJECT_PATH, *config["lock_parts"])
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    try:
        lock_file = open(lock_path, "x", encoding="utf-8")
    except FileExistsError:
        raise RuntimeError("已有分析任务或遗留锁；确认没有任务运行后移除 analysis.lock") from None
    try:
        with lock_file:
            lock_file.write(str(os.getpid()))
        yield
    finally:
        os.remove(lock_path)


def load_usage_ledger(config, cached_results):
    """
    读取跨运行预算，首次建立时计入旧缓存中当天已发生的调用。

    :param config: 分析配置
    :param cached_results: 原有分析记录
    :return: 用量账本字典
    """
    usage_path = os.path.join(PROJECT_PATH, *config["usage_parts"])
    if os.path.exists(usage_path):
        with open(usage_path, encoding="utf-8") as usage_file:
            ledger = json.load(usage_file)
        if not isinstance(ledger, dict):
            raise ValueError("用量账本格式错误，停止调用")
        return ledger
    ledger = {}
    for result in cached_results:
        if result.get("analyzed_at") and result.get("status") in ("success", "failed"):
            day = datetime.fromisoformat(result["analyzed_at"]).astimezone(
                timezone(timedelta(hours=8))).date().isoformat()
            stats = ledger.setdefault(day, empty_usage_stats())
            stats["requests"] += 1
            stats["unknown_usage_requests"] += 1
    return ledger


def empty_usage_stats():
    """
    创建一天的请求和 token 计数。

    :return: 初始化用量字典
    """
    return {"requests": 0, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "unknown_usage_requests": 0}


def run_analysis_pipeline(limit=None, dry_run=False):
    """
    分析最新新闻，复用成功缓存，逐条记录失败和未分析状态。

    :param limit: 本次最多请求模型的条数，为空时使用配置值
    :param dry_run: 只检查输入并统计待处理条目，不调用模型或写结果
    :return: 本次快照的分析状态列表，预览时返回待处理新闻列表
    """
    config = load_analysis_config()
    if dry_run:
        return execute_analysis_pipeline(config, limit, dry_run=True)
    with analysis_run_lock(config):
        return execute_analysis_pipeline(config, limit)


def execute_analysis_pipeline(config, limit=None, dry_run=False):
    """
    执行规则筛选并在每日额度内处理新闻，真实运行由入口持锁。

    :param config: 分析配置
    :param limit: 单次最多请求条数
    :param dry_run: 是否仅预览
    :return: 当前新闻分析状态或待调用的预览新闻
    """
    limit = config["max_articles"] if limit is None else limit
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("分析条数必须是正整数")
    input_path = os.path.join(PROJECT_PATH, *config["input_parts"])
    output_path = os.path.join(PROJECT_PATH, *config["output_parts"])
    with open(input_path, encoding="utf-8") as input_file:
        records = json.load(input_file)
    if not isinstance(records, list) or not records:
        raise ValueError("新闻输入为空或不是列表，请先运行新闻采集")
    now = datetime.now(timezone.utc)
    focus_by_id = {record["id"]: classify_news_focus(record, config, now) for record in records}
    records.sort(key=lambda record: (focus_by_id[record["id"]]["priority"],
                                    -datetime.fromisoformat(record["publish_time"]).timestamp()))
    cached_results = []
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as cached_file:
            cached_results = json.load(cached_file)
        if not isinstance(cached_results, list):
            raise ValueError("分析缓存格式错误，请检查输出文件")
    cached_by_key = {}
    cache_path = os.path.join(PROJECT_PATH, *config["cache_parts"])
    archive = []
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as cache_file:
            archive = json.load(cache_file)
        if not isinstance(archive, list):
            raise ValueError("历史缓存格式错误，停止调用")
    for result in archive + cached_results:
        if result.get("status") == "success":
            NewsAnalysis.model_validate(result["analysis"])
            cached_by_key[(result["id"], result["fingerprint"])] = result
    ledger = load_usage_ledger(config, cached_results)
    usage_path = os.path.join(PROJECT_PATH, *config["usage_parts"])
    day = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    today_usage = ledger.setdefault(day, empty_usage_stats())
    daily_cap = config["daily_max_requests"]
    if daily_cap is not None and (isinstance(daily_cap, bool) or not isinstance(daily_cap, int) or daily_cap < 1):
        raise ValueError("daily_max_requests 必须为正整数或 null（关闭限制）")
    available = limit if daily_cap is None else max(0, daily_cap - today_usage["requests"])
    request_limit = min(limit, available)
    results = []
    pending = []
    for record in records:
        focus = focus_by_id[record["id"]]
        fingerprint = analysis_fingerprint(record, config)
        cached = cached_by_key.get((record["id"], fingerprint))
        if cached is not None:
            results.append(dict(cached, focus=focus))
        else:
            results.append({"id": record["id"], "title": record["title"], "url": record["url"],
                            "source": record["source"], "publish_time": record["publish_time"],
                            "fetched_at": record["fetched_at"], "fingerprint": fingerprint,
                            "model": config["model"], "prompt_version": config["prompt_version"],
                            "status": "pending" if focus["selected"] else "filtered", "focus": focus,
                            "analysis": None, "analyzed_at": None, "error": None, "usage": None})
            if focus["selected"]:
                pending.append((record, results[-1]))
    filtered_count = sum(result["status"] == "filtered" for result in results)
    logger.info("新闻 %s 条；规则过滤 %s 条；复用 %s 条；待分析 %s 条；本次可请求 %s 条",
                len(records), filtered_count, sum(result["status"] == "success" for result in results),
                len(pending), min(request_limit, len(pending)))
    logger.info("北京时间 %s：今日已请求 %s/%s 次；已知 token %s；用量未知 %s 次",
                day, today_usage["requests"], "不限" if daily_cap is None else daily_cap,
                today_usage["total_tokens"], today_usage["unknown_usage_requests"])
    if dry_run:
        for record, result in pending[:min(limit, 10)]:
            logger.info("候选：%s | %s | %s", result["focus"]["entities"],
                        result["focus"]["symbols"], record["title"])
        logger.info("离线预览完成，未调用模型、未写入分析结果")
        return [record for record, result in pending[:request_limit]]
    if pending and request_limit and (not config["api_key"] or not config["model"]):
        raise ValueError("请在本地 .env 配置 OPENAI_API_KEY 和 OPENAI_MODEL；可用 --dry-run 离线预览")
    if pending and request_limit:
        with OpenAI(api_key=config["api_key"], base_url=config["base_url"],
                    timeout=config["timeout"], max_retries=0) as client:
            for record, result in pending[:request_limit]:
                current_day = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()
                today_usage = ledger.setdefault(current_day, empty_usage_stats())
                if daily_cap is not None and today_usage["requests"] >= daily_cap:
                    break
                today_usage["requests"] += 1
                today_usage["unknown_usage_requests"] += 1
                save_analysis_results(usage_path, ledger)
                usage = {}
                try:
                    result["analysis"] = analyze_news_record(client, record, config, usage)
                    result["status"] = "success"
                except (APIError, ValueError, TypeError) as error:
                    result["status"] = "failed"
                    result["error"] = f"{type(error).__name__}：模型请求或输出校验失败，请检查凭据、额度、模型及结构化输出支持"
                    logger.error("新闻 %s 分析失败；未记录模型响应正文", record["id"],
                                 exc_info=(RuntimeError, RuntimeError(result["error"]), None))
                result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
                if usage:
                    result["usage"] = usage
                    today_usage["unknown_usage_requests"] -= 1
                    for field in ("input_tokens", "output_tokens", "total_tokens"):
                        today_usage[field] += usage[field]
                save_analysis_results(usage_path, ledger)
                if result["status"] == "success":
                    cached_by_key[(result["id"], result["fingerprint"])] = result
                    save_analysis_results(cache_path, list(cached_by_key.values()))
                save_analysis_results(output_path, results)
    else:
        save_analysis_results(usage_path, ledger)
        save_analysis_results(cache_path, list(cached_by_key.values()))
        save_analysis_results(output_path, results)
        if pending:
            logger.info("今日额度已用完，保留待分析状态，下一个北京时间自然日恢复")
    logger.info("分析结果已保存：%s", output_path)
    if pending and request_limit and all(result["status"] == "failed" for record, result in pending[:request_limit]):
        raise RuntimeError("本次模型请求全部失败，失败状态已保存")
    return results
