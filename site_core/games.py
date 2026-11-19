"""每日小游戏共用的本地日期与连续完成天数。"""

from datetime import date, datetime, timedelta


def game_date(value=None):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def daily_streaks(completed_days, on_date=None):
    """输入为按日期升序、不重复的胜利或完成日；返回当前和历史最长天数。"""
    previous = None
    run = longest = 0
    for day in completed_days:
        run = run + 1 if previous is not None and (day - previous).days == 1 else 1
        longest = max(longest, run)
        previous = day
    if previous is not None:
        today = game_date(on_date)
        if previous in (today, today - timedelta(days=1)):
            return run, longest
    return 0, longest
