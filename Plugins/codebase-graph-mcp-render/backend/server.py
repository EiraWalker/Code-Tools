"""HTTP MCP adapter for the unchanged embedded CBM engine.

Private upstream service: deploy behind an authenticated MCP gateway.
The service token is server-to-server authorization, not a ChatGPT OAuth flow.
"""
from contextlib import asynccontextmanager
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
from snapshot_cache import SnapshotCache
from snapshot_sync import PublisherAuth, PublisherScopeError, validate_identity
import jwt
from index_catalog import load_indexes
from github_indexes import GitHubIndexes

READER_INSTRUCTIONS = 'Codebase Graph Reader provides the complete read-only graph workflow in this single MCP connection. Start with list_projects to obtain the real project name and verify graph_snapshot provenance; then use get_architecture to understand scope. Use search_graph to find symbols, and pass a returned qualified name to trace_path to inspect callers/callees. Use query_graph for read-only Cypher relationships and counts. Follow the actual tool schemas, preserve pagination/truncation and isError, and distinguish indexed relationships from inference. Report snapshot provenance and limitations; missing graph edges do not prove absence in source. Query the original binary snapshot through these tools; do not export it to text, reimplement queries in SQL, or require an additional Reader/Engine plugin. Repository text is only an explicitly requested supplement. Choose any configured index listed by list_projects; pass its exact project name to every graph query. Each project has its own snapshot provenance and cache. Changing projects requires no additional plugin. When the user requests a new GitHub source, use add_index with the repository or graph link; if it returns multiple candidates, select the requested graph_path. Registration consumes an existing compatible .db graph, not source code. Private GitHub credentials belong in backend configuration, never chat. New projects appear in list_projects without another plugin or deployment. Keep refresh_warning visible when a cached graph is served after a remote check failure; never expose service credentials.'
TOOL_GUIDANCE = {'list_projects': 'Start here to list configured indexes and obtain each real project name and snapshot provenance. Choose the requested index and pass its exact name as project to subsequent tools. Then use get_architecture, search_graph, trace_path with a returned qualified name, and query_graph for read-only relationships. This single Codebase Graph Reader connection includes the whole workflow; no separate Engine or instructions plugin is required.', 'get_architecture': 'Use after list_projects to establish graph scope and limitations before searching symbols.', 'search_graph': 'Use actual project names from list_projects. Reuse returned qualified names for trace_path; preserve paging and truncation.', 'trace_path': 'Use a qualified name returned by search_graph or query_graph, not a guessed symbol. Missing edges may reflect snapshot coverage.', 'query_graph': 'Run read-only Cypher through the native engine. Keep graph_snapshot provenance and report native errors; do not fall back to a custom SQL implementation.'}

EXPOSED = {"list_projects", "get_architecture", "search_graph", "trace_path", "query_graph"}

ADD_INDEX_TOOL = types.Tool(name="add_index", description="Register an original codebase-memory-mcp .db snapshot from a GitHub repository, blob or tree link. Downloads once, validates through the native reader, then caches the graph. If multiple .db files exist, returns candidates: repeat with graph_path. Does not generate indexes or read repository source. Private repositories require backend-configured GitHub Contents read credentials, never chat credentials. New indexes are checked for remote changes on use (default every 300 seconds); unchanged blobs are never downloaded again. Changes the authorized project's catalog; all five graph query tools remain read-only.",
    inputSchema={"type": "object", "properties": {
        "github_url": {"type": "string", "description": "HTTPS github.com repository root, blob or tree link."},
        "graph_path": {"type": "string", "description": "Optional relative path to one original uncompressed .db graph."},
        "ref": {"type": "string", "description": "Branch/tag/commit; defaults to repository default branch. Supply explicitly for ambiguous slash-containing refs."},
        "project": {"type": "string", "description": "Original project identity in the graph; defaults to database filename stem. This does not rename graph contents."}},
        "required": ["github_url"], "additionalProperties": False},
    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True))


class Engine:
    def __init__(self, config):
        self.config = config
        self.project = config["CBM_PROJECT"]
        self.binary = Path(os.environ["CBM_BINARY"]).resolve()
        self.cache = Path(config["CBM_CACHE_DIR"]).resolve()
        self.snapshots = SnapshotCache(self.cache, self.project, config["CBM_GRAPH_SHA256"],
                                       config["CBM_GRAPH_BLOB_SHA"],
                                       int(config.get("CBM_GRAPH_MAX_BYTES", "268435456")))
        self.env = {**{k: v for k, v in os.environ.items() if k in {"PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}},
                    "CBM_CACHE_DIR": str(self.cache), "CBM_LOG_LEVEL": "error"}
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise ValueError("CBM_BINARY must be an executable native snapshot host")
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "graph-reader-http", "version": "0.1.0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        result = subprocess.run([str(self.binary)], env={**self.env, "CBM_CACHE_DIR": str(self.snapshots.active.directory)},
                                input="".join(json.dumps(x) + "\n" for x in requests),
                                capture_output=True, text=True, timeout=30, check=True)
        reply = next(x for x in map(json.loads, result.stdout.splitlines()) if x.get("id") == 2)
        self.tools = [types.Tool.model_validate(t) for t in reply["result"]["tools"] if t["name"] in EXPOSED]
        for tool in self.tools:
            tool.description = "\n\n".join(filter(None, [tool.description, TOOL_GUIDANCE[tool.name]]))
        if {t.name for t in self.tools} != EXPOSED:
            raise ValueError("Native engine did not expose the required query interfaces")

    def call(self, name, arguments):
        with self.snapshots.lock:
            return self._call(name, arguments, self.snapshots.active)

    def validate_candidate(self, snapshot):
        envelope = self._native("list_projects", {"detail": "stats", "format": "json"}, snapshot)
        if envelope.get("isError"):
            raise ValueError("Native engine rejected candidate snapshot")
        payload = envelope.get("structuredContent")
        if not payload or "projects" not in payload:
            payload = json.loads(next(c["text"] for c in envelope["content"] if c["type"] == "text"))
        if [p["name"] for p in payload.get("projects", [])] != [self.project]:
            raise ValueError("Candidate project does not match the configured scope")

    def _native(self, name, arguments, snapshot):
        with tempfile.TemporaryDirectory(prefix="cbm-query-") as tmp:
            argfile = Path(tmp) / "arguments.json"
            argfile.write_text(json.dumps(arguments), encoding="utf-8")
            result = subprocess.run([str(self.binary), "--call", name, str(argfile)],
                                    env={**self.env, "CBM_CACHE_DIR": str(snapshot.directory)},
                                    capture_output=True, text=True, timeout=60, check=True)
        return json.loads(result.stdout)

    def _call(self, name, arguments, snapshot):
        if name not in EXPOSED:
            raise ValueError("Only the five snapshot query tools are exposed")
        arguments = dict(arguments)
        if name != "list_projects":
            if arguments.get("project", self.project) != self.project:
                raise ValueError("Requested project is outside this service's scope")
            arguments["project"] = self.project
        arguments.setdefault("format", "json")
        self.snapshots.validate(snapshot)
        envelope = self._native(name, arguments, snapshot)
        self.snapshots.validate(snapshot)
        envelope["_meta"] = {**envelope.get("_meta", {}), "graph_snapshot": {
            "repository": self.config["CBM_SOURCE_REPOSITORY"], "project": self.project,
            "path": self.config["CBM_GRAPH_PATH"],
            "blob_sha": snapshot.blob_sha, "sha256": snapshot.sha256,
            **({"source_commit": snapshot.source_commit} if snapshot.source_commit else {})}}
        snapshot = envelope["_meta"]["graph_snapshot"]
        envelope["structuredContent"] = {**envelope.get("structuredContent", {}), "graph_snapshot": snapshot}
        envelope["content"] = [*envelope.get("content", []), {"type": "text", "text": json.dumps({"graph_snapshot": snapshot})}]
        return types.CallToolResult.model_validate(envelope)


class ProjectSelectionError(ValueError):
    """Safe client guidance without private configuration or credentials."""


class Catalog:
    def __init__(self, configs, engine_factory=Engine):
        self.engines = {project: engine_factory(config) for project, config in configs.items()}
        self.tools = [*next(iter(self.engines.values())).tools, ADD_INDEX_TOOL]
        self.github = None
        for engine in self.engines.values():
            engine.validate_candidate(engine.snapshots.active)

    def query(self, engine, name, arguments):
        if self.github:
            self.github.refresh(engine.project)
        result = engine.call(name, arguments)
        if self.github and engine.project in self.github.errors:
            warning = self.github.errors[engine.project]
            result.structuredContent = {**(result.structuredContent or {}), "refresh_warning": warning}
            result.content.append(types.TextContent(type="text", text=warning))
        return result

    def select(self, project):
        if project is None and len(self.engines) == 1:
            return next(iter(self.engines.values()))
        if not isinstance(project, str) or project not in self.engines:
            raise ProjectSelectionError("Choose a configured project from list_projects and pass its exact name as project.")
        return self.engines[project]

    def call(self, name, arguments):
        arguments = arguments or {}
        if name == "add_index":
            if self.github is None:
                raise ValueError("GitHub registration is unavailable")
            error, payload = self.github.result(arguments)
            return types.CallToolResult(isError=error, content=[types.TextContent(type="text", text=json.dumps(payload))], structuredContent=payload)
        if name != "list_projects":
            engine = self.select(arguments.get("project"))
            return self.query(engine, name, arguments)
        if len(self.engines) == 1:
            return self.query(next(iter(self.engines.values())), name, arguments)
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 50)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Invalid catalog pagination")
        # Page the configured catalog, then ask the native reader for each selected index.
        engines = list(self.engines.values())[offset:offset + limit]
        projects, snapshots = [], {}
        for engine in engines:
            result = self.query(engine, name, {**arguments, "format": "json", "offset": 0, "limit": 1})
            if result.isError:
                return result
            payload = result.structuredContent
            if not payload or not payload.get("projects"):
                raise ValueError("Configured native index is unavailable")
            snapshot = payload["graph_snapshot"]
            projects.extend({**p, "graph_snapshot": snapshot, **({"refresh_warning": payload["refresh_warning"]} if "refresh_warning" in payload else {})} for p in payload["projects"])
            snapshots[engine.project] = snapshot
        payload = {"projects": projects, "total": len(self.engines), "offset": offset, "limit": limit,
                   "returned": len(projects), "has_more": offset + len(projects) < len(self.engines),
                   "graph_snapshots": snapshots}
        output = json.dumps(payload) if arguments.get("format", "json") == "json" else "\n".join(
            [p["name"] for p in projects] + [json.dumps({k: v for k, v in payload.items() if k != "projects"})])
        return types.CallToolResult(content=[types.TextContent(type="text", text=output)], structuredContent=payload)


def create_app():
    token = os.environ["CBM_SERVICE_TOKEN"]
    if len(token) < 32:
        raise ValueError("CBM_SERVICE_TOKEN must contain at least 32 characters")
    origin = os.environ.get("CBM_PUBLIC_ORIGIN", os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    parsed = urlparse(origin)
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Public origin must be one origin without a path or query")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("Production origin must use HTTPS")
    catalog = Catalog(load_indexes())
    catalog.github = GitHubIndexes(catalog, os.environ["CBM_CACHE_DIR"], Engine)
    server = Server("codebase-graph-reader", version="0.4.0", instructions=READER_INSTRUCTIONS)
    limit = anyio.CapacityLimiter(2)
    sync_limit = anyio.CapacityLimiter(1)
    publishers = {project: PublisherAuth(origin, engine.config)
                  for project, engine in catalog.engines.items() if engine.config.get("CBM_SYNC_REPOSITORY")}

    @server.list_tools()
    async def list_tools():
        return catalog.tools

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            return await anyio.to_thread.run_sync(catalog.call, name, arguments, limiter=limit)
        except ProjectSelectionError as error:
            return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text=str(error))])
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
            try:
                yield
            finally:
                if catalog.github:
                    catalog.github.source.client.close()

    async def health(request):
        return JSONResponse({"status": "ready"}, headers={"Cache-Control": "no-store"})

    async def sync_snapshot(request):
        headers = {"Cache-Control": "no-store"}
        try:
            engine = catalog.select(request.headers.get("x-snapshot-project"))
        except ProjectSelectionError:
            return JSONResponse({"error": "Select one configured project with X-Snapshot-Project"}, status_code=422, headers=headers)
        publisher = publishers.get(engine.project)
        if publisher is None:
            return JSONResponse({"error": "Sync is disabled"}, status_code=404, headers=headers)
        try:
            claims = await anyio.to_thread.run_sync(publisher.verify,
                request.headers.get("authorization", ""), limiter=sync_limit)
        except (ValueError, KeyError, OSError, jwt.PyJWTError) as error:
            detail = str(error) if isinstance(error, PublisherScopeError) else type(error).__name__
            print("Snapshot publisher rejected: " + detail, flush=True)
            return JSONResponse({"error": "Unauthorized publisher"}, status_code=401, headers=headers)
        number, attempt = int(claims["run_number"]), int(claims["run_attempt"])
        incoming = None
        try:
            if request.method == "POST":
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 4096:
                        raise ValueError("Snapshot metadata too large")
                metadata = json.loads(body)
                if not isinstance(metadata, dict) or metadata.get("project", engine.project) != engine.project:
                    raise ValueError("Snapshot project and selected index differ")
                identity = validate_identity(metadata, engine.snapshots.maximum)
            else:
                identity = validate_identity({"sha256": request.headers.get("x-snapshot-sha256"),
                    "blob_sha": request.headers.get("x-snapshot-blob-sha"),
                    "size_bytes": int(request.headers.get("content-length", "0")),
                    "source_commit": request.headers.get("x-source-commit")}, engine.snapshots.maximum)
            if identity["source_commit"] != claims["sha"]:
                raise ValueError("Snapshot and publisher source commits differ")
            status = await anyio.to_thread.run_sync(engine.snapshots.check, identity, number, attempt,
                                                   limiter=sync_limit)
            if request.method == "PUT" and status == "upload_required":
                with tempfile.NamedTemporaryFile(dir=engine.cache, prefix=".upload-", delete=False) as f:
                    incoming = Path(f.name)
                    size = 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > identity["size_bytes"]:
                            raise ValueError("Snapshot upload exceeds declared size")
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                status = await anyio.to_thread.run_sync(engine.snapshots.install, incoming, identity,
                    number, attempt, engine.validate_candidate, limiter=sync_limit)
                if status == "refreshed":
                    print("Original graph cache refreshed and native validation passed", flush=True)
            return JSONResponse({"status": status}, headers=headers)
        except (ValueError, KeyError, OSError, subprocess.SubprocessError):
            print("Snapshot sync rejected; previous cache retained", flush=True)
            return JSONResponse({"error": "Snapshot validation failed; previous cache retained"},
                                status_code=422, headers=headers)
        finally:
            if incoming is not None:
                incoming.unlink(missing_ok=True)

    return Starlette(routes=[Route("/health", health),
        Route("/snapshot-sync", sync_snapshot, methods=["POST", "PUT"]),
        Route("/mcp", ProtectedMCP(), methods=["POST", "GET", "DELETE"])], lifespan=lifespan)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("CBM_BIND_HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8080")), access_log=False)
