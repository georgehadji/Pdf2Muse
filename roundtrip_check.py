"""Compare recognised MusicXML against the ground truth that generated the PDF."""
import sys, zipfile, xml.etree.ElementTree as ET
from pathlib import Path


def load(path):
    path = Path(path)
    if path.suffix == ".mxl":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist()
                        if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
            return ET.fromstring(z.read(name))
    return ET.parse(path).getroot()


def notes(root):
    out = []
    for measure in root.iter("measure"):
        for note in measure.findall("note"):
            if note.find("rest") is not None:
                out.append("rest")
                continue
            pitch = note.find("pitch")
            if pitch is None:
                continue
            step = pitch.findtext("step", "?")
            octave = pitch.findtext("octave", "?")
            alter = pitch.findtext("alter")
            acc = {"1": "#", "-1": "b"}.get(alter, "") if alter else ""
            out.append(f"{step}{acc}{octave}")
    return out


def meta(root):
    attrs = root.find(".//attributes")
    if attrs is None:
        return "no attributes"
    clef = attrs.find("clef")
    time = attrs.find("time")
    return (
        f"clef={clef.findtext('sign', '?') if clef is not None else '?'}"
        f"{clef.findtext('line', '') if clef is not None else ''} "
        f"key={attrs.findtext('key/fifths', '?')} "
        f"time={time.findtext('beats', '?') if time is not None else '?'}/"
        f"{time.findtext('beat-type', '?') if time is not None else '?'}"
    )


truth, got = load(sys.argv[1]), load(sys.argv[2])
t_notes, g_notes = notes(truth), notes(got)

print(f"truth  {meta(truth)}\n       {len(t_notes)} notes: {' '.join(t_notes)}")
print(f"got    {meta(got)}\n       {len(g_notes)} notes: {' '.join(g_notes)}")

hits = sum(1 for a, b in zip(t_notes, g_notes) if a == b)
total = max(len(t_notes), len(g_notes))
print(f"\npitch match: {hits}/{total}", end="  ")
print("EXACT" if t_notes == g_notes else "MISMATCH")
if t_notes != g_notes:
    for i in range(total):
        a = t_notes[i] if i < len(t_notes) else "-"
        b = g_notes[i] if i < len(g_notes) else "-"
        if a != b:
            print(f"  [{i}] expected {a}, got {b}")
