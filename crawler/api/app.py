from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from crawler.api.routes import crawl, health, jobs

app = FastAPI(
    title="News Crawler & LinkedIn CEO Finder API",
    description="FastAPI Backend for automated background news crawling and LinkedIn CEO / Leadership intelligence",
    version="1.1.0",
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

try:
    from linkedin_ceo_finder.api import router as ceo_router
    app.include_router(ceo_router)
except ImportError as err:
    import logging
    logging.warning("linkedin_ceo_finder router could not be loaded: %s", err)

