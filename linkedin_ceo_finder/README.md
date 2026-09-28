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
