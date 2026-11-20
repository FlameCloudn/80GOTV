"""根据本届日期和保留的活动类型解释赛事状态。"""

from datetime import datetime

from src.website.domains.events.arg_event_service import ARG_EVENT_STATUS, is_arg_event


def add_effective_event_status(event_row, now=None):
    """根据日期计算赛事有效状态"""
    if now is None:
        now = datetime.now()
    event = dict(event_row)
    if is_arg_event(event):
        event["effective_event_status"] = ARG_EVENT_STATUS
        return event
    try:
        end_val = event.get("end_date")
        start_val = event.get("start_date")
        end_dt = (
            datetime.fromisoformat(str(end_val).replace("Z", "+00:00").replace("T", " ")[:19])
            if end_val
            else None
        )
        start_dt = (
            datetime.fromisoformat(str(start_val).replace("Z", "+00:00").replace("T", " ")[:19])
            if start_val
            else None
        )
    except (ValueError, TypeError):
        end_dt = start_dt = None
    if end_dt and end_dt < now:
        event["effective_event_status"] = "completed"
    elif start_dt and start_dt > now:
        event["effective_event_status"] = "upcoming"
    else:
        event["effective_event_status"] = "ongoing"
    return event
