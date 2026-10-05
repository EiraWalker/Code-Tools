import assert from "node:assert/strict";
import worker from "../worker/index.js";

const env = {CBM_ENGINE_ORIGIN: "https://engine.example", CBM_SERVICE_TOKEN: "test-only-secret"};
const originalFetch = globalThis.fetch;
let forwards = [];
globalThis.fetch = async (url, options) => {
  forwards.push({url: String(url), options});
  return new Response(JSON.stringify({jsonrpc: "2.0", id: 1, result: {content: [{type: "text", text: "native result"}], structuredContent: {nodes: 2}, _meta: {graph_snapshot: {blob_sha: "test-snapshot"}}}}),
    {headers: {"content-type": "application/json"}});
};
function request(name, headers = {}) {
  return new Request("https://gateway.example/mcp", {method: "POST",
    headers: {"content-type": "application/json", ...headers},
    body: JSON.stringify({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name, arguments: {}}})});
}
try {
  assert.equal((await worker.fetch(request("query_graph"), env)).status, 403);
  assert.equal((await worker.fetch(request("query_graph", {"x-graph-reader-service-token": "wrong"}), env)).status, 403);
  assert.equal(forwards.length, 0);
  const denied = await worker.fetch(request("index_repository", {"oai-authenticated-user-id": "test-user"}), env);
  assert.equal((await denied.json()).result.isError, true);
  assert.equal(forwards.length, 0);
  const allowed = await worker.fetch(request("query_graph", {
    "oai-authenticated-user-id": "test-user", "authorization": "Bearer client-secret", "origin": "https://client.example"
  }), env);
  assert.equal(allowed.status, 200);
  const visible = (await allowed.json()).result;
  assert.equal(visible.structuredContent.nodes, 2);
  assert.equal(visible.structuredContent.graph_snapshot.blob_sha, "test-snapshot");
  assert.equal(visible.content[0].text, "native result");
  assert.equal(JSON.parse(visible.content[1].text).graph_snapshot.blob_sha, "test-snapshot");
  assert.equal(forwards[0].url, "https://engine.example/mcp");
  assert.equal(forwards[0].options.headers.get("authorization"), "Bearer test-only-secret");
  for (const key of ["origin", "oai-authenticated-user-id", "x-graph-reader-service-token"]) {
    assert.equal(forwards[0].options.headers.has(key), false);
  }
  assert.equal(forwards[0].options.redirect, "manual");
  assert.equal((await worker.fetch(request("search_graph", {"x-graph-reader-service-token": env.CBM_SERVICE_TOKEN}), env)).status, 200);
  const method = new Request("https://gateway.example/mcp", {method: "POST", body: JSON.stringify({jsonrpc: "2.0", id: 1, method: "execute"})});
  assert.equal((await (await worker.fetch(method, env)).json()).error.code, -32601);
  const malformed = new Request("https://gateway.example/mcp", {method: "POST", body: "[]"});
  assert.equal((await worker.fetch(malformed, env)).status, 400);

  for (const [method, nativeResult] of [
    ["initialize", {serverInfo: {name: "old-engine", version: "0.1.0"}, instructions: "old"}],
    ["tools/list", {tools: [...["list_projects", "get_architecture", "search_graph", "trace_path", "query_graph"], "index_repository"].map(name => ({name, description: "native", inputSchema: {type: "object"}}))}]
  ]) {
    globalThis.fetch = async () => new Response(JSON.stringify({jsonrpc: "2.0", id: 2, result: nativeResult}), {headers: {"content-type": "application/json"}});
    const discovered = await (await worker.fetch(new Request("https://gateway.example/mcp", {method: "POST", body: JSON.stringify({jsonrpc: "2.0", id: 2, method})}), env)).json();
    if (method === "initialize") {
      assert.equal(discovered.result.serverInfo.name, "codebase-graph-reader");
      assert.equal(discovered.result.serverInfo.version, "0.1.0");
      assert.match(discovered.result.instructions, /single MCP connection/);
      assert.match(discovered.result.instructions, /qualified name/);
    } else {
      assert.equal(discovered.result.tools.length, 5);
      assert.match(discovered.result.tools[0].description, /no separate Engine/);
      assert.match(discovered.result.tools[3].description, /qualified name/);
      assert.deepEqual(discovered.result.tools[0].inputSchema, {type: "object"});
    }
  }
  globalThis.fetch = async () => new Response(JSON.stringify({jsonrpc: "2.0", id: 1, result: {isError: true, content: [{type: "text", text: "native error"}]}}), {headers: {"content-type": "application/json"}});
  assert.equal((await (await worker.fetch(request("query_graph", {"oai-authenticated-user-id": "test-user"}), env)).json()).result.isError, true);

  globalThis.fetch = async () => new Response(null, {status: 302, headers: {location: "https://other.example"}});
  assert.equal((await worker.fetch(request("query_graph", {"oai-authenticated-user-id": "test-user"}), env)).status, 502);
  console.log("Single-plugin instructions, schemas, native errors, access and credential isolation verified");
} finally { globalThis.fetch = originalFetch; }
