#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:45
# software:Vscode
# brief :验证日报时间可知性、置信度过滤和无数据处理

import copy
import unittest
from datetime import datetime, timezone

from reporting.daily_report import build_daily_report, render_report_markdown


class DailyReportTests(unittest.TestCase):
    """验证日报的时间边界、计分和重点对象汇总。"""

    def setUp(self):
        """
        建立可独立复现的报告样本。

        :return: 无
        """
        self.now = datetime(2026, 10, 6, 8, tzinfo=timezone.utc)
        self.config = {
            "symbols": ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"],
            "lookback_hours": 24,
            "sentiment_values": {"positive": 1, "negative": -1, "neutral": 0, "mixed": 0, "unknown": 0},
            "minimum_articles": 2,
            "confidence_floor": 0.5,
            "max_evidence": 5,
            "focus_entities": ["Strategy", "CZ"],
        }
        self.record = {
            "id": "first", "status": "success", "title": "Example", "url": "https://example.test/news",
            "publish_time": "2026-10-06T06:00:00Z", "fetched_at": "2026-10-06T07:00:00Z", "analyzed_at": "2026-10-06T07:30:00Z",
            "focus": {"entities": ["Strategy"], "attribution": "media_report"},
            "analysis": {"symbols": ["BTC"], "sentiment": "positive", "confidence": 0.9, "event_type": "market", "summary": "机构报道", "insufficient_context": False},
        }

    def test_no_future_or_unknown_availability(self):
        """
        验证未来、过期和缺少采集时间的记录不能进入历史报告。

        :return: 无
        """
        records = []
        for index, (field, value) in enumerate([
            ("analyzed_at", "2026-10-06T08:01:00Z"),
            ("fetched_at", "2026-10-06T08:01:00Z"),
            ("publish_time", "2026-10-06T08:01:00Z"),
            ("publish_time", "2026-10-05T07:59:59Z"),
            ("fetched_at", None),
        ]):
            record = copy.deepcopy(self.record)
            record.update({"id": str(index), field: value})
            records.append(record)
        report = build_daily_report(records, self.config, self.now)
        self.assertEqual(report["coins"][0]["article_count"], 0)
        self.assertEqual(report["focus_updates"], [])

    def test_weighted_score_retains_rejected_evidence(self):
        """
        验证低置信度及未知情绪保留计数但不影响加权分数。

        :return: 无
        """
        records = [self.record]
        for identity, sentiment, confidence, insufficient in [
            ("negative", "negative", 0.6, False), ("low", "negative", 0.1, False),
            ("unknown", "unknown", 0.9, False), ("insufficient", "negative", 0.9, True),
        ]:
            record = copy.deepcopy(self.record)
            record["id"] = identity
            record["analysis"].update(sentiment=sentiment, confidence=confidence, insufficient_context=insufficient)
            records.append(record)
        report = build_daily_report(records, self.config, self.now)
        coin = report["coins"][0]
        self.assertEqual(coin["article_count"], 5)
        self.assertEqual(coin["usable_count"], 2)
        self.assertAlmostEqual(coin["sentiment_score"], 0.2)
        self.assertEqual(coin["coverage"], "sufficient")
        self.assertEqual(len(coin["evidence"]), 5)

    def test_missing_is_not_neutral_and_focus_without_symbol(self):
        """
        验证无币种数据不产生中性评分，重点对象可独立展示。

        :return: 无
        """
        record = copy.deepcopy(self.record)
        record["analysis"]["symbols"] = []
        report = build_daily_report([record], self.config, self.now)
        self.assertEqual(len(report["coins"]), 6)
        self.assertIsNone(report["coins"][0]["sentiment_score"])
        self.assertEqual(report["coins"][0]["coverage"], "data_insufficient")
        self.assertEqual(report["focus_updates"][0]["attribution"], "media_report")
        self.assertIn("数据不足", render_report_markdown(report))

    def test_duplicate_and_invalid_confidence(self):
        """
        验证重复记录不增加样本数，非有限置信度不计分。

        :return: 无
        """
        record = copy.deepcopy(self.record)
        record["analysis"]["confidence"] = float("nan")
        report = build_daily_report([record, record], self.config, self.now)
        self.assertEqual(report["coins"][0]["article_count"], 1)
        self.assertEqual(report["coins"][0]["usable_count"], 0)
        self.assertIsNone(report["coins"][0]["sentiment_score"])

    def test_priority_weight_changes_score_not_sample_count(self):
        """
        验证重点新闻略微加权，不增加样本数，不将两对象权重相乘。

        :return: 无
        """
        priority = copy.deepcopy(self.record)
        priority["focus"]["entities"] = ["Strategy", "CZ"]
        ordinary = copy.deepcopy(self.record)
        ordinary.update(id="ordinary", focus={"entities": []})
        ordinary["analysis"]["sentiment"] = "negative"
        config = dict(self.config, default_news_weight=1.0, entity_weights={"Strategy": 1.25, "CZ": 1.25})
        coin = build_daily_report([priority, ordinary], config, self.now)["coins"][0]
        self.assertEqual(coin["usable_count"], 2)
        self.assertAlmostEqual(coin["sentiment_score"], 1 / 9, places=6)
        self.assertEqual(coin["evidence"][0]["importance_weight"], 1.25)

    def test_invalid_priority_weights_rejected(self):
        """
        验证非法权重不会造成无穷或伪造评分。

        :return: 无
        """
        for weight in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                build_daily_report([self.record], dict(self.config, entity_weights={"CZ": weight}), self.now)
