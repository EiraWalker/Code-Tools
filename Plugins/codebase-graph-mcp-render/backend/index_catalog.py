"""Private index configuration; never accept source URLs from query clients."""
import hashlib
import json
import os
from pathlib import Path
import re

FIELDS = {"project": "CBM_PROJECT", "repository": "CBM_SOURCE_REPOSITORY",
          "path": "CBM_GRAPH_PATH", "sha256": "CBM_GRAPH_SHA256",
          "blob_sha": "CBM_GRAPH_BLOB_SHA"}
PUBLISHER = {"repository": "CBM_SYNC_REPOSITORY", "repository_id": "CBM_SYNC_REPOSITORY_ID",
             "owner_id": "CBM_SYNC_OWNER_ID", "ref": "CBM_SYNC_REF", "workflow": "CBM_SYNC_WORKFLOW"}


def validate_config(config):
    project = config["CBM_PROJECT"]
    if not isinstance(project, str) or not project or len(project.encode()) > 180 or project in {".", ".."} or any(c in project for c in "/\\\0\r\n"):
        raise ValueError("Project must be one original database filename stem")
    for key, pattern in (("CBM_GRAPH_SHA256", "[a-f0-9]{64}"), ("CBM_GRAPH_BLOB_SHA", "[a-f0-9]{40}")):
        if not isinstance(config[key], str) or not re.fullmatch(pattern, config[key]):
            raise ValueError("Invalid configured snapshot checksum")
    if not all(isinstance(config[k], str) and config[k] for k in ("CBM_SOURCE_REPOSITORY", "CBM_GRAPH_PATH")):
        raise ValueError("Index provenance is required")
    if int(config.get("CBM_GRAPH_MAX_BYTES", "268435456")) < 16:
        raise ValueError("Invalid snapshot size limit")
    if config.get("CBM_SYNC_REPOSITORY"):
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", config["CBM_SYNC_REPOSITORY"]) or not str(config.get("CBM_SYNC_REPOSITORY_ID", "")).isdigit():
            raise ValueError("Publisher repository and immutable repository ID are required")
        if config.get("CBM_SYNC_OWNER_ID") and not str(config["CBM_SYNC_OWNER_ID"]).isdigit():
            raise ValueError("Invalid publisher owner ID")


def load_indexes(environ=None):
    environ = os.environ if environ is None else environ
    raw = environ.get("CBM_INDEXES_JSON")
    if not raw:
        config = {k: v for k, v in environ.items() if k.startswith("CBM_")}
        validate_config(config)
        return {config["CBM_PROJECT"]: config}
    records = json.loads(raw)
    if not isinstance(records, list) or not 1 <= len(records) <= 32:
        raise ValueError("Configure between one and 32 indexes")
    root = Path(environ["CBM_CACHE_DIR"]).resolve()
    indexes = {}
    allowed = set(FIELDS) | {"url_env", "bearer_token_env", "max_bytes", "publisher"}
    for record in records:
        if not isinstance(record, dict) or set(record) - allowed:
            raise ValueError("Invalid index configuration fields")
        config = {env: record[field] for field, env in FIELDS.items()}
        project = config["CBM_PROJECT"]
        config["CBM_GRAPH_MAX_BYTES"] = str(record.get("max_bytes", 268435456))
        # References keep credentials separate from the catalog and public templates.
        for field, key in (("url_env", "CBM_GRAPH_URL"), ("bearer_token_env", "CBM_GRAPH_BEARER_TOKEN")):
            if field in record:
                name = record[field]
                if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                    raise ValueError("Invalid source environment reference")
                config[key] = environ[name]
        publisher = record.get("publisher", {})
        if not isinstance(publisher, dict) or set(publisher) - set(PUBLISHER):
            raise ValueError("Invalid publisher configuration fields")
        config.update({PUBLISHER[k]: str(v) for k, v in publisher.items()})
        validate_config(config)
        if project in indexes:
            raise ValueError("Duplicate original project name")
        # Every index owns its cache, generations, activation lock and run watermark.
        directory = hashlib.sha256(project.encode()).hexdigest()
        config["CBM_CACHE_DIR"] = str(root / "indexes" / directory)
        indexes[project] = config
    return indexes
