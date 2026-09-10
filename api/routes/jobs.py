from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from api.services.job_manager import job_manager

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


@router.get("/latest")
async def get_latest_job():
    job = job_manager.get_latest_job()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No jobs found",
        )
    return job


@router.get("/{job_id}")
async def get_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return job


@router.get("/{job_id}/download/excel")
async def download_job_excel(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if job["status"] == "running":
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail="Job is still running. Please wait for completion.",
        )
    if job["status"] == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Job failed: {job.get('error')}",
        )

    excel_path_str = job.get("excel_path")
    if not excel_path_str or not Path(excel_path_str).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Excel output file not found",
        )

    path = Path(excel_path_str)
    return FileResponse(
        path=path,
        filename=f"articles_{job_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{job_id}/download/json")
async def download_job_json(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if job["status"] == "running":
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail="Job is still running. Please wait for completion.",
        )
    if job["status"] == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Job failed: {job.get('error')}",
        )

    json_path_str = job.get("json_path")
    # Fallback to output_dir / articles.json if json_path is not explicitly saved
    if not json_path_str and job.get("output_dir"):
        candidate = Path(job["output_dir"]) / "articles.json"
        if candidate.exists():
            json_path_str = str(candidate)

    if not json_path_str or not Path(json_path_str).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="JSON output file not found",
        )

    path = Path(json_path_str)
    return FileResponse(
        path=path,
        filename=f"articles_{job_id}.json",
        media_type="application/json",
    )
