"""时间范围解析工具 - 从用户输入中解析自然语言时间表达"""
import datetime
from typing import Tuple


def parse_time_range(user_input: str) -> Tuple[datetime.date, datetime.date, str]:
    """从用户输入中解析时间范围，返回 (start_date, end_date, 描述文字)

    支持：今天、昨天、本周、上周、本月、上月，兜底近7天。
    """
    today = datetime.date.today()

    if "今天" in user_input or "今日" in user_input:
        return today, today, f"今天（{today}）"

    if "昨天" in user_input or "昨日" in user_input:
        y = today - datetime.timedelta(days=1)
        return y, y, f"昨天（{y}）"

    if "上周" in user_input:
        last_monday = today - datetime.timedelta(days=today.weekday() + 7)
        last_sunday = last_monday + datetime.timedelta(days=6)
        return last_monday, last_sunday, f"上周（{last_monday} ~ {last_sunday}）"

    if "本月" in user_input:
        first = today.replace(day=1)
        return first, today, f"本月（{first} ~ {today}）"

    if "上月" in user_input or "上个月" in user_input:
        first_this = today.replace(day=1)
        last_month_end = first_this - datetime.timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start, last_month_end, f"上月（{last_month_start} ~ {last_month_end}）"

    if "本周" in user_input or "这周" in user_input:
        monday = today - datetime.timedelta(days=today.weekday())
        return monday, today, f"本周（{monday} ~ {today}）"

    # 兜底：近7天
    start = today - datetime.timedelta(days=6)
    return start, today, f"近7天（{start} ~ {today}）"
