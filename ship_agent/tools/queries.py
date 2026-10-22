"""Count and search observations from the prepared tool snapshot."""

from copy import deepcopy
from datetime import date, timedelta

from langchain_core.tools import ToolException, tool

from ship_agent.tools.schemas import CountShipsInput, SearchShipsInput, Classification
from ship_agent.tools.validation import _date_range


def create_query_tools(context):
    observations, metadata, is_mock = context.observations, context.metadata, context.is_mock

    def latest_in_range(first, last, per_day=False):
        latest = {}
        for observation in observations:
            day = date.fromisoformat(observation["observed_date"])
            if (first and day < first) or (last and day > last):
                continue
            identity = observation["ship_id"] if is_mock else observation["observation_id"]
            key = (day, identity) if per_day else identity
            if key not in latest or observation["observed_at"] > latest[key]["observed_at"]:
                latest[key] = observation
        return list(latest.values())

    @tool(args_schema=CountShipsInput)
    def count_ships(observed_from: str, observed_to: str) -> dict:
        """Thống kê tàu khả nghi và tàu có khả năng là tàu sân bay theo từng ngày.

        Ngày YYYY-MM-DD, gồm cả hai đầu mốc, tối đa 366 ngày mỗi lần gọi.
        Đếm ID tàu duy nhất trong ngày, dùng phân loại của lần quan sát cuối ngày.
        Với dữ liệu thật, mỗi ảnh Telegram được đếm riêng dù trùng tên tàu trong caption.
        aircraft_carrier là kết quả mô hình, không phải xác nhận thực tế.
        Ngày không có quan sát trả 0. Lỗi nguồn dữ liệu được báo lỗi, không tính là 0.
        """
        first, last = _date_range(observed_from, observed_to)
        if (last - first).days >= 366:
            raise ToolException("Mỗi lần thống kê tối đa 366 ngày; hãy chia nhỏ khoảng ngày.")
        by_day = {}
        for observation in latest_in_range(first, last, per_day=True):
            by_day.setdefault(observation["observed_date"], []).append(observation)
        stats = []
        for offset in range((last - first).days + 1):
            day = (first + timedelta(days=offset)).isoformat()
            ships = by_day.get(day, [])
            stats.append({
                "date": day,
                "suspicious_ship_count": len(ships),
                "possible_aircraft_carrier_count": sum(s["classification"] == "aircraft_carrier" for s in ships),
            })
        return {**metadata, "observed_from": observed_from, "observed_to": observed_to, "daily_stats": stats}

    @tool(args_schema=SearchShipsInput)
    def search_ships(
        observed_from: str | None = None, observed_to: str | None = None,
        ship_id: str | None = None,
        min_length_m: float | None = None, max_length_m: float | None = None,
        min_width_m: float | None = None, max_width_m: float | None = None,
        length_gt_m: float | None = None, carrier_score_gt: float | None = None,
        classification: Classification | None = None, limit: int = 20, offset: int = 0,
    ) -> dict:
        """Tìm tàu khả nghi, trả URL chi tiết, kích thước, vị trí, ngày giờ, phân loại và URL ảnh.

        Ngày YYYY-MM-DD và kích thước mét, gồm cả hai đầu mốc; bộ lọc có thể bỏ qua.
        Chọn lần quan sát mới nhất của mỗi tàu trong khoảng ngày TRƯỚC khi lọc
        kích thước/phân loại. Dùng ship_id để xem riêng một tàu. Có phân trang.
        Với dữ liệu thật, mỗi ảnh là một kết quả riêng; ship_id lấy từ caption Telegram.
        confidence là carrier score; null nếu chưa có prediction.
        length_gt_m và carrier_score_gt là lớn hơn nghiêm ngặt, không gồm biên;
        trên 250m và score trên 80% dùng 250 và 0.8. total đếm trước phân trang.
        """
        first, last = _date_range(observed_from, observed_to)
        for minimum, maximum, field in [(min_length_m, max_length_m, "length_m"), (min_width_m, max_width_m, "width_m")]:
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ToolException(f"min_{field} phải nhỏ hơn hoặc bằng max_{field}.")
        matches = []
        for observation in latest_in_range(first, last):
            if ship_id is not None and observation["ship_id"] != ship_id:
                continue
            if classification is not None and observation["classification"] != classification:
                continue
            if length_gt_m is not None and (observation["length_m"] is None or observation["length_m"] <= length_gt_m):
                continue
            if carrier_score_gt is not None and (observation["confidence"] is None or observation["confidence"] <= carrier_score_gt):
                continue
            if any((minimum is not None and (observation[field] is None or observation[field] < minimum)) or
                   (maximum is not None and (observation[field] is None or observation[field] > maximum))
                   for minimum, maximum, field in [(min_length_m, max_length_m, "length_m"), (min_width_m, max_width_m, "width_m")]):
                continue
            matches.append(observation)
        matches.sort(key=lambda item: item["ship_id"])
        filters = {"observed_from": observed_from, "observed_to": observed_to, "ship_id": ship_id,
                   "min_length_m": min_length_m, "max_length_m": max_length_m,
                   "min_width_m": min_width_m, "max_width_m": max_width_m, "classification": classification,
                   "length_gt_m": length_gt_m, "carrier_score_gt": carrier_score_gt}
        return {**metadata, "filters": filters, "total": len(matches), "limit": limit, "offset": offset,
                "ships": deepcopy(matches[offset:offset + limit])}

    return [count_ships, search_ships]
