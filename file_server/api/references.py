"""References HTTP endpoints."""

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from file_server import config
from file_server.media.carrier_references import load_reference_library
from file_server.media.image_assets import prepare_preview_image


def register_references_routes(app):
    router = APIRouter()
    def reference_library(request, *, refresh=False):
        library = getattr(request.app.state, "carrier_reference_library", None)
        if library is None or refresh:
            directory = request.app.state.settings.carrier_reference_dir or config.CARRIER_REFERENCE_DIR
            try:
                library = load_reference_library(directory)
            except (OSError, ValueError) as exc:
                raise HTTPException(503, "Chưa nạp được bộ mẫu: kiểm tra CARRIER_REFERENCE_DIR, description.md và ảnh hợp lệ (≤10 MB/16 MP mỗi ảnh).") from exc
            request.app.state.carrier_reference_library = library
        return library

    @router.get("/carrier-references")
    def carrier_references(request: Request):
        library = reference_library(request, refresh=True)
        return Response(content=json.dumps(library.manifest(request.app.state.settings.base_url),
                                           ensure_ascii=False).encode("utf-8"),
                        media_type="application/json", headers={"Cache-Control": "no-store"})

    @router.get("/carrier-references/images/{reference_id}")
    def carrier_reference_image(reference_id: str, request: Request,
                                revision: str = Query(pattern=r"^[a-f0-9]{64}$"), preview: bool = False):
        library = reference_library(request)
        if revision != library.revision:
            raise HTTPException(409, "Bộ mẫu đã thay đổi; tải lại danh sách ảnh mẫu.")
        image = next((image for image in library.images if image.reference_id == reference_id), None)
        if image is None:
            raise HTTPException(404, "Không tìm thấy ảnh mẫu.")
        if preview:
            variant = prepare_preview_image(image.data)
            return Response(variant.data, media_type="image/png", headers={
                "Cache-Control": "no-store", "X-Original-Width": str(image.width),
                "X-Original-Height": str(image.height)})
        return Response(image.data, media_type="image/png", headers={"Cache-Control": "no-store"})

    app.include_router(router)
