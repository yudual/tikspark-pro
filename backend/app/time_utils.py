"""项目统一时间约定。

所有数据库时间字段和调度计算统一使用北京时间（UTC+8）的 naive datetime。
前端通过浏览器本地时区显示（国内用户即北京时间）。
不要混用 UTC naive 和北京时间 naive 写入同一个数据库。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

BEIJING_UTC_OFFSET = timedelta(hours=8)


def beijing_now() -> datetime:
    return (datetime.now(timezone.utc) + BEIJING_UTC_OFFSET).replace(tzinfo=None)


def from_beijing_epoch(epoch_seconds: float) -> datetime:
    """把带时区的绝对时间点转成北京时间 naive datetime。

    适用于 Cookie 过期时间等“绝对时刻”字段。
    """
    return (datetime.fromtimestamp(epoch_seconds, tz=timezone.utc) + BEIJING_UTC_OFFSET).replace(tzinfo=None)

