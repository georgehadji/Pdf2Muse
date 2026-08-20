#!/usr/bin/env python3
"""Self-check for pdf2muse. Runs without Audiveris or MuseScore installed.

    python test_pdf2muse.py
"""

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import merge_lyrics as m
import pdf2muse as p


def test_target_for():
    base = Path("/out/song.mscz")
    # A single-movement book keeps the plain name.
    assert p.target_for(base, 0, 1) == base
    # Multi-movement books get 1-based suffixes, extension preserved.
    assert p.target_for(base, 0, 3) == Path("/out/song-1.mscz")
    assert p.target_for(base, 2, 3) == Path("/out/song-3.mscz")
    assert p.target_for(Path("/out/a.mscx"), 1, 2) == Path("/out/a-2.mscx")


def test_collect_scores():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "book").mkdir()
        for name in ("book/mvt2.mxl", "book/mvt1.mxl", "top.musicxml", "notes.txt"):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text("x")

        found = p.collect_scores(root)
        names = [f.name for f in found]
        # Non-score files are ignored.
        assert "notes.txt" not in names, names
        assert set(names) == {"mvt1.mxl", "mvt2.mxl", "top.musicxml"}, names
        # Movements within a folder come out in stable, sorted order.
        assert names.index("mvt1.mxl") < names.index("mvt2.mxl"), names

        # Empty dir yields nothing rather than raising.
        assert p.collect_scores(root / "book" / "nope") == []


def test_find_tool_override():
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as handle:
        real = Path(handle.name)
    try:
        os.environ["PDF2MUSE_TESTTOOL"] = str(real)
        assert p.find_tool("PDF2MUSE_TESTTOOL", (), (), "Tool", "hint") == real

        # A bogus override must fail loudly, not silently fall back to PATH.
        os.environ["PDF2MUSE_TESTTOOL"] = str(real) + "-missing"
        try:
            p.find_tool("PDF2MUSE_TESTTOOL", (), (), "Tool", "hint")
            raise AssertionError("expected ConversionError for bad override")
        except p.ConversionError as exc:
            assert "no file exists" in str(exc), exc
    finally:
        os.environ.pop("PDF2MUSE_TESTTOOL", None)
        real.unlink(missing_ok=True)


def test_store_app_dirs():
    # Never raises, whatever the platform or registry state.
    assert isinstance(p.store_app_dirs("definitely-no-such-package-xyz"), tuple)
    assert p.store_app_dirs("definitely-no-such-package-xyz") == ()

    if os.name == "nt":
        # WindowsApps cannot be listed without elevation, so any result must
        # have come from the registry rather than a directory scan.
        for found in p.store_app_dirs("MuseScore"):
            assert "WindowsApps" in found and found.endswith("bin"), found


def test_musescore_dirs_prefer_user_install_over_bundled():
    # A score written by a newer MuseScore will not open in an older one, so
    # the bundled fallback must be searched last.
    bundled = [i for i, d in enumerate(p.MUSESCORE_DIRS) if "pdf2muse-tools" in d]
    assert bundled, "bundled fallback missing from search path"
    store = [i for i, d in enumerate(p.MUSESCORE_DIRS) if "WindowsApps" in d]
    for index in store:
        assert index < bundled[0], "store install must be searched before bundled"
    for index, directory in enumerate(p.MUSESCORE_DIRS):
        if "Program Files\\MuseScore" in directory:
            assert index < bundled[0], "real install must be searched before bundled"


def test_find_tool_missing():
    os.environ.pop("PDF2MUSE_ABSENT", None)
    try:
        p.find_tool("PDF2MUSE_ABSENT", ("no-such-binary-xyz",), (), "Widget", "Get it.")
        raise AssertionError("expected ConversionError")
    except p.ConversionError as exc:
        # The message must tell the user how to fix it.
        assert "Widget" in str(exc) and "Get it." in str(exc), exc


def test_resolve_output():
    # Default lands in Outputs/, NOT beside the input.
    args = argparse.Namespace(output=None, outdir=None, format=".mscz")
    assert p.resolve_output(Path("/in/song.pdf"), args) == Path("Outputs/song.mscz")

    args = argparse.Namespace(output=None, outdir=Path("/out"), format=".mscx")
    assert p.resolve_output(Path("/in/song.pdf"), args) == Path("/out/song.mscx")

    args = argparse.Namespace(output=Path("/x/y.mscz"), outdir=None, format=".mscz")
    assert p.resolve_output(Path("/in/song.pdf"), args) == Path("/x/y.mscz")


def test_cli_rejects_bad_usage():
    for argv in (
        ["a.pdf", "b.pdf", "-o", "out.mscz"],   # -o with several inputs
        ["a.pdf", "-o", "out.pdf"],             # not a MuseScore extension
        ["a.pdf", "-o", "out"],                 # no extension at all
    ):
        try:
            p.main(argv)
            raise AssertionError(f"expected rejection for {argv}")
        except SystemExit as exc:
            assert exc.code == 2, (argv, exc.code)


def test_run_decodes_utf8():
    """Regression: locale decoding lost tool output on non-UTF-8 systems.

    With text=True and no explicit encoding, Python decodes subprocess output
    using the system locale (cp1253 on a Greek Windows install). Non-ASCII bytes
    then raised UnicodeDecodeError inside subprocess's reader thread, where it
    did not propagate -- run() returned "successfully" with the output gone.
    """
    import sys as _sys

    greek = "Χριστέ"  # Χριστέ
    proc = p._run(
        [_sys.executable, "-c", f"print({greek!r})"], 30, "python",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert greek in proc.stdout, repr(proc.stdout)


def test_run_survives_undecodable_bytes():
    """Raw invalid bytes must not crash the pipeline; errors='replace' handles it."""
    import sys as _sys

    proc = p._run(
        [_sys.executable, "-c",
         "import sys; sys.stdout.buffer.write(b'ok\\x81\\xfe done')"],
        30, "python",
    )
    assert "ok" in proc.stdout and "done" in proc.stdout, repr(proc.stdout)


def _stub_tools():
    """Make find_tool succeed without depending on installed binaries."""
    os.environ["PDF2MUSE_AUDIVERIS"] = sys.executable
    os.environ["PDF2MUSE_MUSESCORE"] = sys.executable


def test_batch_survives_oserror_in_one_input():
    """D1: an OSError on one input must not abandon the remaining inputs.

    mkdir/copy2 raise OSError for unwritable or invalid output paths. Letting
    it escape discarded every later input after minutes of OMR each.
    """
    _stub_tools()
    with tempfile.TemporaryDirectory() as tmp:
        first, second = Path(tmp) / "a.pdf", Path(tmp) / "b.pdf"
        first.write_bytes(b"%PDF-1.4\n")
        second.write_bytes(b"%PDF-1.4\n")

        seen = []
        original = p.convert_pdf

        def fake(pdf, *args, **kwargs):
            seen.append(Path(pdf).name)
            if Path(pdf).name == "a.pdf":
                raise OSError(28, "No space left on device")
            return [Path("ok.mscz")]

        p.convert_pdf = fake
        try:
            code = p.main([str(first), str(second), "--outdir", tmp])
        finally:
            p.convert_pdf = original

        assert seen == ["a.pdf", "b.pdf"], f"batch stopped early: {seen}"
        assert code == 1, f"expected failure exit code, got {code}"


def test_output_extension_is_case_insensitive():
    """D2: Windows/macOS filesystems are case-insensitive, so .MSCZ is valid."""
    _stub_tools()
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        original = p.convert_pdf
        p.convert_pdf = lambda *a, **k: []
        try:
            for ext in (".mscz", ".MSCZ", ".Mscz", ".MSCX"):
                code = p.main([str(pdf), "-o", str(Path(tmp) / f"out{ext}")])
                assert code == 0, f"{ext} rejected (exit {code})"

            # Boundary: genuinely wrong extensions must STILL be rejected.
            for bad in ("out.pdf", "out.PDF", "out"):
                try:
                    p.main([str(pdf), "-o", str(Path(tmp) / bad)])
                    raise AssertionError(f"{bad} should be rejected")
                except SystemExit as exc:
                    assert exc.code == 2, (bad, exc.code)
        finally:
            p.convert_pdf = original


def test_convert_pdf_rejects_missing_input():
    try:
        p.convert_pdf(Path("nope-does-not-exist.pdf"), Path("o.mscz"), "a", "m", 5)
        raise AssertionError("expected ConversionError")
    except p.ConversionError as exc:
        assert "not found" in str(exc), exc


def test_colliding_output_paths_rejected():
    """D1: two inputs sharing a stem land on one path; the second erased the first.

    Both were still reported as written and the exit code stayed 0, so the loss
    was silent -- after minutes of OMR each.
    """
    _stub_tools()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for sub in ("a", "b"):
            (root / sub).mkdir()
            (root / sub / "score.pdf").write_bytes(b"%PDF-1.4\n")

        try:
            p.main([str(root / "a" / "score.pdf"), str(root / "b" / "score.pdf"),
                    "-d", str(root / "out")])
            raise AssertionError("expected rejection for colliding output paths")
        except SystemExit as exc:
            assert exc.code == 2, exc.code

        # Boundary: distinct stems must still be accepted.
        (root / "a" / "other.pdf").write_bytes(b"%PDF-1.4\n")
        original = p.convert_pdf
        p.convert_pdf = lambda *a, **k: []
        try:
            code = p.main([str(root / "a" / "score.pdf"), str(root / "a" / "other.pdf"),
                           "-d", str(root / "out")])
            assert code == 0, code
        finally:
            p.convert_pdf = original


def test_failed_conversion_leaves_no_partial_output():
    """D2: a killed MuseScore left a truncated file that looked like success."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "song.mscz"
        original = p._run

        def fake(cmd, timeout, label, env=None):
            out.write_bytes(b"PK\x03\x04truncated")   # MuseScore got partway
            raise p.ConversionError("MuseScore timed out after 900s.")

        p._run = fake
        try:
            try:
                p.to_musescore("mscore", Path(tmp) / "s.mxl", out, 900)
                raise AssertionError("expected ConversionError")
            except p.ConversionError:
                pass
            assert not out.exists(), "partial output survived the error"

            # Boundary: a file this run did NOT create must survive.
            keep = Path(tmp) / "keep.mscz"
            keep.write_bytes(b"pre-existing")

            def fake_keep(cmd, timeout, label, env=None):
                raise p.ConversionError("MuseScore failed (exit 1).")

            p._run = fake_keep
            try:
                p.to_musescore("mscore", Path(tmp) / "s.mxl", keep, 900)
                raise AssertionError("expected ConversionError")
            except p.ConversionError:
                pass
            assert keep.exists(), "deleted a file this run did not create"
        finally:
            p._run = original


def test_package_version_sort_is_numeric():
    """D4: lexicographic order put 4.9 above 4.10, so the OLDER package won."""
    names = ["MuseScore.MuseScore_4.9.0.0_x64__abc",
             "MuseScore.MuseScore_4.10.0.0_x64__abc",
             "MuseScore.MuseScore_3.6.2.0_x64__abc"]
    ordered = sorted(names, key=p._pkg_version, reverse=True)
    assert ordered[0].startswith("MuseScore.MuseScore_4.10."), ordered
    assert ordered[-1].startswith("MuseScore.MuseScore_3."), ordered
    # Malformed names must not raise, and must sort last.
    assert p._pkg_version("nounderscore") == [-1]
    assert p._pkg_version("App_neutral_x64") == [-1]


SCORE_XML = (b'<?xml version="1.0"?><score-partwise><part><measure/>'
             b'</part></score-partwise>')


def test_merge_reads_uppercase_mxl():
    """D5: .MXL is a real filename on a case-insensitive filesystem."""
    with tempfile.TemporaryDirectory() as tmp:
        upper = Path(tmp) / "score.MXL"
        with zipfile.ZipFile(upper, "w") as archive:
            archive.writestr("score.xml", SCORE_XML)
        assert m.load(upper).tag == "score-partwise"


def test_merge_reports_empty_container():
    """D6: a container with no score raised bare StopIteration at the user."""
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.mxl"
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("META-INF/container.xml", "<container/>")
        try:
            m.load(empty)
            raise AssertionError("expected SystemExit")
        except SystemExit as exc:
            assert "no MusicXML" in str(exc), exc


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall checks passed")
