"""时间范围解析工具 - 从用户输入中解析自然语言时间表达"""
import datetime
import re
from typing import Tuple


def parse_time_range(user_input: str) -> Tuple[datetime.date, datetime.date, str]:
    """从用户输入中解析时间范围，返回 (start_date, end_date, 描述文字)

    支持：今天、昨天、本周、上周、本月、上月、X月（如 5月/5月份），兜底近180天。
    """
    today = datetime.date.today()

    m = re.search(r"(\d{1,2})\s*月份?(?!底|初)", user_input)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            year = today.year
            if month > today.month:
                year -= 1
            first = datetime.date(year, month, 1)
            if month == 12:
                last = datetime.date(year, 12, 31)
            else:
                last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
            return first, last, f"{year}年{month}月（{first} ~ {last}）"

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

    # 兜底：近180天（数据为历史经营数据, 7天窗口会永远查空）
    start = today - datetime.timedelta(days=180)
    return start, today, f"近180天（{start} ~ {today}）"
