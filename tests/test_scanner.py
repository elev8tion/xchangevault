import sys
import tempfile
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scanner


def test_scan_project_basic(tmp_path):
    (tmp_path / "main.py").write_text("x=1")
    (tmp_path / "README.md").write_text("# hi")
    tree, stats, stack = scanner.scan_project(tmp_path)
    assert tree["type"] == "dir"
    assert stats["files"] == 2
    names = {c["name"] for c in tree["children"]}
    assert "main.py" in names
    assert "README.md" in names


def test_is_excluded():
    assert scanner.is_excluded("node_modules") is True
    assert scanner.is_excluded(".git") is True
    assert scanner.is_excluded("src") is False
    assert scanner.is_excluded("venv") is True


def test_flatten_files(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("")
    tree, _, _ = scanner.scan_project(tmp_path)
    files = scanner.flatten_files(tree)
    assert any("a.py" in f for f in files)
    assert any("b.py" in f for f in files)


def test_detect_stack_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
    stack = scanner.detect_stack(tmp_path)
    assert "python" in stack["detected"]


def test_detect_stack_node(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x"}')
    stack = scanner.detect_stack(tmp_path)
    assert "node" in stack["detected"]


def test_scan_imports_python(tmp_path):
    (tmp_path / "main.py").write_text("from .utils import foo\nfrom .models import Bar")
    result = scanner.scan_imports(tmp_path, ["main.py"])
    # utils.py and models.py not in selection -> should have warnings
    assert "main.py" in result
    assert len(result["main.py"]) > 0


def test_scan_imports_js(tmp_path):
    (tmp_path / "app.js").write_text("import foo from './utils'\nrequire('./helper')")
    result = scanner.scan_imports(tmp_path, ["app.js"])
    assert "app.js" in result


def test_categorize_file():
    assert scanner.categorize_file("app.py", "src/app.py") == "source"
    assert scanner.categorize_file("app.test.js", "src/app.test.js") == "test"
    assert scanner.categorize_file("README.md", "README.md") == "doc"
    assert scanner.categorize_file("config.yaml", "config.yaml") == "config"
    assert scanner.categorize_file("logo.png", "assets/logo.png") == "asset"
    assert scanner.categorize_file("bundle.js", "dist/bundle.js") == "build"
    assert scanner.categorize_file("spec.ts", "tests/spec.ts") == "test"


def test_walk_excludes_git(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (tmp_path / "main.py").write_text("x=1")
    tree, stats, _ = scanner.scan_project(tmp_path)
    names = {c["name"] for c in tree["children"]}
    assert ".git" not in names
    assert "main.py" in names


def test_file_category_in_tree(tmp_path):
    (tmp_path / "main.py").write_text("x=1")
    (tmp_path / "README.md").write_text("# hi")
    (tmp_path / "config.yaml").write_text("key: val")
    tree, _, _ = scanner.scan_project(tmp_path)
    by_name = {c["name"]: c for c in tree["children"]}
    assert by_name["main.py"]["category"] == "source"
    assert by_name["README.md"]["category"] == "doc"
    assert by_name["config.yaml"]["category"] == "config"
