#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:44
# software:Vscode
# brief :按可知时间汇总币种新闻情绪、重点对象动态和可追溯依据

import math
from collections import Counter
from datetime import datetime, timedelta, timezone


def _parse_time(value):
    """
    解析有时区的时间，拒绝无法确定时区的记录。

    :param value: ISO 时间字符串或 datetime 对象
    :return: UTC 时间，无法解析时返回 None
    """
    try:
        parsed_time = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            return None
        return parsed_time.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _confidence(value):
    """
    校验模型置信度。

    :param value: 置信度字段
    :return: 有限且处于零到一之间的浮点数，非法时返回 None
    """
    if isinstance(value, bool):
        return None
    try:
        confidence = float(value)
        return confidence if math.isfinite(confidence) and 0 <= confidence <= 1 else None
    except (TypeError, ValueError):
        return None


def _evidence(record, known_at, importance_weight=1.0):
    """
    提取可以追溯至原文的新闻依据。

    :param record: 单条成功分析记录
    :param known_at: 新闻和分析均可知的时间
    :param importance_weight: 新闻对象重要性权重
    :return: 新闻依据字典
    """
    analysis = record.get("analysis") or {}
    focus = record.get("focus") or {}
    return {
        "id": record.get("id"),
        "title": record.get("title", ""),
        "url": record.get("url", ""),
        "source": record.get("source", ""),
        "platform": record.get("platform", "news"),
        "content_kind": record.get("content_kind", "media"),
        "summary": analysis.get("summary", ""),
        "known_at": known_at.isoformat(),
        "entities": focus.get("entities") or [],
        "attribution": focus.get("attribution", "unknown"),
        "sentiment": analysis.get("sentiment", "unknown"),
        "confidence": analysis.get("confidence"),
        "insufficient_context": analysis.get("insufficient_context", True),
        "importance_weight": importance_weight,
    }


def _importance_weight(record, default_weight, entity_weights):
    """
    按重点对象取单条新闻最大重要性权重，不叠加多个对象的权重。

    :param record: 新闻分析记录
    :param default_weight: 普通新闻权重
    :param entity_weights: 重点对象权重字典
    :return: 单条新闻重要性权重
    """
    entities = (record.get("focus") or {}).get("entities") or []
    return max([default_weight] + [entity_weights.get(entity, default_weight) for entity in entities])


def build_daily_report(analyses, config, now=None):
    """
    汇总时间窗口内已成功分析的新闻，不调用模型或推断交易方向。

    :param analyses: 新闻分析记录列表
    :param config: 币种、窗口、情绪映射、证据数量及置信度门槛配置
    :param now: 有时区的观察时刻，默认 UTC 当前时间
    :return: 币种汇总、重点对象动态及计算方法组成的报告字典
    """
    as_of = _parse_time(now if now is not None else datetime.now(timezone.utc))
    if as_of is None:
        raise ValueError("观察时间必须包含有效时区")
    lookback_hours = float(config["lookback_hours"])
    confidence_floor = float(config["confidence_floor"])
    minimum_articles = int(config["minimum_articles"])
    max_evidence = int(config["max_evidence"])
    if not math.isfinite(lookback_hours) or lookback_hours <= 0 or not 0 <= confidence_floor <= 1 or minimum_articles < 1 or max_evidence < 0:
        raise ValueError("报告窗口、置信度、最少文章数或证据上限配置无效")
    sentiment_values = config["sentiment_values"]
    default_weight = float(config.get("default_news_weight", 1.0))
    entity_weights = {entity: float(weight) for entity, weight in config.get("entity_weights", {}).items()}
    if any(not math.isfinite(weight) or weight <= 0 for weight in [default_weight] + list(entity_weights.values())):
        raise ValueError("新闻重要性权重必须是有限正数")
    symbols = list(dict.fromkeys(config["symbols"]))
    window_start = as_of - timedelta(hours=lookback_hours)
    eligible = []
    seen = set()
    for record in analyses:
        if (record.get("content_kind") == "community") != config.get("_community_only", False):
            continue
        if record.get("status") != "success" or not isinstance(record.get("analysis"), dict):
            continue
        published_at = _parse_time(record.get("publish_time"))
        fetched_at = _parse_time(record.get("fetched_at"))
        analyzed_at = _parse_time(record.get("analyzed_at"))
        if published_at is None or fetched_at is None or analyzed_at is None:
            continue
        known_at = max(fetched_at, analyzed_at)
        if known_at > as_of or not window_start <= published_at <= as_of:
            continue
        identity = record.get("id") or record.get("url")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        eligible.append((record, known_at))
    eligible.sort(key=lambda item: item[1], reverse=True)
    coins = []
    for symbol in symbols:
        mentions = [(record, known_at) for record, known_at in eligible if symbol in (record["analysis"].get("symbols") or [])]
        sentiment_counts = Counter()
        events = Counter()
        weighted_sum = 0.0
        total_confidence = 0.0
        usable_count = 0
        for record, known_at in mentions:
            analysis = record["analysis"]
            sentiment = analysis.get("sentiment", "unknown")
            sentiment_counts[sentiment] += 1
            events[analysis.get("event_type", "unknown")] += 1
            confidence = _confidence(analysis.get("confidence"))
            if sentiment == "unknown" or sentiment not in sentiment_values or analysis.get("insufficient_context", True) is not False or confidence is None or confidence <= 0 or confidence < confidence_floor:
                continue
            usable_count += 1
            importance_weight = _importance_weight(record, default_weight, entity_weights)
            effective_weight = confidence * importance_weight
            weighted_sum += float(sentiment_values[sentiment]) * effective_weight
            total_confidence += effective_weight
        coins.append({
            "symbol": symbol,
            "article_count": len(mentions),
            "usable_count": usable_count,
            "sentiment_counts": dict(sentiment_counts),
            "sentiment_score": round(weighted_sum / total_confidence, 6) if total_confidence else None,
            "coverage": "sufficient" if usable_count >= minimum_articles else "data_insufficient",
            "events": dict(events),
            "evidence": [_evidence(record, known_at, _importance_weight(record, default_weight, entity_weights))
                         for record, known_at in mentions[:max_evidence]],
        })
    focus_entities = set(config.get("focus_entities", []))
    focus_updates = [_evidence(record, known_at, _importance_weight(record, default_weight, entity_weights))
                     for record, known_at in eligible if focus_entities.intersection((record.get("focus") or {}).get("entities") or [])]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "window_start": window_start.isoformat(),
        "coins": coins,
        "focus_updates": focus_updates[:max_evidence],
        "methodology": {
            "lookback_hours": lookback_hours,
            "minimum_articles": minimum_articles,
            "confidence_floor": confidence_floor,
            "sentiment_values": dict(sentiment_values),
            "default_news_weight": default_weight,
            "entity_weights": entity_weights,
            "availability": "仅使用发布时间处于窗口内，且采集与分析均已完成的记录；缺少时间的记录排除。",
            "score": "情绪分数 = Σ(情绪值 × 模型置信度 × 新闻重要性权重) / Σ(模型置信度 × 新闻重要性权重)。多对象取最大权重，不重复叠加。未知、上下文不足和低置信度文章不计分。",
            "limitation": "文章总体情绪不代表其中每个币种的独立方向；该分数是新闻情绪指标，不是价格预测或交易建议。",
        },
    }
    if not config.get("_community_only", False):
        report["social_coins"] = build_daily_report(analyses, dict(config, _community_only=True), as_of)["coins"]
    return report


def _markdown_text(value):
    """
    转义 Markdown 表格中的文本。

    :param value: 待展示字段
    :return: 无换行且已转义分隔符的文本
    """
    return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_report_markdown(report):
    """
    将日报渲染为便于查看的 Markdown。

    :param report: build_daily_report 输出的报告字典
    :return: Markdown 文本
    """
    lines = ["# 币种新闻情绪日报", "", f"观察时刻：{report['as_of']}", "", "| 币种 | 相关新闻 | 有效分析 | 情绪分数 | 数据覆盖 |", "| --- | ---: | ---: | ---: | --- |"]
    for coin in report["coins"]:
        score = "—" if coin["sentiment_score"] is None else f"{coin['sentiment_score']:.3f}"
        coverage = "数据充足" if coin["coverage"] == "sufficient" else "数据不足"
        lines.append(f"| {_markdown_text(coin['symbol'])} | {coin['article_count']} | {coin['usable_count']} | {score} | {coverage} |")
    if report.get("collection"):
        lines.extend(["", "## 采集覆盖", "", "按日报发布时间窗口统计；采集和待分析数量不代表通过质量校验。", "",
                      "| 币种 | 新闻与官方公告 | 社区帖子 | 待分析候选 |", "| --- | ---: | ---: | ---: |"])
        for coin in report["collection"]:
            lines.append(f"| {_markdown_text(coin['symbol'])} | {coin['news_count']} | {coin['community_count']} | {coin['pending_count']} |")
    if report.get("source_statuses"):
        lines.extend(["", "## 社媒来源状态", "", "来源读取成功不代表窗口内有新消息。", "",
                      "| 来源 | 状态 | 读取条数 | 最新原帖发布时间 |", "| --- | --- | ---: | --- |"])
        for source in report["source_statuses"]:
            status = source["status"] + (f" HTTP {source['http_status']}" if source.get("http_status") else "")
            lines.append(f"| {_markdown_text(source['source'])} | {_markdown_text(status)} | {source['count']} | {_markdown_text(source.get('latest_publish_time'))} |")
    weights_text = "、".join(f"{entity} {weight:g} 倍" for entity, weight in report["methodology"]["entity_weights"].items())
    lines.extend(["", report["methodology"]["limitation"], "",
                  f"计分权重：普通新闻 {report['methodology']['default_news_weight']:g} 倍；{weights_text or '无额外对象加权'}。按置信度与重要性加权平均，提及重点对象不代表其本人发出建议。",
                  "", "## 币种依据", ""])
    for coin in report["coins"]:
        lines.extend([f"### {_markdown_text(coin['symbol'])}", ""])
        if not coin["evidence"]:
            lines.extend(["窗口内无可用新闻依据。", ""])
        for evidence in coin["evidence"]:
            lines.extend([f"- {_markdown_text(evidence['title'])}（{_markdown_text(evidence['source'])}；{_markdown_text(evidence['attribution'])}）", f"  {_markdown_text(evidence['summary'])}", f"  原文：{evidence['url']}", f"  可知时间：{evidence['known_at']}", ""])
    lines.extend(["## 社区情绪（独立统计）", "", "社区帖子不计入上方有效新闻数量或研究信号，观点不代表已核实事实。", "",
                  "| 币种 | 相关帖子 | 有效分析 | 社区情绪分数 |", "| --- | ---: | ---: | ---: |"])
    for coin in report.get("social_coins", []):
        score = "—" if coin["sentiment_score"] is None else f"{coin['sentiment_score']:.3f}"
        lines.append(f"| {_markdown_text(coin['symbol'])} | {coin['article_count']} | {coin['usable_count']} | {score} |")
    lines.extend(["", "### 社区原帖依据", ""])
    seen_social = set()
    for coin in report.get("social_coins", []):
        for evidence in coin["evidence"]:
            if evidence["id"] not in seen_social:
                seen_social.add(evidence["id"])
                lines.append(f"- {_markdown_text(evidence['title'])}（{_markdown_text(evidence['source'])}）：{evidence['url']}")
    lines.extend(["", "## 重点对象动态", ""])
    if not report["focus_updates"]:
        lines.extend(["窗口内无重点对象动态。", ""])
    for evidence in report["focus_updates"]:
        lines.extend([f"- {_markdown_text(', '.join(evidence['entities']))}：{_markdown_text(evidence['summary'])}（{_markdown_text(evidence['attribution'])}）", f"  原文：{evidence['url']}", ""])
    return "\n".join(lines)
