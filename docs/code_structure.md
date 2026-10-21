# Cấu trúc code Vesselwatch

Hai package chính tương ứng với hai ứng dụng: `file_server` cung cấp dữ liệu
và phép tính; `ship_agent` điều phối LLM, công cụ và bằng chứng ảnh. Bên trong
mỗi package, module được nhóm theo trách nhiệm. Chưa tạo package `shared`.

## File server

```text
file_server/
├── app.py          # App factory, lifespan và đăng ký router
├── config.py       # Dataset, URL và đường dẫn cấu hình trên MID
├── api/            # FastAPI routes và context giải quyết vùng truy vấn
├── schemas/        # Observation, polygon và request contracts
├── data/           # Telegram, predictions, map bundle, snapshot trong bộ nhớ
├── services/       # Truy vấn, thống kê, DBSCAN, lựa chọn ứng viên review
├── storage/        # Lưu vùng và phiên map vào JSON
├── media/          # Chuẩn hóa ảnh, bộ mẫu, chart PNG
└── area_data/      # Polygon Biển Đông và Vịnh Bắc Bộ
```

`app.py` nạp snapshot trong lifespan; import hoặc khởi tạo app chưa đọc dataset.
Các router nhận dữ liệu qua request/app state hoặc provider đã inject, nên
cùng nhóm route vùng vẫn chạy được cho nguồn thật và nguồn demo.

`AreaContext` ở lớp API xử lý phạm vi truy vấn và chuyển lỗi lưu trữ thành
HTTP response. `storage.area_records` chỉ biết JSON và lỗi `AreaNotFound`,
không phụ thuộc FastAPI. `services` thực hiện phép tính trên observations đã
nạp; thống kê phân bố nằm riêng trong `distributions`, không cần khởi tạo DBSCAN.

Schema dùng chung với HTTP client nằm trong `schemas`, không cần import loader.
`data.store` định nghĩa snapshot và tra ảnh an toàn; loader Telegram và map
cùng sử dụng cấu trúc này. Các package dữ liệu/schema không import agent hoặc
khởi tạo ứng dụng HTTP/LLM.

## Ship agent

```text
ship_agent/
├── graph.py, __main__.py    # LangGraph và CLI entry points
├── agent.py, demo.py       # Entry points mỏng cho builder/demo hiện có
├── image_review.py         # Entry point CLI đọc ảnh hiện có
├── config.py               # URL kết nối các dịch vụ
├── runtime/                # Graph, prompt, context, lựa chọn artifact/pixel
├── tools/                  # Input schemas, factories, registry, source context
├── clients/                # HTTP calls và validation phản hồi backend
├── workflows/              # Điều phối review nhiều ảnh, tổng hợp flags và lỗi
├── vision/                 # Model thị giác, schema kết quả, bằng chứng đối chiếu
├── artifacts/              # HTML báo cáo/map và map snapshots
├── data/                   # Adapter dữ liệu demo và mock
└── map_assets/             # HTML, JS, Leaflet, marker và ranh giới hiển thị
```

`tools.registry.create_tools` chuẩn bị đúng một snapshot/context cho mỗi lần
dựng bộ tool rồi gọi các factory theo thứ tự đã có. Count/search, báo cáo ngày,
truy vấn vùng và adapter ảnh nằm ở các module riêng. Các tool điều tra gọi
HTTP client, lấy bộ mẫu và điều phối workflow; phần gọi model thị giác nằm
trong `vision`. Snapshot được chia sẻ với runtime để LLM chat nhận đúng ảnh.

`runtime.prompts` chứa nguyên prompt nghiệp vụ; `runtime.agent` dựng graph
và vòng agent → tools → agent. `runtime.attachments` chọn kết quả ở lượt hiện
tại và tạo context ảnh tạm thời; `artifacts` render HTML. Không lưu base64 vào
checkpoint. Package `tools` chỉ nạp registry khi gọi export `create_tools`.

Các import nội bộ dùng đường dẫn package mới. Một số schema/hàm thuần vẫn
được agent import từ server và renderer map vẫn được server dùng lại; việc
tách hoàn toàn những phụ thuộc này sang package chung là công việc riêng.

## Entry points và tài nguyên

Các lệnh trên MID giữ nguyên, chạy từ root repository trong virtualenv:

```bash
python -m uvicorn file_server.app:create_app --factory --host 127.0.0.1 --port 8001
langgraph dev --no-browser
python3 scripts/run_vessel_map_demo.py --port 8000
python -m ship_agent --mock-tools --today 2026-10-13
python -m ship_agent.image_review --help
```

Mỗi dịch vụ chạy trong terminal/process riêng như trước. `langgraph.json`
và `langgraph.demo.json`, URL/method/payload API, tên/schema/thứ tự tool và
định dạng JSON lưu vùng đều giữ nguyên. Không thay ngưỡng hoặc hành vi BR 1–20.

Giữ cấu hình trong `file_server/config.py`, `ship_agent/config.py` và `.env`.
Dữ liệu vẫn nằm dưới `data/`; không cần chuyển dataset/bộ mẫu/phiên map.
`area_data` và `map_assets` giữ vị trí cũ; module được chuyển vào package con
tra đường dẫn từ package root thay vì dùng thư mục chứa module mới.

## Kiểm thử và cập nhật MID

Ba nhóm `tests/agent`, `tests/file_server`, `tests/integration` giữ nguyên;
imports và monkeypatch được cập nhật đến module thực thi mới.
`tests/test_package_structure.py` bổ sung kiểm tra import nội bộ, import
không gọi network/load dataset, đường dẫn assets, JSON vùng và entry points.

Trên MID, sau khi pull code, chạy trong virtualenv đã có dependency:

```bash
python -m pytest tests -q
python -m ship_agent --mock-tools --today 2026-10-13
```

Sau đó restart file server 8001 và LangGraph 2024; restart map 8000 để wrapper
nạp import mới. Không thêm dependency, không đổi Pipe hoặc port. File server
vẫn không tự load `.env`.

Kiểm chứng local của đợt refactor: baseline toàn suite có 375 passed, 21 skipped,
9 lỗi collection và 1 failure đều do thiếu FastAPI/LangChain. Sau refactor,
các lỗi môi trường đó giữ nguyên. Lần chạy loại rõ 9 module thiếu dependency
và 1 case cần LangChain đạt 379 passed, 23 skipped, 1 deselected; không phải
toàn suite đã được xác nhận. Kiểm tra Pyflakes và compilation trên hai package
đạt. Snapshot thật 5.230 observations, summary và image registry trước/sau
khớp; các biểu thức tạo system prompt khớp AST. Chưa chạy dịch vụ/vision thật
trên MID trong đợt refactor này.
