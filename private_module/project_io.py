#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:PZW
# datetime:2026/10/6 15:43
# software:Vscode
# brief :提供项目绝对路径配置读取和原子文件保存

import json
import os
import tempfile


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_path(parts):
    """
    将项目内配置路径转换为绝对路径，拒绝越出项目目录。

    :param parts: 项目路径片段列表
    :return: 项目内绝对路径
    """
    if not isinstance(parts, list) or not parts or any(not isinstance(part, str) for part in parts):
        raise ValueError("项目路径配置必须为非空字符串列表")
    path = os.path.abspath(os.path.join(PROJECT_PATH, *parts))
    if os.path.commonpath([PROJECT_PATH, path]) != PROJECT_PATH:
        raise ValueError("输出路径不允许越出项目目录")
    return path


def read_json(path):
    """
    读取 UTF-8 JSON 文件。

    :param path: 文件绝对路径
    :return: JSON 内容
    """
    with open(path, encoding="utf-8") as input_file:
        return json.load(input_file)


def write_text_atomic(path, text):
    """
    在目标目录原子写入文本文件。

    :param path: 文件绝对路径
    :param text: 文本内容
    :return: 无
    """
    if not os.path.isabs(path):
        raise ValueError("保存文件必须使用绝对路径")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path),
                                         suffix=".tmp", delete=False) as output_file:
            temporary_path = output_file.name
            output_file.write(text)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def write_json_atomic(path, data):
    """
    原子保存 JSON 内容。

    :param path: 文件绝对路径
    :param data: 可序列化内容
    :return: 无
    """
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
