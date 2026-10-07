#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 20:15
# software:Vscode
# brief :验证普通币种新闻不再被重大事件门槛过滤

import unittest
from datetime import datetime, timedelta, timezone

from processor.news_focus import classify_news_focus
from private_module.project_config import load_project_config


class NewsFocusTests(unittest.TestCase):
    """验证关注对象只作标记，六币种普通新闻均可入选。"""

    def setUp(self):
        """
        加载当前筛选配置和固定时间。

        :return: 无
        """
        self.config = load_project_config("analysis")
        self.now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)

    def classify(self, title, age=0):
        """
        按固定观察时间筛选新闻。

        :param title: 新闻标题
        :param age: 发布时间距观察时间的小时数
        :return: 新闻筛选结果
        """
        return classify_news_focus({"title": title, "content": "",
                                    "publish_time": (self.now - timedelta(hours=age)).isoformat()}, self.config, self.now)

    def test_ordinary_news_for_all_symbols_selected(self):
        """
        验证价格与普通动态无需机构或重大事件关键词也可分析。

        :return: 无
        """
        for symbol in ("BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"):
            self.assertTrue(self.classify(f"{symbol} price slips today")["selected"])

    def test_entities_do_not_displace_ordinary_news(self):
        """
        验证重点对象与普通新闻相同排队优先级，影响仅在报告权重。

        :return: 无
        """
        self.assertEqual(self.classify("CZ discusses Bitcoin")["priority"], self.classify("Bitcoin falls today")["priority"])
        self.assertFalse(self.classify("Bitcoin trading strategy improves")["entities"])

    def test_unrelated_and_stale_news_remain_excluded(self):
        """
        验证无关及过期新闻仍不产生模型调用候选。

        :return: 无
        """
        self.assertFalse(self.classify("Tether methodology changes")["selected"])
        self.assertFalse(self.classify("Bitcoin price rises", age=49)["selected"])
