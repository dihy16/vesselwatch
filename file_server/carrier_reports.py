"""Count model-positive observations and render daily PNG reports in memory."""

from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO
import json
from threading import Lock
from typing import Iterable


MAX_REPORT_DAYS = 366
_RENDER_LOCK = Lock()


def daily_carrier_report(
    observations: Iterable[dict], observed_from: date, observed_to: date,
) -> dict:
    """Count separate observation IDs, using the already parsed caption date."""
    days = (observed_to - observed_from).days + 1
    if not 1 <= days <= MAX_REPORT_DAYS:
        raise ValueError("Khoảng ngày phải có từ 1 đến 366 ngày, gồm cả hai đầu mốc.")
    counts = Counter()
    seen = set()
    for observation in observations:
        day = date.fromisoformat(observation["observed_date"])
        if not observed_from <= day <= observed_to:
            continue
        identity = observation["observation_id"]
        if identity in seen:
            continue
        seen.add(identity)
        if observation["classification"] == "aircraft_carrier":
            counts[day.isoformat()] += 1
    daily_stats = [
        {"date": (observed_from + timedelta(days=offset)).isoformat(),
         "possible_aircraft_carrier_count": counts[
             (observed_from + timedelta(days=offset)).isoformat()
         ]}
        for offset in range(days)
    ]
    report = {
        "observed_from": observed_from.isoformat(),
        "observed_to": observed_to.isoformat(),
        "timezone": "UTC",
        "count_unit": "detections",
        "classification": "aircraft_carrier",
        "total_detections": sum(counts.values()),
        "daily_stats": daily_stats,
    }
    # Bind the chart URL to these exact dates/counts, even after a server restart.
    report["report_id"] = sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def render_carrier_chart(report: dict) -> bytes:
    """Use Matplotlib's headless canvas; never write images or change its backend."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator

    stats = report["daily_stats"]
    values = [row["possible_aircraft_carrier_count"] for row in stats]
    with _RENDER_LOCK:
        figure = Figure(figsize=(12, 4.8), dpi=140, layout="constrained")
        FigureCanvasAgg(figure)
        axes = figure.subplots()
        axes.bar(range(len(stats)), values, color="#2563eb", width=0.8, zorder=3)
        step = max(1, (len(stats) + 11) // 12)
        ticks = list(range(0, len(stats), step))
        if ticks[-1] != len(stats) - 1:
            ticks.append(len(stats) - 1)
        axes.set_xticks(ticks, [stats[i]["date"] for i in ticks], rotation=35, ha="right")
        axes.set_xlim(-0.7, len(stats) - 0.3)
        axes.set_ylim(0, max(1, max(values)) * 1.2)
        axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        axes.set_xlabel("Ngày quan sát (UTC)")
        axes.set_ylabel("Số lượt phát hiện")
        axes.set_title(
            "Lượt phát hiện nghi là tàu sân bay theo ngày\n"
            f"{report['observed_from']} – {report['observed_to']} | "
            f"Tổng: {report['total_detections']} lượt — kết quả dự đoán",
            loc="left", fontsize=12, pad=14,
        )
        axes.grid(axis="y", alpha=0.2, zorder=0)
        axes.spines[["top", "right"]].set_visible(False)
        if not any(values):
            axes.text(0.5, 0.5, "Không có lượt dự đoán tàu sân bay trong khoảng ngày",
                      transform=axes.transAxes, ha="center", color="#64748b")
        output = BytesIO()
        figure.savefig(output, format="png")
        return output.getvalue()
