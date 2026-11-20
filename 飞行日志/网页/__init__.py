# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""web 子包。"""
from .应用 import create_app, APP  # noqa

__all__ = ["create_app", "APP"]