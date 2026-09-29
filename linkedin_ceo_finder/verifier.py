"""Bộ xác minh và chuẩn hóa danh tính CEO qua Google AI Studio (Gemma / Gemini).

Sử dụng model mặc định gemma-4-26b-a4b-it để kiểm chứng chức danh lãnh đạo,
loại bỏ các cựu nhân sự (ex-CEO / cựu founder) và chuẩn hóa tên/công ty.
Có cơ chế Graceful Fallback: Nếu không có key hoặc mạng AI timeout,
hệ thống sẽ tự động dùng kết quả bóc tách từ Rule-based/Regex mà không làm gián đoạn luồng cào.
"""

import json
import logging
import os
import re
from typing import Optional, Tuple
import requests

from .config import DEFAULT_GEMINI_KEY, DEFAULT_GEMINI_MODEL

logger = logging.getLogger(__name__)


def extract_json_from_ai_response(text: str) -> Optional[dict]:
    """Bóc tách JSON an toàn từ phản hồi dạng text hoặc markdown của Gemma/Gemini."""
    if not text:
        return None

    # 1. Tìm khối ```json ... ``` hoặc ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            val = json.loads(m.group(1).strip())
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                return val[0]
            if isinstance(val, dict):
                return val
        except Exception:
            pass

    # 2. Tìm khối object {...} đơn thuần
    m = re.search(r"(\{[\s\S]*\})", text)
    if m:
        try:
            val = json.loads(m.group(1).strip())
            if isinstance(val, dict):
                return val
        except Exception:
            pass

    # 3. Fallback bóc tách từng thuộc tính theo pattern của Gemma
    is_valid_match = re.search(
        r"(?:is_valid_leader|status)[\"'\s:]+(?:true|verified|yes)",
        text,
        re.I,
    )
    is_invalid_match = re.search(
        r"(?:is_valid_leader|status)[\"'\s:]+(?:false|unverified|no|rejected)",
        text,
        re.I,
    )

    name_m = re.search(r"(?:name|actual_ceo)[\"'\s:]+[\"']([^\"'\n]+)[\"']", text, re.I)
    role_m = re.search(r"role[\"'\s:]+[\"']([^\"'\n]+)[\"']", text, re.I)
    comp_m = re.search(r"company[\"'\s:]+[\"']([^\"'\n]+)[\"']", text, re.I)

    if is_invalid_match and not is_valid_match:
        return {"is_valid_leader": False}

    if is_valid_match or name_m:
        return {
            "is_valid_leader": True,
            "name": name_m.group(1).strip() if name_m else "",
            "role": role_m.group(1).strip() if role_m else "CEO",
            "company": comp_m.group(1).strip() if comp_m else "",
        }

    return None


_warned_no_key = False


def verify_executive_with_gemini(
    name: str,
    role: str,
    company: str,
    target: str,
    snippet: str = "",
    gemini_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    timeout: int = 15,
) -> Tuple[bool, str, str, str]:
    """Sử dụng Google AI Studio (gemma-4-26b-a4b-it) để xác minh và chuẩn hóa chức danh lãnh đạo.

    Parameters:
        name (str): Tên ứng viên bóc tách được.
        role (str): Chức vụ ứng viên.
        company (str): Tên công ty.
        target (str): Nguồn tìm kiếm (tên miền hoặc từ khóa).
        snippet (str): Đoạn trích dẫn thông tin đi kèm từ Google/Yahoo.
        gemini_key (str, optional): API Key Google AI Studio.
        gemini_model (str, optional): Model AI (mặc định: gemma-4-26b-a4b-it).
        timeout (int): Thời gian chờ phản hồi tối đa (giây).

    Returns:
        Tuple[bool, str, str, str, str]: (is_valid, final_name, final_role, final_company, ai_status)
    """
    global _warned_no_key
    key = gemini_key if gemini_key is not None else (os.getenv("GEMINI_KEY") or DEFAULT_GEMINI_KEY)
    if not key or not str(key).strip():
        if not _warned_no_key:
            print("  ℹ️ [Gemma AI] Chưa phát hiện biến môi trường GEMINI_KEY -> Tiếp tục bằng bộ lọc Regex mặc định.", flush=True)
            _warned_no_key = True
        return True, name, role, company, "Chưa xác minh (Regex)"

    model_name = gemini_model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL or "gemma-4-26b-a4b-it"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"

    print(f"  🤖 [Gemma AI] Đang kiểm tra ứng viên: {name} ({role} @ {company})...", flush=True)

    prompt = f"""Task: Determine if the candidate is currently a top executive, CEO, President, or Founder of the target company.
Target Context: {target}
Candidate Name: {name}
Parsed Role: {role}
Parsed Company: {company}
Supporting Snippet: {snippet[:350]}

Rules:
1. Base your evaluation on the live snippet provided.
2. If candidate is a former employee, ex-CEO, advisor, or low-level employee, set is_valid_leader=false.
3. If candidate is currently the CEO, Managing Director, Founder, Co-Founder, President or Chairman, set is_valid_leader=true.
4. Clean up the Name, Role, and Company to be concise and accurate.

Respond strictly with a JSON codeblock:
```json
{{
  "is_valid_leader": true,
  "name": "{name}",
  "role": "{role}",
  "company": "{company}"
}}
```"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 400,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code == 200:
            resp_json = resp.json()
            candidates = resp_json.get("candidates", [])
            if candidates:
                raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed = extract_json_from_ai_response(raw_text)
                if parsed:
                    is_valid = parsed.get("is_valid_leader", True)
                    final_name = str(parsed.get("name") or name).strip()
                    final_role = str(parsed.get("role") or role).strip()
                    final_comp = str(parsed.get("company") or company).strip()
                    if is_valid:
                        ai_status = f"✅ Xác minh bởi {model_name}"
                        print(f"  ✅ [Gemma AI Hợp lệ] {final_name} | {final_role} | {final_comp} ({model_name})", flush=True)
                        return True, final_name, final_role, final_comp, ai_status
                    else:
                        ai_status = f"❌ Bị loại bởi {model_name}"
                        print(f"  ❌ [Gemma AI Loại bỏ] {name} ({role} @ {company}) không phải lãnh đạo hiện tại.", flush=True)
                        return False, name, role, company, ai_status
        else:
            print(f"  ⚠️ [Gemma AI HTTP {resp.status_code}] {resp.text[:120]} -> Dùng kết quả Regex dự phòng.", flush=True)
    except Exception as err:
        print(f"  ⚠️ [Gemma AI Lỗi/Timeout] {err} -> Dùng kết quả Regex dự phòng.", flush=True)

    # Fallback an toàn về kết quả Regex nếu AI gặp sự cố
    return True, name, role, company, "⚠️ Chưa xác minh"
