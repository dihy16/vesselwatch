"""Reports HTTP endpoints."""

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from file_server.media.charts import render_carrier_chart
from file_server.services.carrier_reports import daily_carrier_report


def register_reports_routes(app):
    router = APIRouter()
    def build_report(request: Request, first: date, last: date):
        try:
            return daily_carrier_report(
                (o.model_dump() for o in request.app.state.store.observations), first, last,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/reports/daily-carriers")
    def carrier_report(request: Request, observed_from: date, observed_to: date):
        report = build_report(request, observed_from, observed_to)
        base = request.app.state.settings.base_url.rstrip("/")
        query = urlencode({"observed_from": report["observed_from"],
                           "observed_to": report["observed_to"],
                           "report_id": report["report_id"]})
        return {**report, "is_mock": False,
                "chart_url": f"{base}/charts/daily-carriers.png?{query}",
                "coverage": request.app.state.store.summary}

    @router.get("/charts/daily-carriers.png", response_class=Response)
    def carrier_chart(
        request: Request, observed_from: date, observed_to: date,
        report_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
    ):
        report = build_report(request, observed_from, observed_to)
        if report["report_id"] != report_id:
            raise HTTPException(409, "Report data changed; request a new daily carrier report.")
        return Response(render_carrier_chart(report), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})

    app.include_router(router)
