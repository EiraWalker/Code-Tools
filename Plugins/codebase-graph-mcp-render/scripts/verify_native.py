"""Integration test against a COPY of an authorized snapshot, never the original.

Configure CBM_BINARY, CBM_PROJECT, CBM_CACHE_DIR, CBM_GRAPH_SHA256,
CBM_GRAPH_BLOB_SHA, CBM_SOURCE_REPOSITORY and CBM_GRAPH_PATH through the environment.
The report intentionally excludes source paths, symbols, project identity and hashes.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def verify(url, token, project):
    async with httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(url, json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
        assert response.status_code == 401
        assert project not in response.text
    async with httpx.AsyncClient(trust_env=False, headers={'Authorization':'Bearer '+token}) as http, streamable_http_client(url,http_client=http) as (read,write,_):
        async with ClientSession(read,write) as client:
            initialized = await client.initialize()
            assert initialized.serverInfo.name == 'codebase-graph-reader'
            assert 'single MCP connection' in initialized.instructions
            assert 'qualified name' in initialized.instructions
            tools = (await client.list_tools()).tools
            assert all(t.description for t in tools)
            assert 'no separate Engine' in next(t.description for t in tools if t.name == 'list_projects')
            names = {t.name for t in tools}
            assert names == {'list_projects','get_architecture','search_graph','trace_path','query_graph','add_index'}
            projects = await client.call_tool('list_projects',{})
            assert not projects.isError and projects.structuredContent['projects'][0]['name'] == project
            architecture = await client.call_tool('get_architecture',{'project':project})
            assert not architecture.isError
            assert architecture.structuredContent['graph_snapshot']['sha256'] == os.environ['CBM_GRAPH_SHA256']
            search = await client.call_tool('search_graph',{'project':project,'name_pattern':'.','limit':3})
            assert not search.isError
            count = await client.call_tool('query_graph',{'project':project,'query':'MATCH (n) RETURN count(n) AS nodes'})
            assert not count.isError
            assert int(count.structuredContent['rows'][0][0]) == architecture.structuredContent['total_nodes']
            seed = await client.call_tool('query_graph',{'project':project,'query':'MATCH (f)-[:CALLS]->(g) RETURN f.qualified_name LIMIT 1'})
            assert not seed.isError
            trace_tested = bool(seed.structuredContent['rows'])
            if trace_tested:
                trace = await client.call_tool('trace_path',{'project':project,'function_name':seed.structuredContent['rows'][0][0],'direction':'outbound','depth':1,'limit':3})
                assert not trace.isError
            denied = await client.call_tool('index_repository',{'repo_path':'/unused'})
            assert denied.isError
            foreign = await client.call_tool('get_architecture',{'project':project+'-outside-scope'})
            assert foreign.isError
            invalid = await client.call_tool('query_graph',{'project':project,'query':'THIS IS NOT CYPHER'})
            assert invalid.isError
            return {'native_http_tools':sorted(names),'query_success':True,'trace_tested':trace_tested,
              'unauthenticated_status':401,'foreign_project_denied':True,'write_tool_denied':True,
              'native_error_preserved':True,'visible_provenance':True}

def main():
    project=os.environ['CBM_PROJECT']
    original=Path(os.environ['CBM_CACHE_DIR'])/(project+'.db')
    before=hashlib.sha256(original.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='graph-integration-') as tmp:
        cache=Path(tmp)/'cache'; cache.mkdir()
        copy=cache/original.name; shutil.copyfile(original,copy)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        token=secrets.token_urlsafe(48)
        env={**os.environ,'CBM_BINARY':str(Path(os.environ['CBM_BINARY']).resolve()),'CBM_CACHE_DIR':str(cache),
          'CBM_SERVICE_TOKEN':token,'CBM_PUBLIC_ORIGIN':origin,'CBM_BIND_HOST':'127.0.0.1','PORT':str(port)}
        script=Path(__file__).resolve().parents[1]/'backend/server.py'
        process=subprocess.Popen([sys.executable,str(script)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('Native test service exited; inspect local configuration')
                try:
                    if httpx.get(origin+'/health',timeout=1,trust_env=False).status_code==200: break
                except httpx.HTTPError: pass
                time.sleep(.1)
            else: raise RuntimeError('Native test service did not become ready')
            report=asyncio.run(verify(origin+'/mcp',token,project))
            assert hashlib.sha256(copy.read_bytes()).hexdigest()==before
            assert hashlib.sha256(original.read_bytes()).hexdigest()==before
            report['snapshot_unchanged']=True
            report['single_plugin_workflow']=True
            print(json.dumps(report))
        finally:
            process.terminate(); process.wait(timeout=5)

if __name__=='__main__': main()
