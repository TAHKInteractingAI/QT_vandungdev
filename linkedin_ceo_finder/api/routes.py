"""FastAPI Routes cho LinkedIn CEO Finder.

Hỗ trợ chạy ngầm trong Background Task (cho cron-job) để phản hồi ngay lập tức,
tránh bị timeout HTTP request.
"""

from datetime import datetime, timezone
import logging
import os
from typing import List, Optional, Union
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from linkedin_ceo_finder.config import (
    DEFAULT_SERVICE_ACCOUNT,
    DEFAULT_SHEET_ID,
    DEFAULT_WORKSHEET_NAME,
    get_default_proxy,
    get_sheet_id,
)
from linkedin_ceo_finder.core import find_ceos_by_domains, find_ceos_by_keyword
from linkedin_ceo_finder.network import _mask_proxy
from .schemas import (
    CEOHealthResponse,
    CEOJobTriggerResponse,
    CEOLeadSchema,
    CEOSearchResponse,
    DomainSearchRequest,
    KeywordSearchRequest,
)
from .security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ceo", tags=["LinkedIn CEO Finder"])


def _run_background_domain_search(
    job_id: str,
    domains: List[str],
    target_count: Optional[int],
    save_to_sheet: bool,
    max_workers: int,
    sheet_id: str,
    worksheet_name: str,
    proxy: Optional[str],
) -> None:
    """Tác vụ tìm kiếm CEO theo domain thực thi ngầm trong nền."""
    effective_p = proxy or get_default_proxy()
    logger.info("🚀 [CEO Job %s] Bắt đầu quét ngầm cho %d domain [Proxy: %s]...", job_id, len(domains), _mask_proxy(effective_p))
    try:
        leads = find_ceos_by_domains(
            company_domains=domains,
            target_count=target_count,
            save_to_sheet=save_to_sheet,
            max_workers=max_workers,
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            proxy=effective_p,
        )
        logger.info("✅ [CEO Job %s] Hoàn thành: tìm thấy %d CEO.", job_id, len(leads))
    except Exception as e:
        logger.error("❌ [CEO Job %s] Thất bại khi quét domain: %s", job_id, e)


def _run_background_keyword_search(
    job_id: str,
    keywords: Optional[List[str]] = None,
    keyword: Optional[str] = None,
    target_count: int = 5,
    save_to_sheet: bool = True,
    max_workers: int = 5,
    sheet_id: str = "",
    worksheet_name: str = "",
    proxy: Optional[str] = None,
    skip_empty_company: bool = False,
    max_pages: int = 5,
) -> None:
    """Tác vụ tìm kiếm CEO theo keyword thực thi ngầm trong nền (hỗ trợ nhiều từ khóa song song)."""
    effective_p = proxy or get_default_proxy()
    actual_kws = keywords or ([keyword] if keyword else ["Fintech Vietnam"])
    kw_str = ", ".join(actual_kws[:3]) + ("..." if len(actual_kws) > 3 else "")
    logger.info("🚀 [CEO Job %s] Bắt đầu tìm kiếm ngầm cho %d từ khóa: '%s' [Proxy: %s]...", job_id, len(actual_kws), kw_str, _mask_proxy(effective_p))
    try:
        leads = find_ceos_by_keyword(
            keywords=actual_kws,
            target_count=target_count,
            save_to_sheet=save_to_sheet,
            max_workers=max_workers,
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            proxy=effective_p,
            skip_empty_company=skip_empty_company,
            max_pages=max_pages,
        )
        logger.info("✅ [CEO Job %s] Hoàn thành: tìm thấy %d CEO mới.", job_id, len(leads))
    except Exception as e:
        logger.error("❌ [CEO Job %s] Thất bại khi quét keyword: %s", job_id, e)


@router.get("/health", response_model=CEOHealthResponse)
async def health_check():
    """Kiểm tra trạng thái hoạt động và cấu hình Google Sheet của LinkedIn CEO Finder."""
    sheet_id = get_sheet_id()
    sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_SERVICE_ACCOUNT)
    sa_configured = bool(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.path.exists("/etc/secrets/service_account.json")
        or (sa_path and os.path.exists(sa_path))
    )

    return CEOHealthResponse(
        status="ok",
        service="linkedin-ceo-finder",
        sheet_configured=bool(sheet_id),
        service_account_configured=sa_configured,
        timestamp=datetime.now(timezone.utc),
    )



@router.post(
    "/domains",
    response_model=Union[CEOJobTriggerResponse, CEOSearchResponse],
    dependencies=[Depends(verify_api_key)],
)
async def search_by_domains(
    request: DomainSearchRequest,
    background_tasks: BackgroundTasks,
):
    """Tìm kiếm CEO theo danh sách tên miền website.

    - Mặc định (sync=False, tối ưu cho cron-job): Chạy nền và trả về ngay thông báo 'running' (không lo timeout).
    - Đồng bộ (sync=True): Chờ quét xong và trả về đầy đủ danh sách CEO.
    """
    target_sheet = request.sheet_id or DEFAULT_SHEET_ID
    target_ws = request.worksheet_name or DEFAULT_WORKSHEET_NAME
    target_proxy = request.proxy or get_default_proxy()

    # 1. Chế độ bất đồng bộ / Chạy ngầm (Mặc định cho cron-job)
    if not request.sync:
        job_id = f"ceo_dom_{uuid.uuid4().hex[:8]}"
        background_tasks.add_task(
            _run_background_domain_search,
            job_id=job_id,
            domains=request.domains,
            target_count=request.target_count,
            save_to_sheet=request.save_to_sheet,
            max_workers=request.max_workers,
            sheet_id=target_sheet,
            worksheet_name=target_ws,
            proxy=target_proxy,
        )
        return CEOJobTriggerResponse(
            status="running",
            message=f"Tiến trình tìm kiếm CEO cho {len(request.domains)} tên miền đang chạy ngầm trong nền.",
            job_id=job_id,
            mode="domains",
            target=", ".join(request.domains[:3]) + ("..." if len(request.domains) > 3 else ""),
            save_to_sheet=request.save_to_sheet,
        )

    # 2. Chế độ đồng bộ (sync=True)
    try:
        leads = find_ceos_by_domains(
            company_domains=request.domains,
            target_count=request.target_count,
            save_to_sheet=request.save_to_sheet,
            max_workers=request.max_workers,
            sheet_id=target_sheet,
            worksheet_name=target_ws,
            proxy=target_proxy,
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
    response_model=Union[CEOJobTriggerResponse, CEOSearchResponse],
    dependencies=[Depends(verify_api_key)],
)
async def search_by_keyword(
    request: KeywordSearchRequest,
    background_tasks: BackgroundTasks,
):
    """Tìm kiếm CEO theo từ khóa ngành nghề.

    - Mặc định (sync=False, tối ưu cho cron-job): Chạy nền và trả về ngay thông báo 'running' (không lo timeout).
    - Đồng bộ (sync=True): Chờ quét xong và trả về đầy đủ danh sách CEO.
    """
    target_sheet = request.sheet_id or DEFAULT_SHEET_ID
    target_ws = request.worksheet_name or DEFAULT_WORKSHEET_NAME
    target_proxy = request.proxy or get_default_proxy()
    resolved_kws = request.resolve_keywords()
    target_display = ", ".join(resolved_kws[:3]) + ("..." if len(resolved_kws) > 3 else "")

    # 1. Chế độ bất đồng bộ / Chạy ngầm (Mặc định cho cron-job)
    if not request.sync:
        job_id = f"ceo_kw_{uuid.uuid4().hex[:8]}"
        background_tasks.add_task(
            _run_background_keyword_search,
            job_id=job_id,
            keywords=resolved_kws,
            target_count=request.target_count,
            save_to_sheet=request.save_to_sheet,
            max_workers=request.max_workers,
            sheet_id=target_sheet,
            worksheet_name=target_ws,
            proxy=target_proxy,
            skip_empty_company=request.skip_empty_company,
            max_pages=request.max_pages,
        )
        return CEOJobTriggerResponse(
            status="running",
            message=f"Tiến trình tìm kiếm CEO cho {len(resolved_kws)} từ khóa ({target_display}) đang chạy ngầm trong nền.",
            job_id=job_id,
            mode="keyword",
            target=target_display,
            save_to_sheet=request.save_to_sheet,
        )

    # 2. Chế độ đồng bộ (sync=True)
    try:
        leads = find_ceos_by_keyword(
            keywords=resolved_kws,
            target_count=request.target_count,
            save_to_sheet=request.save_to_sheet,
            max_workers=request.max_workers,
            sheet_id=target_sheet,
            worksheet_name=target_ws,
            proxy=target_proxy,
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
            message=f"Đã tìm thấy {len(leads_data)} CEO từ {len(resolved_kws)} từ khóa ({target_display}).",
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
    response_model=Union[CEOJobTriggerResponse, CEOSearchResponse],
    dependencies=[Depends(verify_api_key)],
)
async def quick_search(
    background_tasks: BackgroundTasks,
    keyword: str = Query(..., description="Từ khóa ngành nghề cần tìm kiếm"),
    count: int = Query(3, ge=1, le=20, description="Số lượng CEO cần tìm"),
    save_to_sheet: bool = Query(True, description="Có lưu vào Google Sheet không"),
    sync: bool = Query(False, description="Chạy đồng bộ hay nền (mặc định False: chạy nền)"),
):
    """Tìm kiếm nhanh CEO qua GET (hỗ trợ cron-job gọi qua URL webhook hoặc browser)."""
    target_proxy = get_default_proxy()

    if not sync:
        job_id = f"ceo_quick_{uuid.uuid4().hex[:8]}"
        background_tasks.add_task(
            _run_background_keyword_search,
            job_id=job_id,
            keyword=keyword,
            target_count=count,
            save_to_sheet=save_to_sheet,
            sheet_id=DEFAULT_SHEET_ID,
            worksheet_name=DEFAULT_WORKSHEET_NAME,
            proxy=target_proxy,
            skip_empty_company=False,
            max_pages=5,
        )
        return CEOJobTriggerResponse(
            status="running",
            message=f"Tiến trình tìm kiếm nhanh CEO cho từ khóa '{keyword}' đang chạy ngầm trong nền.",
            job_id=job_id,
            mode="keyword",
            target=keyword,
            save_to_sheet=save_to_sheet,
        )

    try:
        leads = find_ceos_by_keyword(
            keyword=keyword,
            target_count=count,
            save_to_sheet=save_to_sheet,
            proxy=target_proxy,
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

