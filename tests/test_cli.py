import pytest

from redstring import cli, db


def test_wait_db_exits_nonzero_after_all_failed_pings(monkeypatch, capsys):
    attempts = 0

    class Connection:
        def list_graphs(self):
            raise ConnectionError("not ready")

    def connect():
        nonlocal attempts
        attempts += 1
        return Connection()

    monkeypatch.setattr(db, "connect", connect)

    with pytest.raises(SystemExit) as error:
        cli.main(["wait-db", "--tries", "3", "--delay", "0"])

    assert error.value.code == 1
    assert attempts == 3
    assert capsys.readouterr().err.splitlines() == [
        "Waiting for FalkorDB (1/3)",
        "Waiting for FalkorDB (2/3)",
        "Waiting for FalkorDB (3/3)",
    ]


def test_wait_db_exits_successfully_after_ping(monkeypatch, capsys):
    attempts = 0

    class Connection:
        def list_graphs(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("not ready")
            return []

    monkeypatch.setattr(db, "connect", Connection)

    assert cli.main(["wait-db", "--tries", "3", "--delay", "0"]) is None
    assert attempts == 2
    assert capsys.readouterr().err.splitlines() == ["Waiting for FalkorDB (1/3)"]
