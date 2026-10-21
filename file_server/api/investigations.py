"""Candidate, clustering, analysis and monitoring HTTP endpoints."""

from fastapi import HTTPException, Request

from file_server.schemas.area_models import AreaRequest, ObservationAnalysisRequest
from file_server.schemas.monitoring import MonitoringRequest
from file_server.schemas.reviews import FalseCarrierRequest
from file_server.schemas.reviews import HotspotClusterRequest
from file_server.schemas.reviews import MissedCarrierRequest
from file_server.services.carrier_hotspots import build_hotspot_report, hotspot_cluster_candidates
from file_server.services.carrier_investigation import carrier_investigation_candidates
from file_server.services.false_carriers import (
    candidate_query as false_candidate_query,
    false_carrier_candidates,
)
from file_server.services.label_review import label_review_candidates
from file_server.services.missed_carriers import candidate_query, missed_carrier_candidates
from file_server.services.monitoring_reports import monitoring_query, build_monitoring_report
from file_server.services.observation_analysis import analysis_filters, analyze_observations


def register_investigation_routes(app, context):
    @app.post("/missed-carrier-candidates")
    def missed_candidates(body: MissedCarrierRequest, request: Request):
        area = context.query_area(candidate_query(body), request)
        if area["status"] == "needs_drawing":
            return area
        rows, _, record = context.checked_record(request, area["area_id"])
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **missed_carrier_candidates(rows, body, context.geometry_for(record)),
                "source_snapshot_id": record["snapshot_id"]}

    @app.post("/false-carrier-candidates")
    def false_candidates(body: FalseCarrierRequest, request: Request):
        area = context.query_area(false_candidate_query(body), request)
        if area["status"] == "needs_drawing":
            return area
        rows, _, record = context.checked_record(request, area["area_id"])
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **false_carrier_candidates(rows, body, context.geometry_for(record)),
                "source_snapshot_id": record["snapshot_id"]}

    @app.post("/carrier-investigation-candidates")
    def investigation_candidates(body: FalseCarrierRequest, request: Request):
        area = context.query_area(false_candidate_query(body), request)
        if area["status"] == "needs_drawing":
            return area
        rows, _, record = context.checked_record(request, area["area_id"])
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **carrier_investigation_candidates(rows, body, context.geometry_for(record)),
                "source_snapshot_id": record["snapshot_id"]}

    @app.post("/carrier-hotspots")
    def carrier_hotspots(body: FalseCarrierRequest, request: Request):
        area = context.query_area(false_candidate_query(body), request)
        if area["status"] == "needs_drawing":
            return area
        rows, _, record = context.checked_record(request, area["area_id"])
        try:
            report, _ = build_hotspot_report(rows, body, source_snapshot_id=record["snapshot_id"],
                                             geometry=context.geometry_for(record))
        except ImportError as exc:
            raise HTTPException(503, "Thiếu scikit-learn; cập nhật requirements.txt trên server.") from exc
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **report}

    @app.post("/carrier-hotspot-candidates")
    def carrier_hotspot_candidates(body: HotspotClusterRequest, request: Request):
        area = context.query_area(false_candidate_query(body), request)
        if area["status"] == "needs_drawing":
            return area
        rows, _, record = context.checked_record(request, area["area_id"])
        try:
            report, groups = build_hotspot_report(rows, body, source_snapshot_id=record["snapshot_id"],
                                                  geometry=context.geometry_for(record))
        except ImportError as exc:
            raise HTTPException(503, "Thiếu scikit-learn; cập nhật requirements.txt trên server.") from exc
        if report["report_id"] != body.report_id:
            raise HTTPException(409, "Nguồn/ngày/vùng đã đổi; tìm cụm lại trước khi kiểm tra.")
        if body.cluster_id not in groups:
            raise HTTPException(404, "Không tìm thấy cụm trong báo cáo này.")
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **hotspot_cluster_candidates(groups[body.cluster_id], body),
                "report_id": body.report_id, "cluster_id": body.cluster_id,
                "source_snapshot_id": record["snapshot_id"]}

    @app.post("/vessel-monitoring-reports")
    def vessel_monitoring_reports(body: MonitoringRequest, request: Request):
        area = context.query_area(monitoring_query(body), request)
        if area["status"] == "needs_drawing":
            return area
        rows, _, record = context.checked_record(request, area["area_id"])
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **build_monitoring_report(rows, body, source_snapshot_id=record["snapshot_id"],
                                           geometry=context.geometry_for(record))}

    @app.post("/carrier-label-review-candidates")
    def carrier_label_review_candidates(body: FalseCarrierRequest, request: Request):
        area = context.query_area(false_candidate_query(body), request)
        if area["status"] == "needs_drawing":
            return area
        rows, _, record = context.checked_record(request, area["area_id"])
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **label_review_candidates(rows, body, context.geometry_for(record)),
                "source_snapshot_id": record["snapshot_id"]}

    @app.post("/observation-analyses")
    def observation_analysis(body: ObservationAnalysisRequest, request: Request):
        query = analysis_filters(body)
        area = context.query_area(AreaRequest(**query.model_dump(), polygon=body.polygon), request)
        if area["status"] == "needs_drawing":
            return {**area, "analysis": body.analysis}
        rows, _, record = context.checked_record(request, area["area_id"])
        result = analyze_observations(rows, body, context.geometry_for(record))
        return {**{key: area[key] for key in ("status", "area_id", "area_name", "map_url", "timezone", "is_demo")},
                **result, "source_snapshot_id": record["snapshot_id"]}
