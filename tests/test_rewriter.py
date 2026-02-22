import sys
import tempfile
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import rewriter


def test_brand_map_case_variants():
    brand_map = [{"from": "OldBrand", "to": "NewBrand"}]
    data = b"oldbrand OLDBRAND Oldbrand OldBrand"
    result, _ = rewriter.transform_bytes(Path("test.txt"), data, brand_map, False)
    text = result.decode("utf-8")
    assert "newbrand" in text
    assert "NEWBRAND" in text
    assert "Newbrand" in text
    assert "NewBrand" in text
    assert "OldBrand" not in text


def test_scrub_secrets_patterns():
    cases = [
        b"AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
        b"AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        b"sk-aBcDeFgHiJkLmNoPqRsTuVwX",
        b"ghp_abcdefghijklmnopqrstu1234567890",
        b"xoxb-" + b"FAKEFAKEFAKEFAKE-FAKEFAKEFAKEFAKE",  # Slack pattern (fake, split to avoid scanner)
        b"SENTRY_DSN=https://abc123@sentry.io/project",
        b"DATABASE_URL=postgres://user:pass@host/db",
    ]
    for data in cases:
        result, _ = rewriter.transform_bytes(Path("test.txt"), data, [], True)
        assert b"REDACTED" in result, f"Expected REDACTED in result for: {data}"


def test_crlf_normalization():
    data = b"line1\r\nline2\r\nline3\r\n"
    result, crlf = rewriter.transform_bytes(Path("test.txt"), data, [], False, normalize_line_endings=True)
    assert b"\r\n" not in result
    assert crlf is True

    result2, crlf2 = rewriter.transform_bytes(Path("test.txt"), data, [], False, normalize_line_endings=False)
    assert b"\r\n" in result2
    assert crlf2 is False


def test_template_vars():
    data = b"Project: {{PROJECT_NAME}} on {{DATE}}"
    result, _ = rewriter.transform_bytes(Path("test.txt"), data, [], False, template_vars={"PROJECT_NAME": "MyApp", "DATE": "2026-01-01"})
    text = result.decode("utf-8")
    assert "MyApp" in text
    assert "2026-01-01" in text
    assert "{{" not in text


def test_entropy_detection():
    high_entropy = "aB3$xY9!zQ2@mN7#pK5^wR1&dF8*gH4"  # > 20 chars, high entropy, mixed
    data = f"MY_SECRET_TOKEN = '{high_entropy}'".encode()
    result, _ = rewriter.transform_bytes(Path("test.txt"), data, [], True)
    # The entropy scrubber should redact it
    text = result.decode("utf-8")
    assert "REDACTED" in text


def test_is_binary():
    assert rewriter.is_binary(Path("/dev/null")) is False
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(b"\x00\x01\x02binary data")
        tmp = Path(f.name)
    assert rewriter.is_binary(tmp) is True
    tmp.unlink()


def test_sanitize_name():
    assert rewriter.sanitize_name("my project!") == "my-project"
    assert rewriter.sanitize_name("  hello  ") == "hello"
    assert rewriter.sanitize_name("") == "new-project"
    assert "-" not in rewriter.sanitize_name("hello")[0:1]


def test_build_plan_basic(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('OldBrand')")
    dest = tmp_path / "out"
    dest.mkdir()

    plan = rewriter.build_plan(
        source_root=tmp_path,
        include_rel_paths=["src/main.py"],
        dest_base=dest,
        new_project_name="NewProject",
        old_brand="OldBrand",
        new_brand="NewBrand",
        scrub_secrets=False,
    )
    assert "actions" in plan
    assert len(plan["actions"]) == 1
    assert plan["new_project_name"] == "NewProject"
    assert "previews" in plan
    assert "normalize_line_endings" in plan
    assert "generate_changelog" in plan
    assert "template_vars" in plan
    assert "workers" in plan


def test_generate_changelog():
    plan = {
        "source_root": "/src",
        "dest_root": "/dst",
        "brand_map": [{"from": "Old", "to": "New"}],
        "scrub_secrets": True,
        "patterns": [],
    }
    result = {"copied": 10, "transformed": 5, "crlf_normalized": 2}
    cl = rewriter.generate_changelog(plan, result)
    assert "## [" in cl
    assert "/src" in cl
    assert "10" in cl
    assert "5" in cl


def test_parallel_apply(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(5):
        (src / f"file{i}.txt").write_text(f"OldBrand content {i}")
    dest = tmp_path / "out"
    dest.mkdir()

    plan = rewriter.build_plan(
        source_root=src,
        include_rel_paths=[f"file{i}.txt" for i in range(5)],
        dest_base=dest,
        new_project_name="proj",
        old_brand="OldBrand",
        new_brand="NewBrand",
        scrub_secrets=False,
        workers=2,
        generate_changelog=False,
    )
    result = rewriter.apply_plan(plan)
    assert result["ok"] is True
    assert result["copied"] == 5
    dest_proj = dest / "proj"
    for i in range(5):
        content = (dest_proj / f"file{i}.txt").read_text()
        assert "NewBrand" in content
        assert "OldBrand" not in content
