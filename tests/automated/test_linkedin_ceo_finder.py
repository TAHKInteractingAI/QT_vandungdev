"""Unit tests cho package linkedin_ceo_finder."""

import pytest
from linkedin_ceo_finder.config import CEOConfig
from linkedin_ceo_finder.models import CEOLead
from linkedin_ceo_finder.network import unquote_yahoo_url
from linkedin_ceo_finder.parser import (
    is_duplicate_ceo,
    is_leadership_role,
    make_lead,
    parse_linkedin_title,
)
from linkedin_ceo_finder.cli import parse_args


def test_unquote_yahoo_url():
    sample_yahoo_url = (
        "https://r.search.yahoo.com/_ylt=Awr/RU=https%3a%2f%2fvn.linkedin.com%2fin%2fexample-ceo/RK=2/RS=123"
    )
    clean_url = unquote_yahoo_url(sample_yahoo_url)
    assert clean_url == "https://vn.linkedin.com/in/example-ceo"

    # URL thường không có RU=
    direct_url = "https://www.linkedin.com/in/direct-ceo?ref=test"
    assert unquote_yahoo_url(direct_url) == "https://www.linkedin.com/in/direct-ceo"


def test_is_leadership_role():
    assert is_leadership_role("Chief Executive Officer") is True
    assert is_leadership_role("CEO & Founder") is True
    assert is_leadership_role("Tổng Giám Đốc") is True
    assert is_leadership_role("Managing Director") is True

    # Bad roles (cựu nhân sự hoặc vai trò khác)
    assert is_leadership_role("ex-CEO") is False
    assert is_leadership_role("Former Founder") is False
    assert is_leadership_role("Cựu Giám đốc") is False
    assert is_leadership_role("Product Advisor") is False
    assert is_leadership_role("Software Engineer") is False
    assert is_leadership_role("") is False
    assert is_leadership_role(None) is False


def test_parse_linkedin_title_valid():
    title = "Nguyen Van A - Chief Executive Officer @ Tech Corp | LinkedIn"
    name, role, comp = parse_linkedin_title(title)
    assert name == "Nguyen Van A"
    assert role == "Chief Executive Officer"
    assert comp == "Tech Corp"


def test_parse_linkedin_title_filter_former():
    title = "Henry Scott-Green - Product @ OpenAI | ex Co-Founder/CEO at Context.ai"
    name, role, comp = parse_linkedin_title(title)
    # Vì chức danh lãnh đạo duy nhất là "ex Co-Founder/CEO", role trả về rỗng vì bị loại bỏ
    assert role == ""


def test_parse_linkedin_title_snippet_fallback():
    title = "Jane Doe - Founder - LinkedIn"
    snippet = "Experience: Acme Innovations · San Francisco, CA"
    name, role, comp = parse_linkedin_title(title, snippet=snippet)
    assert name == "Jane Doe"
    assert role == "Founder"
    assert comp == "Acme Innovations"


def test_is_duplicate_ceo():
    seen = {"https://linkedin.com/in/john-doe", "john-doe", "john doe"}

    # Trùng qua full link
    assert is_duplicate_ceo("https://linkedin.com/in/john-doe?param=1", "Random", seen) is True

    # Trùng qua slug
    assert is_duplicate_ceo("https://vn.linkedin.com/in/john-doe/", "Random", seen) is True

    # Trùng qua tên
    assert is_duplicate_ceo("https://linkedin.com/in/another", "John Doe", seen) is True

    # Chưa có
    assert is_duplicate_ceo("https://linkedin.com/in/alice-smith", "Alice Smith", seen) is False


def test_ceo_lead_model():
    lead = CEOLead(
        name="Sundar Pichai",
        role="CEO",
        keyword="Google",
        company="Google",
        linkedin_link="https://www.linkedin.com/in/sundarpichai",
        updated_at="2026-09-28 10:00:00",
    )

    # Object access
    assert lead.name == "Sundar Pichai"
    assert lead.url == "https://www.linkedin.com/in/sundarpichai"

    # Dict-like access
    assert lead["name"] == "Sundar Pichai"
    assert lead["url"] == "https://www.linkedin.com/in/sundarpichai"
    assert lead.get("company") == "Google"

    # Export to sheet row
    row = lead.to_sheet_row(stt=1)
    assert row[0] == 1
    assert row[1] == "Sundar Pichai"
    assert len(row) == 7


def test_cli_parsing():
    args_domain = parse_args(["domains", "google.com", "nvidia.com", "--workers", "3", "--no-sheet"])
    assert args_domain.command == "domains"
    assert args_domain.domains == ["google.com", "nvidia.com"]
    assert args_domain.workers == 3
    assert args_domain.no_sheet is True

    args_kw = parse_args(["keyword", "AI Vietnam", "--target-count", "5"])
    assert args_kw.command == "keyword"
    assert args_kw.keyword == "AI Vietnam"
    assert args_kw.target_count == 5


def test_verifier_functions():
    from linkedin_ceo_finder.verifier import extract_json_from_ai_response, verify_executive_with_gemini
    from unittest.mock import patch, MagicMock

    # 1. Test extract JSON
    json_block = "```json\n{\"is_valid_leader\": true, \"name\": \"Sundar Pichai\", \"role\": \"CEO\", \"company\": \"Google\"}\n```"
    res = extract_json_from_ai_response(json_block)
    assert res is not None
    assert res["is_valid_leader"] is True
    assert res["name"] == "Sundar Pichai"

    # 2. Test fallback when no key
    valid, name, role, comp = verify_executive_with_gemini("Test", "CEO", "Tech", "tech.com", gemini_key="")
    assert valid is True
    assert name == "Test"

    # 3. Test mock API response success
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "```json\n{\"is_valid_leader\": true, \"name\": \"Verified Name\", \"role\": \"Chief Executive Officer\", \"company\": \"Google\"}\n```"}]
            }
        }]
    }
    with patch("requests.post", return_value=mock_resp):
        valid, name, role, comp = verify_executive_with_gemini("Old Name", "CEO", "Google", "google.com", gemini_key="test_key")
        assert valid is True
        assert name == "Verified Name"
        assert role == "Chief Executive Officer"

    # 4. Test mock API rejection
    mock_reject = MagicMock()
    mock_reject.status_code = 200
    mock_reject.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "```json\n{\"is_valid_leader\": false, \"reason\": \"Ex-employee\"}\n```"}]
            }
        }]
    }
    with patch("requests.post", return_value=mock_reject):
        valid, _, _, _ = verify_executive_with_gemini("Ex Employee", "Advisor", "Google", "google.com", gemini_key="test_key")
        assert valid is False
