"""FastAPI Routes cho LinkedIn CEO Finder."""

import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status

from linkedin_ceo_finder.config import (
    DEFAULT_SERVICE_ACCOUNT,
    DEFAULT_SHEET_ID,
    DEFAULT_WORKSHEET_NAME,
)
from linkedin_ceo_finder.core import find_ceos_by_domains, find_ceos_by_keyword
from .schemas import (
    CEOHealthResponse,
    CEOLeadSchema,
    CEOSearchResponse,
    DomainSearchRequest,
    KeywordSearchRequest,
)
from .security import verify_api_key

router = APIRouter(prefix="/api/v1/ceo", tags=["LinkedIn CEO Finder"])



@router.get("/health", response_model=CEOHealthResponse)
async def health_check():
    """Kiểm tra trạng thái hoạt động và cấu hình Google Sheet của LinkedIn CEO Finder."""
    sheet_id = os.getenv("SHEET_CEO", DEFAULT_SHEET_ID)
    sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_SERVICE_ACCOUNT)

    return CEOHealthResponse(
        status="ok",
        service="linkedin-ceo-finder",
        sheet_configured=bool(sheet_id),
        service_account_configured=bool(sa_path and os.path.exists(sa_path)),
        timestamp=datetime.now(timezone.utc),
    )


@router.post(
    "/domains",
    response_model=CEOSearchResponse,
    dependencies=[Depends(verify_api_key)],
)
async def search_by_domains(request: DomainSearchRequest):
    """Tìm kiếm CEO / Lãnh đạo cấp cao theo danh sách tên miền website.

    Áp dụng thuật toán đa tầng:
    1. Executive Search (Wikipedia & Global Knowledge) xác thực CEO thực tế của tập đoàn.
    2. Targeted LinkedIn Lookup tìm link cá nhân chuẩn xác.
    3. Direct LinkedIn Query & Website Fallback cho công ty vừa/nhỏ.
    """
    try:
        leads = find_ceos_by_domains(
            company_domains=request.domains,
            target_count=request.target_count,
            save_to_sheet=request.save_to_sheet,
            max_workers=request.max_workers,
            sheet_id=request.sheet_id or DEFAULT_SHEET_ID,
            worksheet_name=request.worksheet_name or DEFAULT_WORKSHEET_NAME,
            proxy=request.proxy,
        )

        leads_data = [
            CEOLeadSchema(
                name=l.name,
                role=l.role,
                keyword=l.keyword,
                company=l.company,
                linkedin_link=l.linkedin_link,
                updated_at=l.updated_at,
            )
            for l in leads
        ]

        return CEOSearchResponse(
            success=True,
            message=f"Đã tìm thấy {len(leads_data)} CEO từ {len(request.domains)} tên miền.",
            total_found=len(leads_data),
            leads=leads_data,
            sheet_saved=request.save_to_sheet and len(leads_data) > 0,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi khi tìm kiếm CEO theo tên miền: {str(e)}",
        )


@router.post(
    "/keyword",
    response_model=CEOSearchResponse,
    dependencies=[Depends(verify_api_key)],
)
async def search_by_keyword(request: KeywordSearchRequest):
    """Tìm kiếm CEO / Lãnh đạo cấp cao theo từ khóa ngành nghề (vd: 'Fintech Vietnam', 'AI').

    Tự động lọc bỏ các cựu nhân sự, cố vấn và kiểm tra trùng lặp với danh bạ hiện có.
    """
    try:
        leads = find_ceos_by_keyword(
            keyword=request.keyword,
            target_count=request.target_count,
            save_to_sheet=request.save_to_sheet,
            sheet_id=request.sheet_id or DEFAULT_SHEET_ID,
            worksheet_name=request.worksheet_name or DEFAULT_WORKSHEET_NAME,
            proxy=request.proxy,
            skip_empty_company=request.skip_empty_company,
            max_pages=request.max_pages,
        )

        leads_data = [
            CEOLeadSchema(
                name=l.name,
                role=l.role,
                keyword=l.keyword,
                company=l.company,
                linkedin_link=l.linkedin_link,
                updated_at=l.updated_at,
            )
            for l in leads
        ]

        return CEOSearchResponse(
            success=True,
            message=f"Đã tìm thấy {len(leads_data)} CEO cho từ khóa '{request.keyword}'.",
            total_found=len(leads_data),
            leads=leads_data,
            sheet_saved=request.save_to_sheet and len(leads_data) > 0,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi khi tìm kiếm CEO theo từ khóa: {str(e)}",
        )


@router.get(
    "/quick-search",
    response_model=CEOSearchResponse,
    dependencies=[Depends(verify_api_key)],
)
async def quick_search(
    keyword: str = Query(..., description="Từ khóa ngành nghề cần tìm kiếm"),
    count: int = Query(3, ge=1, le=20, description="Số lượng CEO cần tìm"),
    save_to_sheet: bool = Query(False, description="Có lưu vào Google Sheet không"),
):
    """Tìm kiếm nhanh CEO qua phương thức GET (hỗ trợ gọi nhanh qua browser hoặc cURL)."""
    try:
        leads = find_ceos_by_keyword(
            keyword=keyword,
            target_count=count,
            save_to_sheet=save_to_sheet,
        )

        leads_data = [
            CEOLeadSchema(
                name=l.name,
                role=l.role,
                keyword=l.keyword,
                company=l.company,
                linkedin_link=l.linkedin_link,
                updated_at=l.updated_at,
            )
            for l in leads
        ]

        return CEOSearchResponse(
            success=True,
            message=f"Tìm kiếm nhanh thành công: {len(leads_data)} CEO.",
            total_found=len(leads_data),
            leads=leads_data,
            sheet_saved=save_to_sheet and len(leads_data) > 0,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi trong quá trình tìm kiếm nhanh: {str(e)}",
        )
