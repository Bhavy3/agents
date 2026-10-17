from core.app import FridayApp
from core.config.settings import Settings


def test_app_uses_configured_memory_database_copy(tmp_path, monkeypatch):
    database_copy = tmp_path / "audit-memory.db"
    monkeypatch.setenv("FRIDAY_MEMORY_DB_PATH", str(database_copy))
    monkeypatch.setattr("core.app.configure_logging", lambda *args, **kwargs: None)

    app = FridayApp(settings=Settings(root_dir=tmp_path, audio_enabled=False))

    assert app.memory_worker.store.db_path == str(database_copy)
    assert database_copy.is_file()
