from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import crawl, health, jobs

app = FastAPI(
    title="Google News Crawler API",
    description="FastAPI Backend for automated background news crawling triggered via Cloudflare Worker and cron-job.org",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(crawl.router)
app.include_router(jobs.router)
