# OpenMontage

OpenMontage là backend/API-first và local Creator UI cho ba tác vụ media:

- `text_to_image` — Google Imagen
- `text_to_video` — Google Veo 3.1 Lite
- `image_to_video` — Google Veo 3.1 Lite với ảnh upload

Gemini TTS tạo giọng đọc tiếng Việt hoặc tiếng Anh. FFmpeg ghép clip, narration
và phụ đề rồi lưu file local. Repo không tự đăng video.

## Chạy nhanh

```bash
cd OpenMontage
# Dùng virtualenv đã cài sẵn dependency.
cp openmontage/.env.example openmontage/.env
# thêm GOOGLE_API_KEY vào .env
.venv/bin/python main.py
```

Mở `http://127.0.0.1:4750/` để dùng Creator. Provider API key được đọc từ
`.env`; API key không được truyền trong request tạo media và không được ghi
vào `projects/`.

Port mặc định là `4750`. Có thể đổi bằng `OPENMONTAGE_PORT=4760`.

UI hỗ trợ:

- nhập prompt hoặc văn bản narration;
- upload ảnh cho `image_to_video`;
- chọn tiếng Việt/English;
- chọn khung dọc TikTok `9:16` hoặc ngang YouTube `16:9`;
- preview và tải file local.

## Cấu trúc chính

```text
backlot/                  Creator UI, Library và API local
tools/                    Imagen, Veo, Gemini TTS, FFmpeg
lib/                      cấu hình, profile và tiện ích runtime
schemas/                  contract dữ liệu
skills/                   hướng dẫn workflow
 pipeline_defs/news-video.yaml  manifest cho workflow news video
```

## Kiểm tra

```bash
PYTHONPATH=openmontage .venv/bin/python -c "from tools.tool_registry import registry; import json; print(json.dumps(registry.public_media_menu(), indent=2))"
.venv/bin/python -m py_compile openmontage/tools/base_tool.py openmontage/tools/tool_registry.py openmontage/tools/news_video.py
```

Lệnh kiểm tra phải hiển thị đúng ba public operations, narration và local
composition.
