"""Tests for local materialisation — Step 8."""

import os
import tempfile
import time

import pytest

from afsp.runtime.materialise import (
    materialise_path,
    get_cached_path,
    cache_path_for,
    warm_view,
)


@pytest.fixture
def tmp_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        volumes = os.path.join(tmpdir, "volumes")
        cache = os.path.join(tmpdir, "cache")
        os.makedirs(volumes)
        os.makedirs(cache)

        # Create some test files
        finance_dir = os.path.join(volumes, "workspace", "finance")
        os.makedirs(finance_dir)
        with open(os.path.join(finance_dir, "report.csv"), "w") as f:
            f.write("revenue,100\n")

        brand_dir = os.path.join(volumes, "assets", "brand")
        os.makedirs(brand_dir)
        with open(os.path.join(brand_dir, "logo.png"), "w") as f:
            f.write("fake-png-data")

        yield {
            "tmpdir": tmpdir,
            "volumes": volumes,
            "cache": cache,
            "backing_store": {"type": "local", "root": volumes},
        }


class TestMaterialisePath:
    def test_local_path_resolves(self, tmp_env):
        result = materialise_path(
            "workspace/finance", tmp_env["backing_store"], tmp_env["cache"]
        )
        assert result == os.path.realpath(os.path.join(tmp_env["volumes"], "workspace/finance"))

    def test_local_path_with_glob_stripped(self, tmp_env):
        result = materialise_path(
            "workspace/finance/**", tmp_env["backing_store"], tmp_env["cache"]
        )
        assert result == os.path.realpath(os.path.join(tmp_env["volumes"], "workspace/finance"))

    def test_s3_raises_not_implemented(self, tmp_env):
        with pytest.raises(NotImplementedError):
            materialise_path("path", {"type": "s3", "bucket": "test"}, tmp_env["cache"])

    def test_unknown_type_raises(self, tmp_env):
        with pytest.raises(ValueError):
            materialise_path("path", {"type": "nfs"}, tmp_env["cache"])


class TestCaching:
    def test_cache_miss_returns_none(self, tmp_env):
        result = get_cached_path("nonexistent/path", tmp_env["cache"])
        assert result is None

    def test_cache_hit_returns_path(self, tmp_env):
        source = os.path.join(tmp_env["volumes"], "workspace/finance/report.csv")
        cached = cache_path_for("workspace/finance/report.csv", source, tmp_env["cache"])

        result = get_cached_path("workspace/finance/report.csv", tmp_env["cache"])
        assert result == cached
        assert os.path.exists(result)

    def test_cache_dir(self, tmp_env):
        source = os.path.join(tmp_env["volumes"], "workspace/finance")
        cached = cache_path_for("workspace/finance", source, tmp_env["cache"])

        result = get_cached_path("workspace/finance", tmp_env["cache"])
        assert result is not None
        assert os.path.isdir(result)

    def test_stale_cache_returns_none(self, tmp_env):
        source = os.path.join(tmp_env["volumes"], "workspace/finance/report.csv")
        cached = cache_path_for("workspace/finance/report.csv", source, tmp_env["cache"])

        # Backdate the mtime
        old_time = time.time() - 400  # > 300s TTL
        os.utime(cached, (old_time, old_time))

        result = get_cached_path("workspace/finance/report.csv", tmp_env["cache"])
        assert result is None


class TestWarmView:
    def test_warm_materialises_all_paths(self, tmp_env):
        view_entries = [
            {"path": "workspace/finance/**", "ops": ["read", "write"]},
            {"path": "assets/brand/**", "ops": ["read"]},
        ]
        result = warm_view(view_entries, tmp_env["backing_store"], tmp_env["cache"])
        assert len(result) == 2

    def test_warm_skips_nonexistent(self, tmp_env):
        view_entries = [
            {"path": "workspace/finance/**", "ops": ["read"]},
            {"path": "nonexistent/path/**", "ops": ["read"]},
        ]
        result = warm_view(view_entries, tmp_env["backing_store"], tmp_env["cache"])
        assert len(result) == 1
