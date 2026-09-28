# LinkedIn CEO Finder

Mô-đun Python chuyên biệt giúp tìm kiếm, bóc tách và xác thực danh tính CEO, Founder và các chức danh lãnh đạo cấp cao trên LinkedIn thông qua **danh sách tên miền website** hoặc **từ khóa ngành nghề**, đồng thời tự động lưu trữ và đồng bộ hóa với **Google Sheet** theo cấu trúc chuẩn 7 cột.

Dự án được trích xuất và chuẩn hóa từ `LinkedIn_CEO_Finder.ipynb` thành cấu trúc gói mã nguồn mô-đun hóa, dễ bảo trì, mở rộng và chạy qua CLI / script / cron.

---

## 📁 Cấu Trúc Thư Mục

```text
linkedin_ceo_finder/
├── __init__.py      # Export các API, hàm chính và class tiện ích
├── config.py        # Quản lý cấu hình biến môi trường, proxy, Colab/Local, hằng số
├── models.py        # Định nghĩa mô hình dữ liệu CEOLead và các hàm chuyển đổi
├── network.py       # curl_cffi HTTP client (Chrome 120 impersonation) & giải mã link Yahoo
├── parser.py        # Logic phân tích cú pháp tiêu đề LinkedIn, lọc bỏ cựu nhân sự
├── searcher.py      # Thuật toán tìm kiếm đa tầng theo Domain và từ khóa ngành nghề
├── sheet.py         # Kết nối OAuth/Service Account, định dạng bảng 7 cột, sắp xếp
├── core.py          # Lớp điều phối CEOFinder và các hàm chạy song song (ThreadPoolExecutor)
├── cli.py           # Giao diện dòng lệnh CLI (Command Line Interface)
├── api/             # REST API Router & Pydantic Schemas (tích hợp FastAPI)
│   ├── __init__.py
│   ├── routes.py
│   └── schemas.py
└── README.md        # Hướng dẫn chi tiết sử dụng
```

---

## ⚡ Các Tính Năng Nổi Bật

1. **Thuật toán Multi-Tier Executive Resolution (Tìm CEO theo tên miền)**:
   - **Tầng 1 (Executive Search)**: Truy vấn danh tính CEO thực tế từ tri thức toàn cầu / Wikipedia (tránh lấy nhầm cựu CEO, CEO chi nhánh hoặc nhân sự cấp dưới).
   - **Tầng 2 (Targeted LinkedIn Lookup)**: Truy xuất đích danh URL LinkedIn cá nhân của vị CEO đó.
   - **Tầng 3 (Direct LinkedIn Query & Website Fallback)**: Fallback cho các công ty vừa và nhỏ / chuyên biệt, tự động quét trang `/leadership`, `/about`, `/team` của website.
2. **Xác thực chức danh nghiêm ngặt**:
   - Tự động phát hiện và loại bỏ các chức danh không hợp lệ: `ex-`, `former`, `cựu`, `past`, `advisor`, `investor`, `intern`.
3. **Cơ chế chống trùng lặp (Smart Deduplication)**:
   - Tải trước danh bạ CEO hiện có từ Google Sheet để bỏ qua ứng viên đã lưu.
   - Đối chiếu theo cả URL LinkedIn, Username slug và Họ tên.
4. **Chuẩn hóa bảng dữ liệu Google Sheet 7 cột**:
   - `STT | CEO Name | Role / Title | Keyword | Company | LinkedIn URL | Ngày Cập Nhật`
   - Đóng băng header, tô màu navy, căn lề và co giãn pixel tối ưu hiển thị.
   - Tự động sắp xếp ngày mới nhất lên trên cùng và đánh lại STT liên tục.

---

## ⚙️ Cấu Hình (.env)

Tạo hoặc cập nhật file `.env` trong thư mục gốc của dự án:

```env
# Google Sheet ID cho danh bạ CEO
SHEET_CEO=your_google_sheet_id_here
SHEET_CEO_WORKSHEET=sheet1

# Đường dẫn file Google Service Account JSON
GOOGLE_APPLICATION_CREDENTIALS=service_account.json

# Proxy HTTP (tùy chọn)
DEFAULT_BACKBONE_PROXY=http://user:pass@proxy_host:port
```

---

## 🚀 Hướng Dẫn Sử Dụng

### 1. Sử dụng qua dòng lệnh (CLI)

#### Tìm kiếm theo danh sách Tên miền (Domain)
```bash
# Quét danh sách domain với 5 luồng song song và lưu vào Google Sheet
python -m linkedin_ceo_finder.cli domains google.com microsoft.com nvidia.com amd.com

# Chỉ in kết quả ra console và xuất file JSON (không ghi vào Sheet)
python -m linkedin_ceo_finder.cli domains jetbrains.com openai.com --no-sheet -o results.json
```

#### Tìm kiếm theo Từ khóa (Keyword)
```bash
# Tìm 10 CEO thuộc ngành AI tại Việt Nam
python -m linkedin_ceo_finder.cli keyword "AI Vietnam" --target-count 10

# Tìm kiếm và bỏ qua các kết quả không bóc tách được tên công ty
python -m linkedin_ceo_finder.cli keyword "Fintech" --target-count 5 --skip-empty-company
```

---

### 2. Sử dụng trong mã nguồn Python

```python
from linkedin_ceo_finder import find_ceos_by_domains, find_ceos_by_keyword

# Cách 1: Tìm kiếm theo danh sách domain website
domains = [
    "https://www.google.com",
    "https://www.nvidia.com",
    "https://www.jetbrains.com",
]

leads = find_ceos_by_domains(
    company_domains=domains,
    max_workers=5,
    save_to_sheet=True  # Tự động đồng bộ lên Google Sheet
)

# Cách 2: Tìm kiếm theo từ khóa ngành nghề
keyword_leads = find_ceos_by_keyword(
    keyword="Fintech Vietnam",
    target_count=5,
    save_to_sheet=True
)

# In kết quả
for lead in leads:
    print(lead.name, "|", lead.role, "|", lead.company, "->", lead.linkedin_link)
```

---

### 3. Sử dụng hướng đối tượng với `CEOFinder`

```python
from linkedin_ceo_finder import CEOFinder, CEOConfig

config = CEOConfig(
    sheet_id="your_sheet_id",
    worksheet_name="sheet1",
    max_workers=4
)
finder = CEOFinder(config=config)

leads = finder.find_by_domains(["apple.com", "meta.com"])
```

---

### 4. REST API (Tích hợp cùng FastAPI Backend)

API của LinkedIn CEO Finder được tích hợp trực tiếp vào FastAPI server (`main.py`):

| Phương thức | Đường dẫn | Chức năng |
|---|---|---|
| `GET` | `/api/v1/ceo/health` | Kiểm tra trạng thái dịch vụ và cấu hình Google Sheet |
| `POST` | `/api/v1/ceo/domains` | Tìm kiếm CEO theo danh sách tên miền website |
| `POST` | `/api/v1/ceo/keyword` | Tìm kiếm CEO theo từ khóa ngành nghề |
| `GET` | `/api/v1/ceo/quick-search` | Tìm kiếm nhanh CEO qua Query parameters |

#### Chế độ hoạt động tối ưu cho Cron-Job:
- **Mặc định (`sync: false`)**: API tiếp nhận yêu cầu, đẩy tiến trình tìm kiếm vào **Background Tasks** chạy ngầm (lưu kết quả vào Google Sheet) và **phản hồi ngay lập tức `status: "running"` trong < 100ms**. Cron-job sẽ không bao giờ bị timeout!
- **Đồng bộ (`sync: true`)**: Nếu bạn muốn API đợi quét xong và trả về danh sách leads trực tiếp trong response JSON, hãy gửi `"sync": true`.

#### Ví dụ gọi API qua `curl` (Bắt buộc kèm Header `X-API-Key`):

**Dành cho Cron-Job (Mặc định chạy ngầm, phản hồi "running" ngay lập tức):**
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/ceo/keyword" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: test-secret-key-123" \
     -d '{
       "keyword": "Fintech Vietnam",
       "target_count": 5,
       "save_to_sheet": true
     }'
```
*Phản hồi ngay:*
```json
{
  "status": "running",
  "message": "Tiến trình tìm kiếm CEO cho từ khóa 'Fintech Vietnam' đang chạy ngầm trong nền.",
  "job_id": "ceo_kw_8f3a1b2c",
  "mode": "keyword",
  "target": "Fintech Vietnam",
  "save_to_sheet": true,
  "timestamp": "2026-09-28T09:40:00Z"
}
```

**Tìm CEO theo danh sách tên miền:**
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/ceo/domains" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: test-secret-key-123" \
     -d '{
       "domains": ["google.com", "nvidia.com"],
       "save_to_sheet": true
     }'
```

**Tìm nhanh qua GET query:**
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/ceo/quick-search?keyword=AI&count=2" \
     -H "X-API-Key: test-secret-key-123"

# Hoặc truyền key qua query parameter trên trình duyệt:
# http://127.0.0.1:8000/api/v1/ceo/quick-search?keyword=AI&count=2&key=test-secret-key-123
```

**Xem tài liệu tương tác Swagger UI:**
Truy cập `http://127.0.0.1:8000/docs` trên trình duyệt để thử nghiệm trực quan.


