#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/7 10:49
# software:Vscode
# brief :统一加载业务配置、币种定义和本地环境变量

import os

from dotenv import load_dotenv

from private_module.project_io import project_path, read_json


def load_project_config(name):
    """
    加载指定业务配置，为新闻、分析和流程注入同一份币种定义。

    :param name: 配置名称，不含路径和扩展名
    :return: 独立的配置字典
    """
    if not isinstance(name, str) or not name or not all(character.isascii() and
            (character.isalnum() or character == "_") for character in name):
        raise ValueError("配置名称必须是字母、数字或下划线")
    config = read_json(project_path(["config", name + "_config.json"]))
    if name in ("news", "analysis", "pipeline"):
        assets = read_json(project_path(["config", "assets_config.json"]))
        if name == "news":
            config["symbol_aliases"] = assets["symbol_aliases"]
        elif name == "analysis":
            config["focus"]["symbol_aliases"] = assets["symbol_aliases"]
        else:
            config["symbols"] = list(assets["symbol_aliases"])
    return config


def load_local_environment():
    """
    加载项目本地环境变量，保留进程中已经设置的值。

    :return: 无
    """
    load_dotenv(project_path([".env"]), override=False)


def load_analysis_config():
    """
    加载分析业务配置及模型访问参数，不记录凭据。

    :return: 分析配置字典
    """
    load_local_environment()
    config = load_project_config("analysis")
    config["model"] = os.getenv("OPENAI_MODEL", "").strip()
    config["api_key"] = os.getenv("OPENAI_API_KEY", "").strip()
    config["base_url"] = os.getenv("OPENAI_BASE_URL", "").strip() or None
    return config
