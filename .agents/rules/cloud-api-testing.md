# Quy Tắc Kiểm Thử API Trên Cloud (Render / Production)

1. **Phạm vi áp dụng**: Mọi tác vụ kiểm thử, gửi request HTTP/cURL tới domain server cloud (ví dụ: `https://crawler-bot-pf33.onrender.com` hoặc bất kỳ URL cloud deployment nào của hệ thống).

2. **Lý do & Bối cảnh**:
   - Server Render (Free Tier) cần duy trì trạng thái ngủ (sleep / inactive sau 15 phút không có request) để người dùng chủ động kiểm tra cơ chế đánh thức (wake-up logic) và đo lường thời gian khởi động lạnh (cold start).
   - Bất kỳ request nào gửi đến cloud (bao gồm `GET /health`, `POST /api/v1/crawl/trigger`, v.v.) đều sẽ kích hoạt Render thức dậy, làm hỏng kịch bản kiểm tra trạng thái ngủ của người dùng.

3. **Chỉ thị bắt buộc cho Agent**:
   - **TUYỆT ĐỐI KHÔNG** tự ý gửi request (bằng `curl`, python `requests`, `httpx`, test script...) tới API trên cloud / Render khi chưa có sự đồng ý hoặc yêu cầu tường minh từ người dùng.
   - **MỌI TÁC VỤ KIỂM THỬ MẶC ĐỊNH**:
     - Chỉ chạy test nội bộ / local (sử dụng `TestClient(app)` trong `pytest` hoặc server chạy tại `localhost:8000`).
     - `pytest tests/automated/` chỉ được tương tác với local test client hoặc local mock.
   - **NGOẠI LỆ DUY NHẤT**:
     - Chỉ thực hiện gọi/test API trên cloud khi người dùng đưa ra yêu cầu trực tiếp và rõ ràng (ví dụ: *"hãy test API trên cloud"*, *"gửi request lên Render xem sao"*, *"wake up server Render đi"*...).
