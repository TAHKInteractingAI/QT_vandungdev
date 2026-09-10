/**
 * Cloudflare Worker: Edge HTTP Endpoint for cron-job.org
 * Forwards full configuration parameters compatible with crawler/cli.py to the FastAPI Backend.
 */
/**
 * Resolves secret from Cloudflare Secrets Store (CRAWLER_BOT) or fallback to env.CRON_SECRET
 */
async function resolveSecret(env) {
  if (env.CRAWLER_BOT && typeof env.CRAWLER_BOT.get === "function") {
    try {
      const val = await env.CRAWLER_BOT.get();
      if (val) return val;
    } catch (err) {
      console.warn("[SecretsStore] Failed to retrieve secret from CRAWLER_BOT binding:", err);
    }
  }
  return env.CRON_SECRET || "vandungdev@qt";
}

async function decodeGoogleNewsUrl(sourceUrl) {
  try {
    const urlObj = new URL(sourceUrl);
    const pathParts = urlObj.pathname.split("/");
    const base64Str = pathParts[pathParts.length - 1].split("?")[0];

    // Strategy 0: Direct base64 regex decode
    try {
      const padded = base64Str + "=".repeat((4 - (base64Str.length % 4)) % 4);
      const decodedB64 = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
      const match = decodedB64.match(/https?:\/\/[^\x00-\x1f\x7f-\xff\s"'<>]+/);
      if (match && !match[0].includes("google.com") && !match[0].includes("google.")) {
        return { status: true, decoded_url: match[0], method: "direct_b64" };
      }
    } catch (_) {}

    // Strategy 1: GET rss/articles
    const rssUrl = `https://news.google.com/rss/articles/${base64Str}`;
    const rssHeaders = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
      "Cookie": "SOCS=CAESEwgDEgk2NDgyOTM5MDQaAmVuIAEaBgiA_L20Bg",
    };
    const rssResp = await fetch(rssUrl, { headers: rssHeaders, redirect: "follow" });
    if (!rssResp.ok) {
      return { status: false, error: `RSS status ${rssResp.status}` };
    }
    const html = await rssResp.text();

    const sgMatch = html.match(/data-n-a-sg="([^"]+)"/);
    const tsMatch = html.match(/data-n-a-ts="([^"]+)"/);
    if (!sgMatch || !tsMatch) {
      return { status: false, error: "c-wiz sig/ts not found in HTML" };
    }
    const sig = sgMatch[1];
    const ts = tsMatch[1];

    // Strategy 2: POST batchexecute
    const beUrl = "https://news.google.com/_/DotsSplashUi/data/batchexecute";
    const payload = [
      "Fbv4je",
      `["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"${base64Str}",${ts},"${sig}"]`,
    ];
    const beData = "f.req=" + encodeURIComponent(JSON.stringify([[payload]]));
    const beHeaders = {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
      "Cookie": "SOCS=CAESEwgDEgk2NDgyOTM5MDQaAmVuIAEaBgiA_L20Bg",
      "Origin": "https://news.google.com",
      "Referer": "https://news.google.com/",
    };
    const beResp = await fetch(beUrl, {
      method: "POST",
      headers: beHeaders,
      body: beData,
    });
    if (!beResp.ok) {
      return { status: false, error: `batchexecute status ${beResp.status}` };
    }
    const beText = await beResp.text();
    const parts = beText.split("\n\n");
    if (parts.length > 1) {
      const parsed = JSON.parse(parts[1]).slice(0, -2);
      const decodedUrl = JSON.parse(parsed[0][2])[1];
      if (decodedUrl && !decodedUrl.includes("google.com") && !decodedUrl.includes("google.")) {
        return { status: true, decoded_url: decodedUrl, method: "batchexecute" };
      }
    }
    return { status: false, error: "batchexecute parse error" };
  } catch (err) {
    return { status: false, error: String(err) };
  }
}

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

    // Endpoint: Decode Google News URL
    if (url.pathname === "/decode") {
      const targetUrl = url.searchParams.get("url");
      if (!targetUrl) {
        return new Response(JSON.stringify({ status: false, error: "Missing ?url= parameter" }), {
          status: 400,
          headers: { "Content-Type": "application/json" }
        });
      }
      const decodeRes = await decodeGoogleNewsUrl(targetUrl);
      return new Response(JSON.stringify(decodeRes), {
        status: decodeRes.status ? 200 : 422,
        headers: { "Content-Type": "application/json" }
      });
    }

    // Endpoint: Proxy Google News RSS
    if (url.pathname === "/rss" || url.pathname.startsWith("/rss/")) {
      const googleRssUrl = `https://news.google.com${url.pathname}${url.search}`;
      try {
        const rssResp = await fetch(googleRssUrl, {
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"
          }
        });
        return new Response(rssResp.body, {
          status: rssResp.status,
          headers: { "Content-Type": "application/rss+xml; charset=utf-8" }
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: String(err) }), { status: 502, headers: { "Content-Type": "application/json" } });
      }
    }

    // Endpoint 2: Trigger Crawler
    if (url.pathname === "/trigger") {
      const authHeader = request.headers.get("X-API-Key") || request.headers.get("Authorization");
      const authQuery = url.searchParams.get("key");
      const secret = await resolveSecret(env);

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
      if (url.searchParams.get("languages")) crawlConfig.lang = url.searchParams.get("languages");
      if (url.searchParams.get("markets")) crawlConfig.lang = url.searchParams.get("markets");
      if (url.searchParams.get("timeout")) crawlConfig.timeout = parseInt(url.searchParams.get("timeout"));
      if (url.searchParams.get("proxy")) crawlConfig.proxy = url.searchParams.get("proxy");
      if (url.searchParams.get("rotate_ua")) crawlConfig.rotate_ua = url.searchParams.get("rotate_ua") === "true";
      if (url.searchParams.get("resume")) crawlConfig.resume = url.searchParams.get("resume") !== "false";
      if (url.searchParams.get("time_window")) crawlConfig.time_window = url.searchParams.get("time_window");
      if (url.searchParams.get("when")) crawlConfig.time_window = url.searchParams.get("when");
      if (url.searchParams.get("storage_mode")) crawlConfig.storage_mode = url.searchParams.get("storage_mode");
      if (url.searchParams.get("timezone")) crawlConfig.timezone = url.searchParams.get("timezone");
      if (url.searchParams.get("tz")) crawlConfig.timezone = url.searchParams.get("tz");
      if (url.searchParams.get("ping_url")) crawlConfig.ping_url = url.searchParams.get("ping_url");

      // If POST, merge JSON body parameters
      if (request.method === "POST") {
        try {
          const body = await request.json();
          crawlConfig = { ...crawlConfig, ...body };
        } catch (e) {}
      }

      // Apply environment variable defaults if not specified
      if (!crawlConfig.keyword && env.DEFAULT_KEYWORD) crawlConfig.keyword = env.DEFAULT_KEYWORD;
      if (!crawlConfig.max_articles && env.DEFAULT_MAX_ARTICLES) crawlConfig.max_articles = parseInt(env.DEFAULT_MAX_ARTICLES);
      if (!crawlConfig.timezone && env.DEFAULT_TIMEZONE) crawlConfig.timezone = env.DEFAULT_TIMEZONE;
      if (!crawlConfig.ping_url && env.CRON_HEARTBEAT_URL) crawlConfig.ping_url = env.CRON_HEARTBEAT_URL;

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
  },

  /**
   * Cloudflare Native Cron Trigger Handler (Optional)
   * Invoked automatically when Cloudflare Cron Trigger fires.
   */
  async scheduled(event, env, ctx) {
    const backendUrl = `${env.BACKEND_API_URL}/api/v1/crawl/trigger`;
    const secret = await resolveSecret(env);
    const crawlConfig = {
      keyword: env.DEFAULT_KEYWORD || "Trillion",
      max_articles: parseInt(env.DEFAULT_MAX_ARTICLES || "20"),
      timezone: env.DEFAULT_TIMEZONE || "Asia/Ho_Chi_Minh",
    };
    if (env.CRON_HEARTBEAT_URL) {
      crawlConfig.ping_url = env.CRON_HEARTBEAT_URL;
    }

    const backendPromise = fetch(backendUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": secret
      },
      body: JSON.stringify(crawlConfig)
    }).catch(err => console.error("[Cron Scheduled] Forwarding failed:", err));

    ctx.waitUntil(backendPromise);
  }
};

