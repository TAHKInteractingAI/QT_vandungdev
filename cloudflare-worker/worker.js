/**
 * Cloudflare Worker: Edge HTTP Endpoint for cron-job.org
 * Forwards full configuration parameters compatible with crawler/cli.py to the FastAPI Backend.
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Endpoint 1: Healthcheck
    if (url.pathname === "/health" || url.pathname === "/") {
      return new Response(JSON.stringify({
        status: "ok",
        service: "google-news-crawler-worker",
        timestamp: new Date().toISOString()
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    // Endpoint 2: Trigger Crawler
    if (url.pathname === "/trigger") {
      const authHeader = request.headers.get("X-API-Key") || request.headers.get("Authorization");
      const authQuery = url.searchParams.get("key");
      const secret = env.CRON_SECRET || "test-secret-key-123";

      if (authHeader !== secret && authHeader !== `Bearer ${secret}` && authQuery !== secret) {
        return new Response(JSON.stringify({ error: "Unauthorized: Invalid API Key" }), {
          status: 401,
          headers: { "Content-Type": "application/json" }
        });
      }

      // Default parameters from query params
      let crawlConfig = {};
      if (url.searchParams.get("keyword")) crawlConfig.keyword = url.searchParams.get("keyword");
      if (url.searchParams.get("max")) crawlConfig.max_articles = parseInt(url.searchParams.get("max"));
      if (url.searchParams.get("workers")) crawlConfig.workers = parseInt(url.searchParams.get("workers"));
      if (url.searchParams.get("lang")) crawlConfig.lang = url.searchParams.get("lang");
      if (url.searchParams.get("country")) crawlConfig.country = url.searchParams.get("country");
      if (url.searchParams.get("timeout")) crawlConfig.timeout = parseInt(url.searchParams.get("timeout"));
      if (url.searchParams.get("proxy")) crawlConfig.proxy = url.searchParams.get("proxy");
      if (url.searchParams.get("rotate_ua")) crawlConfig.rotate_ua = url.searchParams.get("rotate_ua") === "true";
      if (url.searchParams.get("resume")) crawlConfig.resume = url.searchParams.get("resume") !== "false";

      // If POST, merge JSON body parameters
      if (request.method === "POST") {
        try {
          const body = await request.json();
          crawlConfig = { ...crawlConfig, ...body };
        } catch (e) {}
      }

      // Forward request to FastAPI Backend in background (via ctx.waitUntil)
      const backendUrl = `${env.BACKEND_API_URL}/api/v1/crawl/trigger`;
      const backendPromise = fetch(backendUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": secret
        },
        body: JSON.stringify(crawlConfig)
      }).catch(err => console.error("Forwarding failed:", err));

      ctx.waitUntil(backendPromise);

      // Return immediate response < 50ms to caller (prevents webhook timeout)
      return new Response(JSON.stringify({
        status: "accepted",
        message: "Crawl tool triggered successfully with custom CLI params.",
        config: crawlConfig,
        triggered_at: new Date().toISOString()
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }

    return new Response(JSON.stringify({ error: "Not Found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" }
    });
  }
};
