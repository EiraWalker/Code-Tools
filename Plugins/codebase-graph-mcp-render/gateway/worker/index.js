const QUERY_TOOLS = new Set([
  "list_projects", "get_architecture", "search_graph", "trace_path", "query_graph"
]);
const page = `<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Codebase Graph Reader</title><style>
body{font-family:system-ui,sans-serif;background:#101923;color:#e9edf1;max-width:48rem;margin:10vh auto;padding:2rem;line-height:1.7}
h1{font-weight:600}code{color:#8cd2bd}a{color:#8cd2bd}</style></head><body>
<h1>Codebase Graph Reader</h1><p>通过原生查询接口读取 你的项目 代码图谱。</p>
<p>连接个人插件后，可以查询项目、架构、符号、调用路径和图关系。</p>
<p><code>list_projects · get_architecture · search_graph · trace_path · query_graph</code></p>
<p>此入口仅供拥有访问权限的账户使用。图谱快照经过完整性校验，查询保持只读。</p>
</body></html>`;

function reply(body, status = 200) {
  return new Response(JSON.stringify(body), {status, headers: {
    "content-type": "application/json", "cache-control": "no-store"
  }});
}
function equalSecret(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === "/") return new Response(page, {headers: {
      "content-type": "text/html; charset=utf-8", "cache-control": "no-store"
    }});
    if (path !== "/mcp") return reply({error: "Not found"}, 404);
    if (request.method !== "POST") return new Response(null, {status: 405, headers: {Allow: "POST"}});
    if (!env.CBM_ENGINE_ORIGIN || !env.CBM_SERVICE_TOKEN) return reply({error: "Engine configuration missing"}, 503);
    if (Number(request.headers.get("content-length")) > 1048576) return reply({error: "Request too large"}, 413);
    const body = await request.text();
    if (new TextEncoder().encode(body).length > 1048576) return reply({error: "Request too large"}, 413);
    let message;
    try { message = JSON.parse(body); } catch { return reply({error: "Invalid JSON"}, 400); }
    if (!message || Array.isArray(message) || message.jsonrpc !== "2.0") return reply({error: "Invalid MCP request"}, 400);
    const method = message.method;
    const discovery = new Set(["initialize", "notifications/initialized", "tools/list", "ping"]);
    if (method === "tools/call") {
      // Sites dispatch authenticates visitors and enforces the owner-private audience.
      // A separate server credential also permits authorized private service calls;
      // this does not manufacture a visitor identity or connected-app consent.
      const user = request.headers.get("oai-authenticated-user-id");
      const service = equalSecret(request.headers.get("x-graph-reader-service-token"), env.CBM_SERVICE_TOKEN);
      if (!user && !service) return reply({error: "Authenticated graph access required"}, 403);
      if (!QUERY_TOOLS.has(message.params?.name)) return reply({jsonrpc: "2.0", id: message.id,
        result: {isError: true, content: [{type: "text", text: "Only the five read-only graph query tools are available"}]}});
    } else if (!discovery.has(method)) {
      return reply({jsonrpc: "2.0", id: message.id ?? null, error: {code: -32601, message: "Method not found"}});
    }
    try {
      const origin = new URL(env.CBM_ENGINE_ORIGIN);
      if (origin.protocol !== "https:") return reply({error: "Engine origin must use HTTPS"}, 503);
      const headers = new Headers({"content-type": "application/json",
        "accept": "application/json, text/event-stream", "authorization": `Bearer ${env.CBM_SERVICE_TOKEN}`});
      const protocol = request.headers.get("mcp-protocol-version");
      if (protocol) headers.set("mcp-protocol-version", protocol);
      const response = await fetch(new URL("/mcp", origin), {
        method: "POST", headers, body, redirect: "manual", signal: AbortSignal.timeout(90000)
      });
      if (response.status >= 300 && response.status < 400) {
        return reply({error: "Engine redirects are not permitted"}, 502);
      }
      if (method === "tools/call" && response.ok && response.headers.get("content-type")?.includes("application/json")) {
        const result = await response.json();
        const snapshot = result.result?._meta?.graph_snapshot;
        if (snapshot && !result.result.structuredContent?.graph_snapshot) {
          // ChatGPT may omit MCP _meta. Preserve the native payload and expose
          // its server-provided provenance through visible result channels too.
          result.result.structuredContent = {...result.result.structuredContent, graph_snapshot: snapshot};
          result.result.content = [...(result.result.content || []), {type: "text", text: JSON.stringify({graph_snapshot: snapshot})}];
        }
        return reply(result, response.status);
      }
      const outputHeaders = new Headers({"cache-control": "no-store"});
      for (const key of ["content-type", "mcp-protocol-version"]) {
        if (response.headers.has(key)) outputHeaders.set(key, response.headers.get(key));
      }
      return new Response(response.body, {status: response.status, headers: outputHeaders});
    } catch {
      return reply({error: "Native graph engine is temporarily unavailable"}, 503);
    }
  }
};
