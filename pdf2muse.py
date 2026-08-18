#!/usr/bin/env python3
"""Convert PDF sheet music into MuseScore files.

Pipeline: PDF -> Audiveris (OMR) -> MusicXML -> MuseScore CLI -> .mscz/.mscx

Both Audiveris and MuseScore are external programs; this module only glues them
together. MusicXML is used as the interchange format on purpose: MuseScore
imports it natively, so we never have to synthesise MuseScore's internal .mscx
schema ourselves.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MUSESCORE_EXTS = (".mscz", ".mscx")
SCORE_PATTERNS = ("*.mxl", "*.musicxml", "*.xml")

# Converted scores land here unless -o/--outdir says otherwise. Relative, so it
# resolves against the working directory and is created on demand.
DEFAULT_OUTDIR = Path("Outputs")

# OMR is slow; a dense orchestral page can take minutes.
DEFAULT_TIMEOUT = 900

AUDIVERIS_NAMES = ("Audiveris", "audiveris")
AUDIVERIS_DIRS = (
    r"C:\Program Files\Audiveris",
    r"C:\Program Files (x86)\Audiveris",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Audiveris"),
    # Layout produced by extracting the MSI without admin rights (see README).
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\pdf2muse-tools\audiveris\Audiveris"),
    "/opt/audiveris/bin",
    "/usr/local/bin",
)
AUDIVERIS_HINT = (
    "Install it from https://github.com/Audiveris/audiveris/releases "
    "(the installer bundles its own Java runtime), or set PDF2MUSE_AUDIVERIS "
    "to the full path of the executable."
)

MUSESCORE_NAMES = ("MuseScore4", "MuseScore3", "mscore", "musescore")
MUSESCORE_DIRS = (
    r"C:\Program Files\MuseScore 4\bin",
    r"C:\Program Files\MuseScore 3\bin",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\MuseScore 4\bin"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\pdf2muse-tools\musescore\MuseScore 4\bin"),
    "/Applications/MuseScore 4.app/Contents/MacOS",
    "/usr/bin",
    "/usr/local/bin",
)
MUSESCORE_HINT = (
    "Install it from https://musescore.org/download, or set PDF2MUSE_MUSESCORE "
    "to the full path of the executable."
)


class ConversionError(Exception):
    """Anything that stops a PDF from becoming a MuseScore file."""


def find_tool(env_var, names, dirs, label, hint):
    """Locate an external executable: explicit override, then PATH, then usual dirs."""
    override = os.environ.get(env_var)
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise ConversionError(
            f"{env_var} is set to {override!r}, but no file exists there."
        )

    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)

    for directory in dirs:
        if not directory:
            continue
        for name in names:
            for suffix in ("", ".exe"):
                candidate = Path(directory) / (name + suffix)
                if candidate.is_file():
                    return candidate

    raise ConversionError(f"Could not find {label}. {hint}")


def _run(cmd, timeout, label, env=None):
    """Run a subprocess, turning failure into a ConversionError with useful output."""
    try:
        # Decode as UTF-8 explicitly. Defaulting to the system locale breaks on
        # non-ASCII tool output (e.g. cp1253 on a Greek Windows install), and the
        # failure lands in a subprocess reader thread where it does NOT propagate
        # -- subprocess.run returns "successfully" with the output lost.
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, env=env,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise ConversionError(f"Could not execute {label}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            f"{label} timed out after {timeout}s. Dense or many-page scores can "
            f"exceed this; raise it with --timeout."
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        tail = "\n".join(detail.splitlines()[-15:])
        raise ConversionError(f"{label} failed (exit {proc.returncode}).\n{tail}")
    return proc


def collect_scores(directory):
    """Return MusicXML files Audiveris wrote, sorted so movement order is stable."""
    found = set()
    for pattern in SCORE_PATTERNS:
        found.update(Path(directory).rglob(pattern))
    return sorted(found, key=lambda p: (str(p.parent), p.name))


def run_audiveris(exe, pdf, workdir, timeout, languages=None):
    """Transcribe a PDF, returning the MusicXML files produced."""
    # -export implies -transcribe. '--' guards filenames that start with '-'.
    #
    # Audiveris applies its own per-sheet step timeout (default ~120s) and aborts
    # the whole export when it trips -- which pre-empts our --timeout entirely.
    # OCR-heavy pages routinely exceed it. Derive it from our own budget so
    # --timeout is the single authoritative control.
    cmd = [
        str(exe), "-batch", "-export",
        "-constant", f"org.audiveris.omr.Main.sheetStepTimeOut={timeout}",
        "-output", str(workdir),
    ]
    if languages:
        # Audiveris OCRs with English only by default, which mangles other
        # scripts (Greek lyrics come back as Latin lookalikes) rather than
        # failing outright. Tesseract spec syntax, e.g. "eng+ell".
        cmd += ["-constant",
                f"org.audiveris.omr.text.Language.ocrDefaultLanguages={languages}"]
    cmd += ["--", str(pdf)]
    _run(cmd, timeout, "Audiveris")

    scores = collect_scores(workdir)
    if not scores:
        raise ConversionError(
            f"Audiveris produced no MusicXML for {pdf.name}. This usually means it "
            f"could not detect staves — check that the PDF really contains sheet "
            f"music and is not a low-resolution scan."
        )
    return scores


def musescore_env():
    """MuseScore needs an offscreen Qt platform when there is no display."""
    if os.name == "nt" or sys.platform == "darwin":
        return None
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


def to_musescore(exe, score, out_path, timeout):
    """Convert one MusicXML file to .mscz/.mscx. Extension decides the format."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Absolute paths: MuseScore 4 resolves relative ones unpredictably in batch use.
    cmd = [str(exe), "-o", str(out_path.resolve()), str(Path(score).resolve())]
    _run(cmd, timeout, "MuseScore", env=musescore_env())

    if not out_path.is_file():
        raise ConversionError(
            f"MuseScore reported success but did not write {out_path}."
        )
    return out_path


def target_for(base, index, total):
    """Name outputs for a book. Multi-movement scores get -1, -2, ... suffixes."""
    if total <= 1:
        return base
    return base.with_name(f"{base.stem}-{index + 1}{base.suffix}")


def convert_pdf(pdf, out_base, audiveris, musescore, timeout, keep_xml=False,
                languages=None):
    """Run the full pipeline for one PDF. Returns the MuseScore files written."""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise ConversionError(f"Input not found: {pdf}")

    written = []
    workdir = Path(tempfile.mkdtemp(prefix="pdf2muse-"))
    try:
        scores = run_audiveris(audiveris, pdf, workdir, timeout, languages)
        for index, score in enumerate(scores):
            target = target_for(out_base, index, len(scores))
            written.append(to_musescore(musescore, score, target, timeout))
            if keep_xml:
                kept = target.with_suffix(Path(score).suffix)
                shutil.copy2(score, kept)
                written.append(kept)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return written


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pdf2muse",
        description="Convert PDF sheet music to MuseScore files using Audiveris OMR.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="PDF file(s) to convert")
    parser.add_argument(
        "-o", "--output", type=Path,
        help="Output file path. Only valid with a single input.",
    )
    parser.add_argument(
        "-d", "--outdir", type=Path,
        help=f"Directory for outputs (default: {DEFAULT_OUTDIR}/, created if "
             f"missing).",
    )
    parser.add_argument(
        "-f", "--format", default=".mscz", choices=MUSESCORE_EXTS,
        help="Output format when -o is not given (default: .mscz)",
    )
    parser.add_argument(
        "-l", "--language",
        help="OCR language(s) for lyrics and chord symbols, Tesseract spec "
             "syntax (e.g. 'eng', 'eng+ell'). Default: Audiveris' own setting, "
             "normally English only.",
    )
    parser.add_argument(
        "--keep-xml", action="store_true",
        help="Also keep the intermediate MusicXML next to each output.",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"Per-step timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    return parser


def resolve_output(pdf, args):
    """Work out the output path for one input PDF."""
    if args.output:
        return args.output
    directory = args.outdir if args.outdir else DEFAULT_OUTDIR
    return Path(directory) / (pdf.stem + args.format)


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.output and len(args.inputs) > 1:
        build_parser().error("-o/--output takes a single input; use --outdir instead.")
    if args.output and args.output.suffix not in MUSESCORE_EXTS:
        build_parser().error(
            f"Output must end in one of {', '.join(MUSESCORE_EXTS)}; "
            f"got {args.output.suffix or 'no extension'!r}."
        )

    try:
        audiveris = find_tool(
            "PDF2MUSE_AUDIVERIS", AUDIVERIS_NAMES, AUDIVERIS_DIRS,
            "Audiveris", AUDIVERIS_HINT,
        )
        musescore = find_tool(
            "PDF2MUSE_MUSESCORE", MUSESCORE_NAMES, MUSESCORE_DIRS,
            "MuseScore", MUSESCORE_HINT,
        )
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failures = 0
    for pdf in args.inputs:
        print(f"==> {pdf}", flush=True)
        try:
            for path in convert_pdf(
                pdf, resolve_output(pdf, args), audiveris, musescore,
                args.timeout, args.keep_xml, args.language,
            ):
                print(f"    wrote {path}")
        except ConversionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
