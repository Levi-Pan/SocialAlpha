#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:26
# software:Vscode
# brief :验证社媒解析、来源归因、新闻隔离和币种均衡分析

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import requests

from app.news_run import run_news_pipeline
from crawler.news_crawler import parse_news_feed
from crawler.social_crawler import fetch_social_posts, fetch_x_account, parse_telegram_page
from processor.news_analyzer import order_pending_by_coverage
from processor.news_focus import classify_news_focus
from processor.news_processor import clean_news_posts
from private_module.project_config import load_project_config
from reporting.daily_report import build_daily_report, render_report_markdown


class SocialSourceTests(unittest.TestCase):
    """验证不可信社媒内容与正式新闻计分之间的边界。"""

    def setUp(self):
        """
        加载配置和固定 UTC 观察时间。

        :return: 无
        """
        self.config = load_project_config("analysis")
        self.now = datetime(2026, 10, 7, 2, tzinfo=timezone.utc)

    def test_atom_preserves_published_time_and_post_url(self):
        """
        验证 Atom 不用较新的更新时间替代发布时间，清洗保留社区身份。

        :return: 无
        """
        feed = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>DOGE payment adoption</title><published>2026-10-07T00:00:00Z</published>
          <updated>2026-10-07T01:00:00Z</updated><content type="html">&lt;p&gt;Dogecoin payments&lt;/p&gt;</content>
          <link rel="self" href="https://example.test/feed"/>
          <link rel="alternate" href="https://example.test/post?utm_source=reddit"/>
        </entry></feed>'''
        records = parse_news_feed(feed, "reddit_dogecoin", self.now.isoformat(), 30)
        records[0].update(platform="reddit", content_kind="community")
        cleaned = clean_news_posts(records, self.config["focus"]["symbol_aliases"])[0]
        self.assertEqual(cleaned["publish_time"], "2026-10-07T00:00:00+00:00")
        self.assertEqual(cleaned["url"], "https://example.test/post")
        self.assertEqual(cleaned["content"], "Dogecoin payments")
        self.assertEqual(cleaned["platform"], "reddit")
        self.assertEqual(cleaned["mention_symbol"], ["DOGE"])
        self.assertEqual(classify_news_focus(cleaned, self.config, self.now)["attribution"], "community_post")

    def test_rss_compatibility_and_dtd_rejection(self):
        """
        验证旧 RSS 来源兼容，危险 XML 声明仍被拒绝。

        :return: 无
        """
        feed = b'<rss><channel><item><title>Bitcoin</title><link>https://example.test</link></item></channel></rss>'
        self.assertEqual(len(parse_news_feed(feed, "media", self.now.isoformat(), 30)), 1)
        with self.assertRaises(ValueError):
            parse_news_feed(b'<!DOCTYPE feed>' + feed, "media", self.now.isoformat(), 30)

    def test_telegram_ignores_navigation_and_undated_media(self):
        """
        验证嵌套正文、消息时间和原帖链接正确，导航与无正文消息不进入数据。

        :return: 无
        """
        page = '''<div>Navigation BNB</div><div data-post="bnbchain/12">
          <div class="tgme_widget_message_text js-message_text">BNB upgrade<br/><b>Mainnet</b> ready</div>
          <span>10000 views</span><time datetime="2026-10-07T00:00:00+00:00">today</time></div>
          <div data-post="bnbchain/13"><time datetime="2026-10-07T01:00:00+00:00"></time></div>'''
        feed = {"channel": "bnbchain", "source": "telegram_bnbchain", "platform": "telegram",
                "content_kind": "official", "url": "https://t.me/s/bnbchain"}
        records = parse_telegram_page(page, feed, self.now.isoformat(), 30)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content"], "BNB upgrade\nMainnet ready")
        self.assertEqual(records[0]["url"], "https://t.me/bnbchain/12")
        self.assertEqual(classify_news_focus(records[0], self.config, self.now)["attribution"], "official_post")

    def test_one_failed_source_does_not_discard_other_posts(self):
        """
        验证限流记录 HTTP 状态，其他来源仍返回真实数据。

        :return: 无
        """
        config = {"enabled": True, "user_agent": "test", "limit_per_source": 30,
                  "feeds": [{"source": name, "platform": "reddit", "content_kind": "community"}
                            for name in ("failed", "working")], "telegram_channels": [],
                  "x": {"enabled": False, "bearer_token_env": "SOCIAL_TEST_TOKEN"}}
        response = Mock(status_code=429)
        feed = b'<rss><channel><item><title>DOGE</title><link>https://example.test/post</link></item></channel></rss>'
        with patch("crawler.social_crawler.read_public_source", side_effect=[
            requests.HTTPError("rate limited", response=response), (feed, "utf-8")
        ]), self.assertLogs("crawler.social_crawler", level="INFO"):
            records, statuses = fetch_social_posts(config)
        self.assertEqual(len(records), 1)
        self.assertEqual(statuses[0]["http_status"], 429)
        self.assertEqual(statuses[1]["status"], "success")

    def test_x_uses_official_read_endpoints_and_post_time(self):
        """
        验证 X 请求使用只读接口、原始时间且不采集转发回复。

        :return: 无
        """
        session = Mock()
        session.get.side_effect = [Mock(json=lambda: {"data": {"id": "123"}}),
                                   Mock(json=lambda: {"data": [{"id": "456", "text": "BNB upgrade",
                                                                "created_at": "2026-10-07T00:00:00Z"}]})]
        records = fetch_x_account(session, "BNBCHAIN", {"timeout": 20},
                                  {"api_base_url": "https://api.x.com/2", "post_base_url": "https://x.com",
                                   "max_results": 20}, "test-token", self.now.isoformat())
        self.assertEqual(records[0]["url"], "https://x.com/BNBCHAIN/status/456")
        self.assertEqual(session.get.call_args.kwargs["params"]["exclude"], "retweets,replies")
        self.assertEqual(session.get.call_args.kwargs["params"]["post.fields"], "created_at")

    def test_community_score_cannot_inflate_news_coverage(self):
        """
        验证社区帖子单独汇总，相同 ID 和低置信度不会增加有效计数。

        :return: 无
        """
        config = {"symbols": ["DOGE"], "lookback_hours": 24, "confidence_floor": 0.5,
                  "minimum_articles": 2, "max_evidence": 5, "sentiment_values": {"positive": 1}}
        record = {"id": "community", "status": "success", "content_kind": "community", "platform": "reddit",
                  "publish_time": self.now.isoformat(), "fetched_at": self.now.isoformat(), "analyzed_at": self.now.isoformat(),
                  "analysis": {"symbols": ["DOGE"], "sentiment": "positive", "confidence": 0.9, "insufficient_context": False}}
        low = copy.deepcopy(record)
        low["id"] = "low"
        low["analysis"]["confidence"] = 0.1
        report = build_daily_report([record, record, low], config, self.now)
        self.assertEqual(report["coins"][0]["usable_count"], 0)
        self.assertIsNone(report["coins"][0]["sentiment_score"])
        self.assertEqual(report["social_coins"][0]["article_count"], 2)
        self.assertEqual(report["social_coins"][0]["usable_count"], 1)
        self.assertIn("社区情绪（独立统计）", render_report_markdown(report))

    def test_balance_prioritizes_missing_coins_and_fresh_posts(self):
        """
        验证缓存 BTC 已覆盖时优先 DOGE、XRP，并避免旧新闻抢占当日额度。

        :return: 无
        """
        cached = [{"id": str(index), "status": "success", "publish_time": self.now.isoformat(),
                   "fetched_at": self.now.isoformat(), "analyzed_at": self.now.isoformat(),
                   "analysis": {"symbols": ["BTC"], "sentiment": "positive", "confidence": 0.9,
                                "insufficient_context": False}} for index in range(7)]
        pending = []
        for symbol, age in (("BTC", 0), ("DOGE", 1), ("DOGE", 2), ("XRP", 3), ("BNB", 30)):
            record = {"title": symbol, "content": "", "publish_time": (self.now - timedelta(hours=age)).isoformat()}
            pending.append((record, {"focus": classify_news_focus(record, self.config, self.now)}))
        ordered = order_pending_by_coverage(pending, cached, self.config, self.now)
        self.assertEqual([item[0]["title"] for item in ordered[:2]], ["DOGE", "XRP"])
        self.assertEqual(ordered[-1][0]["title"], "BNB")

    def test_low_information_social_posts_are_filtered(self):
        """
        验证重复喊单和问候不消耗模型额度，真实币种事件仍可入选。

        :return: 无
        """
        record = {"title": "Day 189 Posting Until Doge 1$", "content": "DOGE", "content_kind": "community",
                  "publish_time": self.now.isoformat()}
        self.assertEqual(classify_news_focus(record, self.config, self.now)["reason"], "low_information_community_post")
        record["title"] = "Dogecoin payment adoption expands"
        self.assertTrue(classify_news_focus(record, self.config, self.now)["selected"])

    def test_refresh_retains_recent_posts_and_preserves_file_on_failure(self):
        """
        验证订阅翻页不会丢失旧新闻，全部来源失败不能覆盖上一份结果。

        :return: 无
        """
        with tempfile.TemporaryDirectory() as temporary_path:
            os.makedirs(os.path.join(temporary_path, "config"))
            news_config = {"symbol_aliases": self.config["focus"]["symbol_aliases"],
                           "retention_hours": 48, "output_parts": ["data", "news_clean.json"]}
            with open(os.path.join(temporary_path, "config", "news_config.json"), "w", encoding="utf-8") as config_file:
                json.dump(news_config, config_file)
            with open(os.path.join(temporary_path, "config", "social_config.json"), "w", encoding="utf-8") as config_file:
                json.dump({"status_parts": ["data", "social_source_status.json"]}, config_file)
            now = datetime.now(timezone.utc).isoformat()
            raw = {"source": "media", "title": "XRP update", "content": "XRP", "url": "https://example.test/first",
                   "publish_time": now, "fetched_at": now}
            with patch("crawler.news_pipeline.load_project_config", side_effect=lambda name: news_config if name == "news" else
                       {"status_parts": ["data", "social_source_status.json"]}), \
                    patch("crawler.news_pipeline.project_path", side_effect=lambda parts: os.path.join(temporary_path, *parts)), \
                    patch("crawler.news_pipeline.fetch_social_posts", return_value=([], [])), \
                    patch("crawler.news_pipeline.fetch_news_posts", return_value=[raw]) as fetch:
                first = run_news_pipeline()
                fetch.return_value = [dict(raw, title="SOL update", content="SOL", url="https://example.test/second")]
                second = run_news_pipeline()
                self.assertEqual(len(second), 2)
                retained = next(record for record in second if record["id"] == first[0]["id"])
                self.assertEqual(retained["fetched_at"], first[0]["fetched_at"])
                output_path = os.path.join(temporary_path, "data", "news_clean.json")
                with open(output_path, "rb") as output_file:
                    previous = output_file.read()
                fetch.side_effect = RuntimeError("all feeds failed")
                with self.assertLogs("crawler.news_pipeline", level="ERROR"), self.assertRaises(RuntimeError):
                    run_news_pipeline()
                with open(output_path, "rb") as output_file:
                    self.assertEqual(previous, output_file.read())
