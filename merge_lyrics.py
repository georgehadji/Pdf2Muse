"""Graft lyrics from a Greek-only OCR pass onto the eng+ell score.

The eng+ell pass keeps chord symbols; the ell pass reads lyrics better. Notes
come from OMR (not OCR), so both passes should agree on them - which is exactly
what makes the graft safe, and is verified before anything is copied.
"""

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

LY = "lyric"


def load(path):
    path = Path(path)
    if path.suffix != ".mxl":
        return ET.parse(path).getroot()
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist()
                    if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
        return ET.fromstring(z.read(name))


def pitches(root):
    """Note identity per note element, in document order."""
    out = []
    for note in root.iter("note"):
        pitch = note.find("pitch")
        if pitch is None:
            out.append("rest")
        else:
            out.append(f"{pitch.findtext('step')}{pitch.findtext('octave')}"
                       f"{pitch.findtext('alter') or ''}")
    return out


def lyric_text(note):
    return " ".join("".join(t.itertext()) for t in note.findall(f"{LY}/text"))


def main(target_path, source_path, out_path):
    target, source = load(target_path), load(source_path)
    t_notes = list(target.iter("note"))
    s_notes = list(source.iter("note"))

    # Alignment gate. Grafting onto misaligned notes would silently scramble
    # the words across the score, so refuse rather than guess.
    t_pitch, s_pitch = pitches(target), pitches(source)
    if len(t_notes) != len(s_notes):
        raise SystemExit(f"note count differs: {len(t_notes)} vs {len(s_notes)} - refusing")
    mismatch = [i for i, (a, b) in enumerate(zip(t_pitch, s_pitch)) if a != b]
    if mismatch:
        raise SystemExit(
            f"{len(mismatch)}/{len(t_pitch)} notes differ (first at index "
            f"{mismatch[0]}: {t_pitch[mismatch[0]]} vs {s_pitch[mismatch[0]]}) - refusing"
        )

    replaced = added = cleared = 0
    for t_note, s_note in zip(t_notes, s_notes):
        had = t_note.findall(LY)
        new = s_note.findall(LY)
        for old in had:
            t_note.remove(old)
        for element in new:
            t_note.append(element)
        if had and new:
            replaced += 1
        elif new:
            added += 1
        elif had:
            cleared += 1

    ET.ElementTree(target).write(out_path, encoding="UTF-8", xml_declaration=True)
    print(f"aligned    {len(t_notes)} notes, pitch sequences identical")
    print(f"lyrics     replaced={replaced} added={added} cleared={cleared}")
    print(f"chord syms {len(list(target.iter('harmony')))} (preserved from target)")
    print(f"wrote      {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
