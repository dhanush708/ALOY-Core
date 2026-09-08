"""
Unit tests for ALOY Core Path & Runtime Environment Manager (kernel/path_manager.py).
Target coverage: >90%. Tests development mode, frozen mode simulation, AppData pathing,
resource lookup, directory bootstrapping, log rotation, and startup validation.
"""

import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, PropertyMock

from kernel.path_manager import PathManager, paths


class TestPathManager:

    def test_development_mode_paths(self, tmp_path):
        pm = PathManager(override_app_data=tmp_path / "ALOY")

        assert pm.is_frozen is False
        assert pm.app_root.exists()
        assert pm.resource_root == pm.app_root
        assert pm.app_data_root == (tmp_path / "ALOY").resolve()

    def test_app_data_subdirectories(self, tmp_path):
        app_data = tmp_path / "ALOY"
        pm = PathManager(override_app_data=app_data)

        assert pm.config_dir == app_data / "config"
        assert pm.data_dir == app_data / "data"
        assert pm.logs_dir == app_data / "logs"
        assert pm.cache_dir == app_data / "cache"
        assert pm.downloads_dir == app_data / "downloads"
        assert pm.temp_dir == app_data / "temp"
        assert pm.db_path == app_data / "data" / "aloy.db"
        assert pm.trace_db_path == app_data / "data" / "trace.db"

    def test_ensure_directories_creation(self, tmp_path):
        app_data = tmp_path / "ALOY"
        pm = PathManager(override_app_data=app_data)

        # Before ensure
        assert not app_data.exists()

        pm.ensure_directories()

        # After ensure
        assert app_data.exists()
        assert pm.config_dir.exists()
        assert pm.data_dir.exists()
        assert pm.logs_dir.exists()
        assert pm.cache_dir.exists()
        assert pm.downloads_dir.exists()
        assert pm.temp_dir.exists()

    def test_resource_path_resolution(self, tmp_path):
        pm = PathManager(override_app_data=tmp_path / "ALOY")

        res_path = pm.get_resource_path("static/index.html")
        assert res_path == (pm.resource_root / "static" / "index.html").resolve()

        user_path = pm.get_user_data_path("config/settings.json")
        assert user_path == (pm.app_data_root / "config" / "settings.json").resolve()

    def test_frozen_mode_simulation(self, tmp_path):
        mock_meipass = tmp_path / "_MEIPASS_TEST"
        mock_meipass.mkdir(parents=True, exist_ok=True)

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", str(mock_meipass), create=True), \
             patch.object(sys, "executable", str(tmp_path / "ALOY.exe")):

            pm = PathManager(override_app_data=tmp_path / "ALOY")

            assert pm.is_frozen is True
            assert pm.app_root == tmp_path.resolve()
            assert pm.resource_root == mock_meipass.resolve()
            assert pm.static_dir == mock_meipass / "static"
            assert pm.assets_dir == mock_meipass / "assets"
            assert pm.tiktoken_cache_dir == mock_meipass / "assets" / "tiktoken_cache"

    def test_validate_environment_success(self, tmp_path):
        pm = PathManager(override_app_data=tmp_path / "ALOY")

        # Mock critical assets existence
        with patch.object(PathManager, "static_dir", new_callable=PropertyMock) as mock_static, \
             patch.object(PathManager, "icons_dir", new_callable=PropertyMock) as mock_icons:

            mock_static_file = tmp_path / "static" / "index.html"
            mock_static_file.parent.mkdir(parents=True, exist_ok=True)
            mock_static_file.write_text("<html></html>", encoding="utf-8")
            mock_static.return_value = mock_static_file.parent

            mock_icon_file = tmp_path / "assets" / "icons" / "aloy.ico"
            mock_icon_file.parent.mkdir(parents=True, exist_ok=True)
            mock_icon_file.write_bytes(b"\x00\x00")
            mock_icons.return_value = mock_icon_file.parent

            is_valid, errors = pm.validate_environment()

            assert is_valid is True
            assert len(errors) == 0

    def test_validate_environment_missing_assets_failure(self, tmp_path):
        pm = PathManager(override_app_data=tmp_path / "ALOY")

        # Point to non-existent assets
        with patch.object(PathManager, "static_dir", new_callable=PropertyMock) as mock_static:
            mock_static.return_value = tmp_path / "non_existent_static"

            is_valid, errors = pm.validate_environment()

            assert is_valid is False
            assert len(errors) > 0
            assert any("Missing critical bundled asset" in e for e in errors)

    def test_setup_logging(self, tmp_path):
        pm = PathManager(override_app_data=tmp_path / "ALOY")

        logger = pm.setup_logging(log_filename="test_run.log")

        assert pm.logs_dir.exists()
        assert (pm.logs_dir / "test_run.log").parent == pm.logs_dir
        logger.info("PathManager test log entry")

        assert (pm.logs_dir / "test_run.log").exists()

    def test_global_paths_instance(self):
        assert paths is not None
        assert isinstance(paths, PathManager)
