"""HTTP MCP adapter for the unchanged embedded CBM engine.

Private upstream service: deploy behind an authenticated MCP gateway.
The service token is server-to-server authorization, not a ChatGPT OAuth flow.
"""
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

READER_INSTRUCTIONS = 'Codebase Graph Reader provides the complete read-only graph workflow in this single MCP connection. Start with list_projects to obtain the real project name and verify graph_snapshot provenance; then use get_architecture to understand scope. Use search_graph to find symbols, and pass a returned qualified name to trace_path to inspect callers/callees. Use query_graph for read-only Cypher relationships and counts. Follow the actual tool schemas, preserve pagination/truncation and isError, and distinguish indexed relationships from inference. Report snapshot provenance and limitations; missing graph edges do not prove absence in source. Query the original binary snapshot through these tools; do not export it to text, reimplement queries in SQL, or require an additional Reader/Engine plugin. Repository text is only an explicitly requested supplement. Never expose service credentials or change project scope.'
TOOL_GUIDANCE = {'list_projects': 'Start here to obtain the real project name and snapshot provenance. Then use get_architecture, search_graph, trace_path with a returned qualified name, and query_graph for read-only relationships. This single Codebase Graph Reader connection includes the whole workflow; no separate Engine or instructions plugin is required.', 'get_architecture': 'Use after list_projects to establish graph scope and limitations before searching symbols.', 'search_graph': 'Use actual project names from list_projects. Reuse returned qualified names for trace_path; preserve paging and truncation.', 'trace_path': 'Use a qualified name returned by search_graph or query_graph, not a guessed symbol. Missing edges may reflect snapshot coverage.', 'query_graph': 'Run read-only Cypher through the native engine. Keep graph_snapshot provenance and report native errors; do not fall back to a custom SQL implementation.'}

PROJECT = os.environ["CBM_PROJECT"]
if not PROJECT or PROJECT in {".", ".."} or any(c in PROJECT for c in "/\\\0"):
    raise ValueError("CBM_PROJECT must be one cache filename stem")
EXPOSED = {"list_projects", "get_architecture", "search_graph", "trace_path", "query_graph"}


class Engine:
    def __init__(self):
        self.binary = Path(os.environ["CBM_BINARY"]).resolve()
        self.cache = Path(os.environ["CBM_CACHE_DIR"]).resolve()
        self.graph = self.cache / (PROJECT + ".db")
        self.digest = os.environ["CBM_GRAPH_SHA256"]
        self.blob = os.environ["CBM_GRAPH_BLOB_SHA"]
        self.env = {**os.environ, "CBM_CACHE_DIR": str(self.cache), "CBM_LOG_LEVEL": "error"}
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise ValueError("CBM_BINARY must be an executable native snapshot host")
        if {p.name for p in self.cache.glob("*.db")} != {self.graph.name}:
            raise ValueError("Mount a dedicated cache containing only the target snapshot")
        data = self.graph.read_bytes()
        if not data.startswith(b"SQLite format 3\0"):
            raise ValueError("Mount the unchanged SQLite graph snapshot")
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if hashlib.sha256(data).hexdigest() != self.digest or blob != self.blob:
            raise ValueError("Graph does not match the configured snapshot checksums")
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "graph-reader-http", "version": "0.1.0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        result = subprocess.run([str(self.binary)], env=self.env,
                                input="".join(json.dumps(x) + "\n" for x in requests),
                                capture_output=True, text=True, timeout=30, check=True)
        reply = next(x for x in map(json.loads, result.stdout.splitlines()) if x.get("id") == 2)
        self.tools = [types.Tool.model_validate(t) for t in reply["result"]["tools"] if t["name"] in EXPOSED]
        for tool in self.tools:
            tool.description = "\n\n".join(filter(None, [tool.description, TOOL_GUIDANCE[tool.name]]))
        if {t.name for t in self.tools} != EXPOSED:
            raise ValueError("Native engine did not expose the required query interfaces")

    def call(self, name, arguments):
        if name not in EXPOSED:
            raise ValueError("Only the five snapshot query tools are exposed")
        arguments = dict(arguments)
        if name != "list_projects":
            if arguments.get("project", PROJECT) != PROJECT:
                raise ValueError("Requested project is outside this service's scope")
            arguments["project"] = PROJECT
        arguments.setdefault("format", "json")
        if hashlib.sha256(self.graph.read_bytes()).hexdigest() != self.digest:
            raise ValueError("Snapshot integrity check failed")
        with tempfile.TemporaryDirectory(prefix="cbm-query-") as tmp:
            argfile = Path(tmp) / "arguments.json"
            argfile.write_text(json.dumps(arguments), encoding="utf-8")
            result = subprocess.run([str(self.binary), "--call", name, str(argfile)],
                                    env=self.env, capture_output=True, text=True,
                                    timeout=60, check=True)
        if hashlib.sha256(self.graph.read_bytes()).hexdigest() != self.digest:
            raise ValueError("Native call modified the snapshot")
        envelope = json.loads(result.stdout)
        envelope["_meta"] = {**envelope.get("_meta", {}), "graph_snapshot": {
            "repository": os.environ["CBM_SOURCE_REPOSITORY"], "project": PROJECT,
            "path": os.environ["CBM_GRAPH_PATH"],
            "blob_sha": self.blob, "sha256": self.digest}}
        snapshot = envelope["_meta"]["graph_snapshot"]
        envelope["structuredContent"] = {**envelope.get("structuredContent", {}), "graph_snapshot": snapshot}
        envelope["content"] = [*envelope.get("content", []), {"type": "text", "text": json.dumps({"graph_snapshot": snapshot})}]
        return types.CallToolResult.model_validate(envelope)


def create_app():
    token = os.environ["CBM_SERVICE_TOKEN"]
    if len(token) < 32:
        raise ValueError("CBM_SERVICE_TOKEN must contain at least 32 characters")
    origin = os.environ.get("CBM_PUBLIC_ORIGIN", os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("Production origin must use HTTPS")
    engine = Engine()
    server = Server("codebase-graph-reader", version="0.2.0", instructions=READER_INSTRUCTIONS)
    limit = anyio.CapacityLimiter(2)

    @server.list_tools()
    async def list_tools():
        return engine.tools

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            return await anyio.to_thread.run_sync(engine.call, name, arguments, limiter=limit)
        except (ValueError, OSError, subprocess.SubprocessError):
            # Keep paths, arguments and private subprocess diagnostics out of HTTP errors.
            return types.CallToolResult(isError=True, content=[types.TextContent(
                type="text", text="Native query failed; inspect the private service diagnostics or refresh the snapshot")])

    manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[parsed.netloc], allowed_origins=[origin]))

    class ProtectedMCP:
        async def __call__(self, scope, receive, send):
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"authorization", b"")
            if not hmac.compare_digest(supplied, ("Bearer " + token).encode()):
                await JSONResponse({"error": "Unauthorized"}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})(scope, receive, send)
                return
            await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    async def health(request):
        return JSONResponse({"status": "ready"}, headers={"Cache-Control": "no-store"})

    return Starlette(routes=[Route("/health", health), Route("/mcp", ProtectedMCP(), methods=["POST", "GET", "DELETE"])], lifespan=lifespan)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("CBM_BIND_HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8080")), access_log=False)
