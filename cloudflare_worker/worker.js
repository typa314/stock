/**
 * Cloudflare Worker - LINE Bot 邊緣智慧多重備援路由器
 * 
 * 核心特性：
 * 1. 永不休眠、全球邊緣節點加速（延遲 < 15ms）
 * 2. 瀑布式智慧容錯 (Waterfall Failover)：
 *    第 1 順位：本地電腦 (Local PC Tunnel，若有開機享受滿血 CPU 秒回)
 *    第 2 順位：Render 雲端 (主力雲端託管)
 *    第 3 順位：未來備援 (Koyeb / Fly.io / 自建主機，隨時熱插拔)
 * 3. 忠實透傳 LINE Webhook 原始 Payload 與 X-Line-Signature
 * 4. 內建全節點即時健康監控儀表 (GET /health)
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // ── 輔助函式：清理後端網址（自動容錯結尾斜線或誤填 /callback） ──
    const sanitizeBaseUrl = (raw) => {
      if (!raw) return "";
      let u = raw.trim().replace(/\/+$/, "");
      u = u.replace(/\/callback\/?$/i, "");
      return u.replace(/\/+$/, "");
    };

    // ── 1. 定義後端備援節點清單（優先順序由上而下） ──
    const localUrl = sanitizeBaseUrl(env.LOCAL_BACKEND_URL || "");
    const hfUrl = sanitizeBaseUrl(env.HF_BACKEND_URL || "");
    const renderUrl = sanitizeBaseUrl(env.RENDER_BACKEND_URL || "https://tw-stock-bpa-bot.onrender.com");
    const backup3Url = sanitizeBaseUrl(env.BACKUP_3_URL || "");

    const localTimeout = parseInt(env.LOCAL_TIMEOUT_MS || "1500", 10);
    const cloudTimeout = parseInt(env.CLOUD_TIMEOUT_MS || "25000", 10);

    const backends = [];

    // 若有設定本機穿透網址，列為第 1 順位
    if (localUrl) {
      backends.push({
        id: "local_pc",
        name: "💻 本地電腦 (高算力優先)",
        baseUrl: localUrl,
        timeoutMs: localTimeout,
        isLocal: true
      });
    }

    // 若有設定 Hugging Face，列為旗艦主力雲端
    if (hfUrl) {
      backends.push({
        id: "huggingface_cloud",
        name: "🤗 Hugging Face 旗艦雲端 (2核16G ⚡ 極速主力)",
        baseUrl: hfUrl,
        timeoutMs: cloudTimeout,
        isLocal: false
      });
    }

    // Render 雲端為備援守護
    if (renderUrl) {
      backends.push({
        id: "render_cloud",
        name: "☁️ Render 雲端 (留守備援)",
        baseUrl: renderUrl,
        timeoutMs: cloudTimeout,
        isLocal: false
      });
    }

    // 第三備援節點（若有設定）
    if (backup3Url) {
      backends.push({
        id: "backup_tier_3",
        name: "🚀 第三雲端備援 (Koyeb/Fly.io)",
        baseUrl: backup3Url,
        timeoutMs: cloudTimeout,
        isLocal: false
      });
    }

    // ── 2. 健康檢查端點 (GET /health 或 GET /) ──
    if (request.method === "GET" && (path === "/health" || path === "/" || path === "")) {
      const probeResults = await Promise.all(
        backends.map(async (b) => {
          const probeUrl = `${b.baseUrl}/health`;
          const t0 = Date.now();
          try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 3500);
            const res = await fetch(probeUrl, {
              method: "GET",
              signal: controller.signal,
              headers: { "User-Agent": "Cloudflare-Worker-Router/1.0" }
            });
            clearTimeout(timer);
            const latency = Date.now() - t0;
            const data = await res.json().catch(() => null);
            return {
              name: b.name,
              url: b.baseUrl,
              status: res.ok ? "online" : `http_${res.status}`,
              latency_ms: latency,
              details: data
            };
          } catch (err) {
            return {
              name: b.name,
              url: b.baseUrl,
              status: "offline",
              latency_ms: Date.now() - t0,
              error: err.name === "AbortError" ? "timeout_>_3.5s" : err.message
            };
          }
        })
      );

      return new Response(
        JSON.stringify(
          {
            gateway: "Cloudflare Edge Multi-Backend Failover Router",
            version: "1.0.0",
            timestamp: new Date().toISOString(),
            status: "online",
            total_backends: backends.length,
            backends: probeResults
          },
          null,
          2
        ),
        {
          status: 200,
          headers: { "Content-Type": "application/json; charset=utf-8" }
        }
      );
    }

    // ── 3. LINE Webhook 轉發處理 (POST /callback 或 POST /) ──
    if (request.method === "POST") {
      const rawBody = await request.arrayBuffer();

      // 複製並過濾 Header，確保 LINE 簽章完好
      const forwardHeaders = new Headers();
      for (const [key, value] of request.headers.entries()) {
        const k = key.toLowerCase();
        // 排除 Cloudflare 內部專用標頭，保留所有業務標頭
        if (!k.startsWith("cf-") && k !== "host") {
          forwardHeaders.set(key, value);
        }
      }

      const errors = [];

      // 依序嘗試後端節點（瀑布式容錯）
      for (let i = 0; i < backends.length; i++) {
        const b = backends[i];
        const targetUrl = `${b.baseUrl}${path.startsWith("/callback") ? "/callback" : "/callback"}`;

        try {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), b.timeoutMs);

          const res = await fetch(targetUrl, {
            method: "POST",
            headers: forwardHeaders,
            body: rawBody,
            signal: controller.signal
          });

          clearTimeout(timer);

          // 只要收到後端回傳（包含 200 OK 或其他 HTTP 狀態），代表伺服器已接收處理
          if (res.status >= 200 && res.status < 500) {
            const respHeaders = new Headers(res.headers);
            respHeaders.set("X-Handled-By", b.id);
            return new Response(res.body, {
              status: res.status,
              headers: respHeaders
            });
          } else {
            errors.push(`${b.name}: HTTP ${res.status}`);
          }
        } catch (err) {
          const isTimeout = err.name === "AbortError";
          errors.push(`${b.name}: ${isTimeout ? `超時 (> ${b.timeoutMs}ms)` : err.message}`);
          // 容錯機制：自動跳至下一個後端節點
          continue;
        }
      }

      // 若所有節點皆失敗，回傳優雅 200 OK，避免 LINE 重複重發
      console.error("All backends failed:", errors);
      return new Response(
        JSON.stringify({
          status: "fallback",
          message: "All backends temporarily unavailable",
          attempted_errors: errors
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json; charset=utf-8", "X-Handled-By": "cf_edge_fallback" }
        }
      );
    }

    // 其他請求類型預設回覆
    return new Response("LINE Bot Cloudflare Edge Router Online", { status: 200 });
  }
};
