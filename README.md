# pdf2muse

Convert PDF sheet music into MuseScore files (`.mscz` / `.mscx`).

```
PDF  ->  Audiveris (OMR)  ->  MusicXML  ->  MuseScore CLI  ->  .mscz / .mscx
```

MusicXML is used as the interchange format deliberately. MuseScore imports it
natively, so pdf2muse never has to generate MuseScore's internal `.mscx` schema
itself — that would mean reimplementing MuseScore's MusicXML importer and
re-doing it every time the format version changes.

## Requirements

pdf2muse itself has **no Python dependencies** (standard library only), but it
drives two external programs:

| Tool | Why | Install |
|------|-----|---------|
| [Audiveris](https://github.com/Audiveris/audiveris/releases) 5.5+ | Optical Music Recognition | Installer bundles its own Java runtime — a separate JDK is not needed |
| [MuseScore](https://musescore.org/download) 3 or 4 | MusicXML → `.mscz`/`.mscx` | Standard installer |

Both are found automatically on `PATH` and in the usual install directories.
Override either explicitly if needed:

```bash
export PDF2MUSE_AUDIVERIS="C:/Program Files/Audiveris/Audiveris.exe"
export PDF2MUSE_MUSESCORE="C:/Program Files/MuseScore 4/bin/MuseScore4.exe"
```

## Install

```bash
pip install -e .
```

Or just run the single module directly: `python pdf2muse.py ...`

## Usage

Convert one score:

```bash
pdf2muse score.pdf
```

Pick the output path explicitly:

```bash
pdf2muse score.pdf -o "My Song.mscz"
```

Batch a folder into one output directory, as uncompressed `.mscx`:

```bash
pdf2muse scores/*.pdf --outdir out --format .mscx
```

Keep the intermediate MusicXML for inspection or manual repair:

```bash
pdf2muse score.pdf --keep-xml
```

Raise the per-step timeout for long or dense scores (default 900s):

```bash
pdf2muse symphony.pdf --timeout 3600
```

### Options

| Flag | Meaning |
|------|---------|
| `-o`, `--output` | Output file path (single input only) |
| `-d`, `--outdir` | Output directory (default: alongside each input) |
| `-f`, `--format` | `.mscz` (default) or `.mscx` |
| `--keep-xml` | Also keep the intermediate MusicXML |
| `--timeout` | Per-step timeout in seconds (default 900) |

Multi-movement scores produce one file per movement, suffixed `-1`, `-2`, ...

Exit code is `0` on success, `1` if any input failed, `2` if a required
external tool is missing.

## Accuracy expectations

OMR is not lossless. Audiveris is strong on clean, engraved PDFs and degrades on
low-resolution scans, handwriting, and dense orchestral textures. Treat the
output as a first draft to proofread in MuseScore, not a finished edition. Use
`--keep-xml` when you want to see what the recogniser actually produced.

## Tests

```bash
python test_pdf2muse.py
```

Runs without Audiveris or MuseScore installed — it covers the pure logic
(tool discovery, output naming, argument validation).
