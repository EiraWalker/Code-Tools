/*
 * Single-process read-only host for codebase-memory-mcp v0.11.0.
 * Uses the upstream embedded MCP server and unchanged query implementations.
 * It operates on an isolated graph snapshot, never the shared live cache.
 */
#include "cbm.h"
#include "mcp/mcp.h"
#include "foundation/log.h"
#include "foundation/mem.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int allowed_tool(const char *tool) {
    const char *const tools[] = {
        "list_projects", "get_graph_schema", "index_status", "get_architecture",
        "search_graph", "trace_path", "query_graph", "get_file_outline",
        "check_index_coverage"
    };
    for (size_t i = 0; i < sizeof(tools) / sizeof(tools[0]); i++) {
        if (strcmp(tools[i], tool) == 0) return 1;
    }
    return 0;
}

static char *read_arguments(const char *path) {
    FILE *input = fopen(path, "rb");
    if (!input) return NULL;
    size_t cap = 1024 * 1024;
    char *args = malloc(cap + 1);
    if (!args) { fclose(input); return NULL; }
    size_t size = fread(args, 1, cap, input);
    int valid = !ferror(input) && fgetc(input) == EOF;
    fclose(input);
    if (!valid) { free(args); return NULL; }
    args[size] = '\0';
    return args;
}

int main(int argc, char **argv) {
    cbm_alloc_init();
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("codebase-memory-mcp 0.11.0 (embedded snapshot host 0.2.0)");
        return 0;
    }
    int call = argc == 4 && strcmp(argv[1], "--call") == 0;
    if ((!call && argc != 1) || (call && !allowed_tool(argv[2]))) {
        fputs("Use --call <read-tool> <arguments.json>, or no arguments for MCP stdio.\n", stderr);
        return 2;
    }
    if (!getenv("CBM_CACHE_DIR") || !getenv("CBM_CACHE_DIR")[0]) {
        fputs("An isolated CBM_CACHE_DIR containing the graph snapshot is required.\n", stderr);
        return 2;
    }
    cbm_log_init_for_process(true, false);
    cbm_mem_init(0.25);
    cbm_mcp_server_t *server = cbm_mcp_server_new(NULL);
    if (!server) { fputs("Embedded MCP initialization failed.\n", stderr); return 1; }
    cbm_mcp_server_set_background_tasks(server, false);
    cbm_mcp_server_set_tool_profile(server, CBM_MCP_TOOL_PROFILE_ANALYSIS);
    int status = 0;
    if (call) {
        char *args = read_arguments(argv[3]);
        char *result = args ? cbm_mcp_handle_tool(server, argv[2], args) : NULL;
        if (result) { puts(result); free(result); }
        else { fputs("Native tool call failed.\n", stderr); status = 1; }
        free(args);
    } else {
        status = cbm_mcp_server_run(server, stdin, stdout) < 0 ? 1 : 0;
    }
    cbm_mcp_server_free(server);
    return status;
}
