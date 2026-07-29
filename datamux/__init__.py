"""datamux 多源金融数据汇聚系统。"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["FeedHandler", "__version__"]


def __getattr__(name: str):
    """惰性导出顶层符号，避免导入轻量子模块时被可选依赖阻塞。"""
    if name == "FeedHandler":
        from datamux.handler import FeedHandler

        return FeedHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
