"""Render source-calculated monthly monitoring and validated review evidence as HTML."""

from html import escape
from urllib.parse import urlsplit


LABEL_NAMES = {"aircraft_carrier": "Nghi tàu sân bay", "not_aircraft_carrier": "Nhãn không phải tàu sân bay",
               "unknown": "Chưa có nhãn"}


def _text(value):
    return escape(str(value)) if value is not None else "—"


def _number(value):
    return f"{value:.2f}" if value is not None else "—"


def _url(value):
    try:
        parsed = urlsplit(value or "")
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return escape(value, quote=True)
    except ValueError:
        pass
    return None


def render_monitoring_artifact(report):
    stats, review = report["statistics"], report["review"]
    labels = stats["classification_counts"]
    months = []
    bars = []
    peak = max((max(item["average_daily_count"], item["previous_month"]["average_daily_count"])
                for item in report["monthly_stats"]), default=1) or 1
    for item in report["monthly_stats"]:
        previous = item["previous_month"]
        change = item["comparison"]["average_daily_change_pct"]
        change_text = f"{change:+.2f}%" if change is not None else "Không có nền đối chiếu"
        counts = item["classification_counts"]
        months.append(f'<tr><th>{_text(item["month"])}</th><td>{_text(item["observed_from"])} → '
                      f'{_text(item["observed_to"])}<br>{item["queried_days"]}/{item["calendar_days"]} ngày trong tháng</td>'
                      f'<td>{item["detection_count"]}</td><td>{counts["aircraft_carrier"]}</td>'
                      f'<td>{counts["not_aircraft_carrier"]}</td><td>{counts["unknown"]}</td>'
                      f'<td>{_number(item["average_daily_count"])}</td><td>{_text(previous["month"])}: '
                      f'{previous["detection_count"]} lượt / {previous["queried_days"]} ngày<br>'
                      f'{_number(previous["average_daily_count"])} lượt/ngày</td><td>{change_text}</td></tr>')
        bars.append(f'<div class="bar-row"><strong>{_text(item["month"])}</strong><div>'
                    f'<div class="bar current" style="width:{100 * item["average_daily_count"] / peak:.2f}%"></div>'
                    f'<div class="bar baseline" style="width:{100 * previous["average_daily_count"] / peak:.2f}%"></div>'
                    f'</div><span>{_number(item["average_daily_count"])} / {_number(previous["average_daily_count"])}</span></div>')
    daily = []
    for item in stats["daily_stats"]:
        counts = item["classification_counts"]
        daily.append(f'<tr><th>{_text(item["date"])}</th><td>{item["count"]}</td>'
                     + ''.join(f'<td>{counts[label]}</td>' for label in LABEL_NAMES) + '</tr>')
    sizes = []
    for group, name in (("below_300m", "<300 m"), ("at_least_300m", "≥300 m"), ("missing", "Thiếu chiều dài")):
        sizes.append(f'<tr><th>{escape(name)}</th><td>{stats["length_groups"][group]}</td>'
                     + ''.join(f'<td>{stats["size_classification_counts"][group][label]}</td>' for label in LABEL_NAMES) + '</tr>')
    measurements = []
    for key, name in (("length_m", "Chiều dài (m)"), ("width_m", "Chiều rộng (m)"), ("carrier_score", "Carrier score")):
        item = stats[key]
        measurements.append(f'<tr><th>{name}</th><td>{item["count"]}</td><td>{item["missing_count"]}</td>'
                            + ''.join(f'<td>{_number(item[field])}</td>' for field in ("min", "mean", "median", "max")) + '</tr>')
    cases = []
    for item in review["flags"]:
        row = item["observation"]
        if item["priority"] == 1:
            evidence = f'Chiều dài {_text(row["length_m"])} m &lt;300 m. Chưa đọc ảnh.'
        else:
            visual = item["visual_review"]
            details = [_text(feature) for feature in visual["visible_features"]]
            details.extend(f'{_text(ref["reference_id"])}: {_text(detail)}'
                           for ref in visual["reference_evidence"] for detail in ref["differences"])
            evidence = '<br>'.join(details)
        image_url = _url(item.get("image_url"))
        image = (f'<a href="{image_url}" target="_blank" rel="noopener noreferrer">'
                 f'<img src="{image_url}" loading="lazy" alt="{_text(row["ship_id"])}"></a>') if image_url else ''
        cases.append(f'<article><h3>Ưu tiên {item["priority"]} · {_text(row["ship_id"])}</h3>'
                     f'<p class="id">{_text(item["observation_id"])}</p>{image}'
                     f'<p>Thời gian: {_text(row["observed_at"])}<br>'
                     f'Vị trí: {_text(row["position"]["latitude"])}, {_text(row["position"]["longitude"])}<br>'
                     f'Dài × rộng: {_text(row["length_m"])} × {_text(row["width_m"])} m<br>'
                     f'Nhãn: {_text(row["classification"])} · score: {_text(row["confidence"])}</p>'
                     f'<p>{evidence}</p></article>')
    errors = ''.join(f'<li>{_text(item["observation_id"])}: {_text(item["error"])}</li>' for item in review["errors"])
    unknown = sum(item["decision"] in {"insufficient_image", "inconclusive"} for item in review["unflagged"])
    continuation = f' · next_offset={review["next_offset"]}' if review["next_offset"] is not None else ''
    coverage = "Đã xử lý hết ứng viên" if review["coverage_complete"] else "Chưa xử lý hết ứng viên"
    filters = report["statistics_filters"]
    return f'''<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Báo cáo giám sát tàu theo tháng</title><style>
:root{{font-family:system-ui,sans-serif;color:#172033;background:#f3f6fb;color-scheme:light}}
*{{box-sizing:border-box}}body{{margin:0;padding:24px}}main{{max-width:1200px;margin:auto}}
h1{{font-size:28px;margin:8px 0}}h2{{font-size:20px;margin:0 0 14px}}h3{{font-size:16px;overflow-wrap:anywhere}}
p{{line-height:1.6}}.muted,.id{{color:#58677f}}.id{{font-size:12px;overflow-wrap:anywhere}}
section,.metric,article{{background:white;border:1px solid #dce4ef;border-radius:12px;padding:20px}}
section{{margin-top:20px}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}}
.metric strong{{display:block;font-size:30px;margin-top:8px}}.scroll{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}}
th,td{{padding:10px 9px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}}
tbody th{{font-weight:500}}.monthly{{min-width:930px}}.bar-row{{display:grid;grid-template-columns:80px 1fr 100px;gap:12px;align-items:center;margin:12px 0;font-size:12px}}
.bar{{height:10px;border-radius:3px;margin:3px 0}}.current{{background:#2563eb}}.baseline{{background:#94a3b8}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}
article img{{width:100%;height:180px;object-fit:contain;background:#10202d;border-radius:8px}}article p{{font-size:13px;overflow-wrap:anywhere}}
footer{{color:#58677f;font-size:12px;margin:20px 0;overflow-wrap:anywhere}}
@media(max-width:650px){{body{{padding:12px}}.metrics{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:23px}}section{{padding:14px}}}}
</style></head><body><main>
<header><p class="muted">VESSELWATCH · BÁO CÁO GIÁM SÁT</p><h1>Thống kê và so sánh theo tháng</h1>
<p>{_text(report.get("area_name") or "Toàn bộ nguồn dữ liệu")} · {_text(filters["observed_from"])} → {_text(filters["observed_to"])}</p></header>
<div class="metrics"><div class="metric">Tổng lượt<strong>{stats["detection_count"]}</strong></div>
<div class="metric">Nghi tàu sân bay<strong>{labels["aircraft_carrier"]}</strong></div>
<div class="metric">Nhãn âm<strong>{labels["not_aircraft_carrier"]}</strong></div>
<div class="metric">Chưa có nhãn<strong>{labels["unknown"]}</strong></div></div>
<section><h2>So sánh tháng dương lịch</h2><p class="muted">Xanh: kỳ báo cáo; xám: tháng liền trước cùng vùng. Cột biểu đồ là lượt/ngày.
Tháng lấy một phần ghi rõ ngày truy vấn. Kỳ trước có 0 lượt thì không tính thay đổi phần trăm.</p>
{''.join(bars)}<div class="scroll"><table class="monthly"><thead><tr><th>Tháng</th><th>Phạm vi</th><th>Tổng</th><th>Nghi TSB</th><th>Nhãn âm</th><th>Chưa có nhãn</th><th>Lượt/ngày</th><th>Kỳ đối chiếu</th><th>Thay đổi lượt/ngày</th></tr></thead><tbody>{''.join(months)}</tbody></table></div></section>
<section><h2>Kích thước và kết quả phân loại</h2><div class="scroll"><table><thead><tr><th>Chiều dài</th><th>Tổng</th><th>Nghi TSB</th><th>Nhãn âm</th><th>Chưa có nhãn</th></tr></thead><tbody>{''.join(sizes)}</tbody></table></div>
<div class="scroll"><table><thead><tr><th>Đại lượng</th><th>Có dữ liệu</th><th>Thiếu</th><th>Min</th><th>Trung bình</th><th>Trung vị</th><th>Max</th></tr></thead><tbody>{''.join(measurements)}</tbody></table></div></section>
<section><h2>Trường hợp ưu tiên kiểm tra thủ công</h2><p>Đã xử lý {review["processed_count"]}/{review["total_candidates"]} ứng viên nhãn tàu sân bay trong trang bắt đầu tại {review["offset"]}: sàng lọc kích thước {review["dimension_screened_count"]}, đọc ảnh {review["reviewed_count"]}, lỗi {review["failed_count"]}.
Ưu tiên 1: {review["priority_1_count"]}; ưu tiên 2: {review["priority_2_count"]}; ảnh chưa đủ bằng chứng: {unknown}.</p>
<p class="muted">{coverage}{continuation}. Flags thuộc trang hiện tại; không phải lỗi mô hình đã xác nhận.</p>
<div class="gallery">{''.join(cases) or '<p>Trang này chưa có trường hợp được flag; xem phạm vi và lỗi trước khi kết luận.</p>'}</div>
{('<ul>' + errors + '</ul>') if errors else ''}</section>
<section><h2>Thống kê từng ngày</h2><div class="scroll"><table><thead><tr><th>Ngày</th><th>Tổng</th><th>Nghi TSB</th><th>Nhãn âm</th><th>Chưa có nhãn</th></tr></thead><tbody>{''.join(daily)}</tbody></table></div></section>
<footer><p>Đếm lượt quan sát, không phải tàu duy nhất. Thay đổi lượt/ngày không chứng minh hoạt động tàu tăng/giảm; số ngày truy vấn không đo độ phủ ảnh vệ tinh.
Thiếu tọa độ trong phạm vi: {report["missing_position_count"]}; thiếu tọa độ trong khoảng ngày trước lọc vùng: {report["unlocated_in_date_range_count"]}.</p>
<p>Báo cáo: {_text(report["report_id"])}<br>Snapshot: {_text(report["source_snapshot_id"])}</p></footer>
</main></body></html>'''
