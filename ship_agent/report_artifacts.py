"""Render self-contained HTML reports for Open WebUI's Artifacts panel."""

from html import escape


def render_carrier_artifact(report: dict) -> str:
    """Keep dates/counts from the tool; require no scripts, assets, or network."""
    stats = report["daily_stats"]
    peak = max(row["possible_aircraft_carrier_count"] for row in stats)
    rows = []
    for row in stats:
        count = row["possible_aircraft_carrier_count"]
        day = escape(row["date"])
        width = 100 * count / max(peak, 1)
        rows.append(
            f'<tr class="{"zero" if count == 0 else "positive"}">'
            f'<th scope="row">{day}</th><td class="plot" aria-hidden="true">'
            f'<span class="bar" style="width:{width:.2f}%"></span></td>'
            f'<td class="count">{count}</td></tr>'
        )
    first, last = escape(report["observed_from"]), escape(report["observed_to"])
    source = "DỮ LIỆU GIẢ LẬP" if report["is_mock"] else "KẾT QUẢ DỰ ĐOÁN"
    gallery = ""
    date_note = "Ngày lấy từ thời gian quan sát trong caption."
    scope_note = ("Phạm vi: các quan sát có metadata, prediction và ảnh đã được nạp; "
                  "không khẳng định bao phủ toàn bộ dữ liệu nguồn.")
    if report.get("is_demo"):
        from .demo_data import demo_gallery
        source = "BỘ DỮ LIỆU DEMO · KẾT QUẢ ĐÃ LƯU"
        gallery = demo_gallery(report)
        date_note = "Giữ nguyên thời gian quan sát từ dữ liệu nguồn."
        scope_note = ("Phạm vi: tập mẫu demo trích từ ShipClassification, giữ nguyên ảnh và kết quả đã lưu. "
                      "Bí danh DEMO là mã quan sát trong bản trình diễn, không phải tên tàu thực tế.")
    empty = ('<p class="empty">Không có lượt dự đoán tàu sân bay trong khoảng ngày.</p>'
             if report["total_detections"] == 0 else "")
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Báo cáo lượt phát hiện nghi là tàu sân bay</title>
<style>
  :root {{ color-scheme: light dark; font-family: system-ui, sans-serif;
    --bg: #f3f6fb; --card: #fff; --text: #172033; --muted: #54647b;
    --line: #dce4ef; --accent: #2563eb; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); padding: 24px; }}
  main {{ max-width: 960px; margin: auto; }}
  .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 700; letter-spacing: .08em; }}
  h1 {{ font-size: clamp(22px, 4vw, 32px); line-height: 1.2; margin: 12px 0; }}
  p {{ line-height: 1.6; }}
  .muted, footer {{ color: var(--muted); }}
  .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 24px 0; }}
  .metric, section {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 20px; }}
  .metric strong {{ display: block; font-size: 30px; margin-top: 6px; }}
  h2 {{ margin: 0 0 12px; font-size: 20px; }}
  label {{ cursor: pointer; font-size: 14px; }}
  .scroll {{ overflow-x: auto; margin-top: 16px; }}
  table {{ width: 100%; min-width: 330px; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
  caption {{ text-align: left; color: var(--muted); padding-bottom: 12px; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; }}
  tbody th {{ font-weight: 400; white-space: nowrap; width: 116px; }}
  .plot {{ width: 100%; }}
  .bar {{ display: block; height: 18px; background: var(--accent); border-radius: 3px; }}
  .count {{ text-align: right; white-space: nowrap; font-weight: 600; }}
  #hide-zero:checked ~ .scroll tr.zero {{ display: none; }}
  .empty {{ padding: 12px; border: 1px dashed var(--line); color: var(--muted); }}
  .demo-gallery {{ margin-top: 24px; }}
  .image-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
  figure {{ margin: 0; }}
  figure img {{ width: 100%; height: 240px; object-fit: contain; image-rendering: pixelated; background: #101827; border-radius: 10px; }}
  figcaption {{ padding-top: 10px; font-size: 14px; line-height: 1.5; }}
  footer {{ font-size: 13px; margin: 20px 0; }}
  @media (max-width: 540px) {{ body {{ padding: 12px; }} .metrics {{ grid-template-columns: 1fr; }} }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #101827; --card: #192438;
    --text: #e5edf8; --muted: #a8b8ce; --line: #344259; --accent: #79a7ff; }} }}
</style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">VESSELWATCH · {source}</div>
    <h1>Lượt phát hiện nghi là tàu sân bay</h1>
    <p class="muted">{first} → {last} · {date_note}</p>
  </header>
  <div class="metrics">
    <div class="metric">Tổng lượt phát hiện<strong>{report["total_detections"]}</strong></div>
    <div class="metric">Số ngày báo cáo<strong>{len(stats)}</strong></div>
    <div class="metric">Cao nhất một ngày<strong>{peak}</strong></div>
  </div>
  <section aria-labelledby="daily-heading">
    <h2 id="daily-heading">Biểu đồ và số liệu theo ngày</h2>
    <p class="muted">Chỉ đếm lượt được mô hình phân loại là tàu sân bay.</p>
    {empty}
    <input type="checkbox" id="hide-zero">
    <label for="hide-zero">Ẩn ngày không có lượt phát hiện</label>
    <div class="scroll">
      <table>
        <caption>Mỗi hàng là một ngày; độ dài cột tỷ lệ với số lượt phát hiện.</caption>
        <thead><tr><th scope="col">Ngày</th><th scope="col">Biểu đồ</th><th scope="col">Số lượt</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </section>
  {gallery}
  <footer>
    <p>Mỗi ảnh quan sát được đếm riêng. Đây là số lượt phát hiện, không phải số tàu duy nhất
    hay xác nhận tàu sân bay thực tế. Không suy ra mức độ hoạt động tàu từ biến động số lượt.</p>
    <p>{scope_note}</p>
  </footer>
</main>
</body>
</html>"""
