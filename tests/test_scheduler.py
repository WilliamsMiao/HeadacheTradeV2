from pathlib import Path

import pytest

from app.services import pipeline_lock as lock_module
from app.services.pipeline_lock import PipelineBusyError, pipeline_lock


def test_pipeline_lock_rejects_concurrent_process_style_access(tmp_path, monkeypatch):
    monkeypatch.setattr(lock_module, "LOCK_PATHS", (tmp_path / "pipeline.lock",))

    with pipeline_lock():
        with pytest.raises(PipelineBusyError):
            with pipeline_lock():
                pass


def test_systemd_timers_use_new_york_time_and_expected_schedule():
    deploy_dir = Path(__file__).parents[1] / "deploy"
    daily = (deploy_dir / "headachetrade-daily.timer").read_text()
    intraday = (deploy_dir / "headachetrade-60m.timer").read_text()
    market = (deploy_dir / "headachetrade-market-refresh.timer").read_text()

    assert "08:45:00 America/New_York" in daily
    assert "Persistent=true" in daily
    assert "10:35:00 America/New_York" in intraday
    assert "16:05:00 America/New_York" in intraday
    assert intraday.count("OnCalendar=") == 7
    assert "Persistent=false" in intraday
    assert "09:20:00 America/New_York" in market
    assert "Persistent=true" in market


def test_release_installs_and_enables_both_timers():
    release_script = (Path(__file__).parents[1] / "deploy" / "remote_release.sh").read_text()

    assert "headachetrade-daily.timer" in release_script
    assert "headachetrade-60m.timer" in release_script
    assert "headachetrade-market-refresh.timer" in release_script
    assert "systemctl enable --now headachetrade-daily.timer headachetrade-market-refresh.timer headachetrade-60m.timer" in release_script


def test_release_pauses_database_users_before_initializing_schema():
    release_script = (Path(__file__).parents[1] / "deploy" / "remote_release.sh").read_text()

    stop_tasks = release_script.index('systemctl stop "${background_units[@]}"')
    stop_web = release_script.index('systemctl stop "${SERVICE_NAME}"')
    init_db = release_script.index("uv run python -m app.cli init-db")

    assert stop_tasks < init_db
    assert stop_web < init_db
    assert "trap restore_existing_services EXIT" in release_script
    assert "services_paused=0" in release_script


def test_release_prunes_old_release_directories_before_extracting():
    release_script = (Path(__file__).parents[1] / "deploy" / "remote_release.sh").read_text()

    prune = release_script.index('find "${APP_ROOT}/releases"')
    extract = release_script.index('tar -xzf - -C "${RELEASE_DIR}"')

    assert prune < extract
    assert 'current_release="$(readlink -f "${CURRENT_LINK}" || true)"' in release_script
    assert 'RELEASES_TO_KEEP="${RELEASES_TO_KEEP:-3}"' in release_script
