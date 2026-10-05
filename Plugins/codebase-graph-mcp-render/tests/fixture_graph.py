"""Synthetic native-format test fixtures only; never used to query a user's graph.

The reader always runs original queries through the upstream native engine.
This helper uses SQLite solely to create tiny, public, non-sensitive test inputs.
"""
import sqlite3


def make_graph(path, project='reader-demo', helper='helper'):
    connection = sqlite3.connect(path)
    connection.executescript("""
    CREATE TABLE projects(name TEXT PRIMARY KEY, indexed_at TEXT NOT NULL, root_path TEXT NOT NULL);
    CREATE TABLE nodes(id INTEGER PRIMARY KEY, project TEXT NOT NULL, label TEXT NOT NULL, name TEXT NOT NULL, qualified_name TEXT NOT NULL, file_path TEXT DEFAULT '', start_line INTEGER DEFAULT 0, end_line INTEGER DEFAULT 0, properties TEXT DEFAULT '{}');
    CREATE TABLE edges(id INTEGER PRIMARY KEY, project TEXT NOT NULL, source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, type TEXT NOT NULL, properties TEXT DEFAULT '{}');
    CREATE TABLE file_hashes(project TEXT, rel_path TEXT, sha256 TEXT, mtime_ns INTEGER, size INTEGER);
    CREATE TABLE project_summaries(project TEXT PRIMARY KEY, summary TEXT, source_hash TEXT, created_at TEXT, updated_at TEXT);
    """)
    connection.execute('INSERT INTO projects VALUES (?, ?, ?)', (project, '2026-01-01T00:00:00Z', '/synthetic-demo'))
    for id, label, name, qn, line in ((1, 'File', 'main.py', 'main.py', 1), (2, 'Function', 'entry', 'demo.entry', 1), (3, 'Function', helper, 'demo.' + helper, 5)):
        connection.execute('INSERT INTO nodes(id,project,label,name,qualified_name,file_path,start_line,end_line) VALUES (?,?,?,?,?,?,?,?)', (id, project, label, name, qn, 'main.py', line, line+2))
    connection.execute('INSERT INTO edges(id,project,source_id,target_id,type) VALUES (1,?,2,3,?)', (project, 'CALLS'))
    connection.commit(); connection.close()
