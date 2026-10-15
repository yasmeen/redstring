"""FalkorDB connection and small helpers. One `agency` graph, one `client:<slug>` graph per prospect or client."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from falkordb import FalkorDB

from . import config


@lru_cache(maxsize=1)
def connect() -> FalkorDB:
    return FalkorDB(
        host=config.FALKORDB_HOST,
        port=config.FALKORDB_PORT,
        username=config.FALKORDB_USERNAME,
        password=config.FALKORDB_PASSWORD,
    )


def graph(name: str):
    return connect().select_graph(name)


def agency():
    return graph(config.AGENCY_GRAPH)


def client(slug: str):
    return graph(config.client_graph_name(slug))


def list_graphs() -> list[str]:
    return list(connect().list_graphs())


def client_slugs() -> list[str]:
    p = config.CLIENT_PREFIX
    return sorted(g[len(p):] for g in list_graphs() if g.startswith(p))


def _plain(v: Any) -> Any:
    """Turn FalkorDB Node/Edge objects into dicts so results are JSON-safe."""
    if hasattr(v, "properties") and hasattr(v, "labels"):
        return {"labels": list(v.labels), **v.properties}
    if hasattr(v, "properties") and hasattr(v, "relation"):
        return {"type": v.relation, **v.properties}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def rows(g, cypher: str, params: dict | None = None) -> list[dict]:
    res = g.query(cypher, params or {})
    header = [h[1] if isinstance(h, (list, tuple)) else h for h in (res.header or [])]
    return [dict(zip(header, (_plain(v) for v in r))) for r in res.result_set]


def run(g, cypher: str, params: dict | None = None) -> None:
    g.query(cypher, params or {})


def drop(name: str) -> None:
    if name in list_graphs():
        connect().select_graph(name).delete()
