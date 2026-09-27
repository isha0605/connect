"""Computes a partner's median business-hours response time from actual message data.

Response time = the business-hours gap between a customer's last message and the partner's
first reply, measured across every company thread the partner has participated in over the
last 90 days.  Off-clock hours (outside the replying partner member's configured work
schedule) are subtracted, so a message landing at 11 PM doesn't penalise the partner for
sleeping.  All times are treated as IST (Asia/Kolkata) for now.

Called by a daily scheduled job (see hooks.py → recompute_all_response_times).
"""

import frappe
from datetime import datetime, timedelta

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
ROLLING_WINDOW_DAYS = 90
MIN_SAMPLES = 3


def _minutes_from_hhmm(hhmm):
    parts = (hhmm or "00:00").split(":")
    return int(parts[0]) * 60 + int(parts[1] if len(parts) > 1 else 0)


def _business_minutes_between(start_dt, end_dt, work_start, work_end, work_days):
    """Count minutes between two datetimes that fall inside the given work window.

    Walks day-by-day, clipping each day's work window to [start_dt, end_dt].  A message
    arriving after hours naturally gets zero credit for that day, and the counter only
    starts once the next working day's window opens — no explicit "adjust to next morning"
    step needed.
    """
    if start_dt >= end_dt:
        return 0

    ws_min = _minutes_from_hhmm(work_start)
    we_min = _minutes_from_hhmm(work_end)
    if ws_min >= we_min:
        return 0

    total = 0
    current_date = start_dt.date()
    end_date = end_dt.date()

    while current_date <= end_date:
        day_name = WEEKDAY_NAMES[current_date.weekday()]
        if day_name in work_days:
            day_start = datetime.combine(current_date, datetime.min.time()).replace(
                hour=ws_min // 60, minute=ws_min % 60,
            )
            day_end = datetime.combine(current_date, datetime.min.time()).replace(
                hour=we_min // 60, minute=we_min % 60,
            )
            window_start = max(day_start, start_dt)
            window_end = min(day_end, end_dt)
            if window_start < window_end:
                total += (window_end - window_start).total_seconds() / 60

        current_date += timedelta(days=1)

    return total


def _default_work_settings():
    return {
        "work_start": "09:00",
        "work_end": "18:00",
        "work_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    }


def _collect_response_samples(threads, thread_sides, work_settings, cutoff):
    """Walk messages in each thread and collect business-minutes samples for every
    customer→partner reply transition."""
    samples = []

    for thread_name in threads:
        sides_map = thread_sides.get(thread_name, {})
        messages = frappe.get_all(
            "Connect Message",
            filters={"thread": thread_name, "creation": [">=", cutoff]},
            fields=["sender", "creation"],
            order_by="creation asc",
        )

        last_customer_time = None
        last_side = None

        for msg in messages:
            sender_side = sides_map.get(msg.sender)
            if not sender_side:
                continue

            msg_time = frappe.utils.get_datetime(msg.creation)

            if sender_side == "Customer":
                last_customer_time = msg_time
                last_side = "Customer"
            elif sender_side == "Partner" and last_side == "Customer" and last_customer_time:
                replier_ws = work_settings.get(msg.sender) or _default_work_settings()
                biz_min = _business_minutes_between(
                    last_customer_time, msg_time,
                    replier_ws["work_start"], replier_ws["work_end"], replier_ws["work_days"],
                )
                samples.append(biz_min)
                last_side = "Partner"
                last_customer_time = None

    return samples


def aggregate_samples(samples):
    """Turn raw business-minutes samples into the hours number for the badge, or None."""
    if len(samples) < MIN_SAMPLES:
        return None
    from statistics import median
    median_minutes = median(samples)
    return max(1, round(median_minutes / 60))


def compute_response_time(partner):
    """Compute the response time (in hours) for a partner from their message history.
    Returns an int or None if insufficient data."""
    threads = frappe.get_all("Connect Thread", filters={"partner": partner}, pluck="name")
    if not threads:
        return None

    members = frappe.get_all(
        "Connect Thread Member",
        filters={"thread": ["in", threads]},
        fields=["user", "thread", "side"],
    )
    thread_sides = {}
    for m in members:
        thread_sides.setdefault(m.thread, {})[m.user] = m.side

    partner_users = list({m.user for m in members if m.side == "Partner"})
    if not partner_users:
        return None

    from connect.messaging.doctype.connect_user_settings.connect_user_settings import get_settings_for_users
    work_settings = get_settings_for_users(partner_users)

    cutoff = datetime.now() - timedelta(days=ROLLING_WINDOW_DAYS)
    samples = _collect_response_samples(threads, thread_sides, work_settings, cutoff)

    return aggregate_samples(samples)


def recompute_all_response_times():
    """Scheduled job entry point — recomputes response_time_hours for every partner."""
    partners = frappe.get_all("Partner", pluck="name")
    for partner in partners:
        try:
            hours = compute_response_time(partner)
            if hours is not None:
                frappe.db.set_value("Partner", partner, "response_time_hours", hours, update_modified=False)
        except Exception:
            frappe.log_error(f"Response time computation failed for partner {partner}")
    frappe.db.commit()
