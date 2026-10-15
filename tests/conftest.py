"""Boot a throwaway FalkorDB (redis-server + falkordb.so from the falkordblite wheel) for the tests."""
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from redstring import config, db


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session", autouse=True)
def falkordb():
    import redislite
    bindir = Path(redislite.__file__).parent / "bin"
    port, tmp = _free_port(), tempfile.mkdtemp()
    proc = subprocess.Popen([str(bindir / "redis-server"), "--port", str(port), "--dir", tmp, "--save", "",
                             "--loadmodule", str(bindir / "falkordb.so")], stdout=subprocess.DEVNULL)
    config.FALKORDB_HOST, config.FALKORDB_PORT = "127.0.0.1", port
    db.connect.cache_clear()
    for _ in range(50):
        try:
            db.connect().list_graphs()
            break
        except Exception:
            time.sleep(0.1)
    yield port
    proc.terminate()
    shutil.rmtree(tmp, ignore_errors=True)
