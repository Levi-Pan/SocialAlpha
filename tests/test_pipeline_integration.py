#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:55
# software:Vscode
# brief :验证统一配置、旧入口兼容和默认研究流程无需联网

import os
import tempfile
import unittest
from unittest.mock import patch

from app.news_run import run_news_pipeline
from app.market_run import run_market_pipeline
from app.pipeline_run import main, run_pipeline
from crawler import news_pipeline
from market_data import market_pipeline
from pipeline import research_pipeline
from private_module.project_config import load_project_config
from private_module.project_io import read_json, write_json_atomic


class PipelineIntegrationTests(unittest.TestCase):
    """验证职责迁移后的入口兼容、统一配置和离线运行边界。"""

    def test_shared_asset_config_is_consistent_and_independent(self):
        """
        验证新闻识别、分析筛选与行情流程使用相同币种，调用间配置不共享可变状态。

        :return: 无
        """
        news = load_project_config("news")
        analysis = load_project_config("analysis")
        pipeline = load_project_config("pipeline")
        self.assertEqual(news["symbol_aliases"], analysis["focus"]["symbol_aliases"])
        self.assertEqual(list(news["symbol_aliases"]), pipeline["symbols"])
        news["symbol_aliases"]["BTC"].append("temporary_alias")
        self.assertNotIn("temporary_alias", load_project_config("news")["symbol_aliases"]["BTC"])
        with self.assertRaises(ValueError):
            load_project_config("../assets")

    def test_existing_entry_imports_remain_compatible(self):
        """
        验证旧入口仍导出原有业务函数，实际执行指向迁移后的模块。

        :return: 无
        """
        self.assertIs(run_news_pipeline, news_pipeline.run_news_pipeline)
        self.assertIs(run_market_pipeline, market_pipeline.run_market_pipeline)
        self.assertIs(run_pipeline, research_pipeline.run_pipeline)

    def test_cli_parameters_preserve_existing_behavior(self):
        """
        验证新旧统一入口共用参数解析，传递的开关和分析额度保持一致。

        :return: 无
        """
        with patch("app.pipeline_run.configure_logging"), patch("app.pipeline_run.run_pipeline") as run:
            main(["--refresh-news", "--analyze", "--limit", "3", "--backtest", "--refresh-market"])
        run.assert_called_once_with(True, True, True, 3, True)

    def test_default_run_saves_reports_without_fetching_or_model_calls(self):
        """
        验证默认流程仅处理本地分析，生成各类输出且追加信号历史，不调用采集或模型。

        :return: 无
        """
        config = load_project_config("pipeline")
        with tempfile.TemporaryDirectory() as temporary_path:
            input_path = os.path.join(temporary_path, *config["analysis_parts"])
            write_json_atomic(input_path, [])
            with patch("pipeline.research_pipeline.project_path", side_effect=lambda parts: os.path.join(temporary_path, *parts)), \
                    patch("pipeline.research_pipeline.run_news_pipeline") as news, \
                    patch("pipeline.research_pipeline.run_market_pipeline") as market, \
                    patch("pipeline.research_pipeline.run_analysis_pipeline") as analyze, \
                    self.assertLogs("pipeline.research_pipeline", level="INFO"):
                first = run_pipeline()
                second = run_pipeline(backtest=True)
            news.assert_not_called()
            market.assert_not_called()
            analyze.assert_not_called()
            self.assertEqual(len(first["report"]["coins"]), len(config["symbols"]))
            self.assertEqual(first["backtest"], None)
            self.assertEqual(second["backtest"]["status"], "missing_market_data")
            history = read_json(os.path.join(temporary_path, *config["signal_history_parts"]))
            self.assertEqual(len(history), 2 * len(config["symbols"]))
            for signal in history:
                self.assertIsNone(signal["target_weight"])
                self.assertIn("report_as_of", signal)
            self.assertTrue(os.path.exists(os.path.join(temporary_path, *config["report_markdown_parts"])))
