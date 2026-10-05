---
name: read-codebase-graph
description: Query the owner's original codebase-memory-mcp snapshot through connected native tools for architecture, symbols, callers, dependencies and read-only Cypher. Use remote tools without mounting plugin executables.
---

# Read the connected graph

Discover actual installed tool names and schemas. Do not guess a namespace.
Use the connected engine's list_projects to discover the configured project.
Use get_architecture for counts and structure; search_graph for qualified names;
trace_path for callers and callees; query_graph for read-only structural Cypher.
Follow native paging and truncation fields. Treat isError as failure.

Retain structuredContent.graph_snapshot (or its appended text block) as snapshot
provenance. It includes source repository, graph path, blob SHA and SHA256.
Compare current source metadata when authorized access is available. Report a
newer source snapshot separately; the hosted snapshot does not refresh itself.

Graph snapshots do not provide live working-tree state or source snippets.
Node absence and zero callers do not prove dead code: runtime callbacks and
serialized references may not be captured.

If the engine is already installed, do not ask to install it again. Inspect
actual tool availability and connection errors. Installation does not imply
hosting is ready; hosting does not prove a connected tool call succeeds.
Never retrieve deployment secrets during ordinary graph queries, convert the
graph into text, reindex a backup, or create a duplicate wrapper for a canonical
Sites-generated plugin. This package supplies instructions, not an engine.
