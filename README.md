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

Verified end to end against **Audiveris 5.11.0** and **MuseScore Studio 4.7.4** on
Windows 11.

On Windows, prefer the **`windowsConsole`** Audiveris MSI over the plain
`windows` one. Both contain the same program, but only the console build writes
to stdout/stderr, which is what pdf2muse captures to report errors.

Both tools are found automatically on `PATH` and in the usual install
directories. Override either explicitly if needed:

```bash
export PDF2MUSE_AUDIVERIS="C:/Program Files/Audiveris/Audiveris.exe"
export PDF2MUSE_MUSESCORE="C:/Program Files/MuseScore 4/bin/MuseScore4.exe"
```

### Installing without admin rights

Both MSIs normally install to `Program Files`, which needs elevation. If you do
not have it, unpack them instead — `msiexec /a` performs an administrative
*extraction* and does not require admin:

```powershell
$root = "$env:LOCALAPPDATA\Programs\pdf2muse-tools"
msiexec /a Audiveris-5.11.0-windowsConsole-x86_64.msi /qn TARGETDIR="$root\audiveris"
msiexec /a MuseScore-Studio-4.7.4.260706075-x86_64.msi /qn TARGETDIR="$root\musescore"
```

pdf2muse searches that exact layout, so no environment variables are needed
afterwards. The extracted Audiveris tree keeps its bundled Java runtime and runs
as-is.

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

## Speed

Expect **minutes, not seconds**. A 4-measure single-staff score took ~5.7 min
end to end. Most of that is fixed cost — JVM start plus Audiveris pipeline
warm-up — so longer scores do not scale linearly, but budget accordingly and
raise `--timeout` for anything substantial.

## Accuracy expectations

OMR is not lossless. Audiveris is strong on clean, engraved PDFs and degrades on
low-resolution scans, handwriting, and dense orchestral textures. Treat the
output as a first draft to proofread in MuseScore, not a finished edition. Use
`--keep-xml` when you want to see what the recogniser actually produced.

A round-trip check — MusicXML → MuseScore → PDF → pdf2muse → MusicXML — gives a
concrete sense of the loss. On a 4-measure C-major scale:

- clef, time signature, and all note durations recovered correctly
- 11 of 12 pitches exact
- the final measure (a lone stemless whole note before the closing barline) was
  **dropped entirely** by Audiveris

That last point is characteristic rather than a one-off: isolated noteheads and
final measures are a known weak spot. Always proofread the last system.

## Tests

```bash
python test_pdf2muse.py
```

Runs without Audiveris or MuseScore installed — it covers the pure logic
(tool discovery, output naming, argument validation).

### Round-trip accuracy check

`fixtures/scale.musicxml` is checked-in ground truth. Render it to PDF, push it
back through the pipeline, and diff what survived — useful after upgrading
Audiveris, since OMR quality regressions are otherwise invisible:

```bash
MuseScore4 -o scale.pdf fixtures/scale.musicxml
python pdf2muse.py scale.pdf -o scale.mscz --keep-xml
python roundtrip_check.py fixtures/scale.musicxml scale.mxl
```

It prints clef/key/time, the note sequence from each side, and a per-note diff
of anything that does not match.
