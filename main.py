import uvicorn
from crawler.api.config import settings

if __name__ == "__main__":
    print(f"🚀 Starting Google News Crawler API Server on {settings.APP_HOST}:{settings.APP_PORT} ...")
    uvicorn.run(
        "crawler.api.app:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_ENV == "development",
    )
