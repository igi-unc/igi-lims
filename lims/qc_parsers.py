"""Instrument QC export readers.

Each reader returns a list of Measurement(sample_name, measured_at, values, extra) where `values` maps
LIMS attribute keys to (value, unit). Qubit and NanoDrop go through allotropy (Benchling's open-source
converter, ASM output); TapeStation is read straight from the XML export because the ASM form buries
RIN/DIN in calculated-data documents and drops region tables; Countess 3 is a plain CSV whose columns
come from the vendor user guide (docs/countess3_csv_columns.md).
"""
import csv
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Measurement:
    sample_name: str
    measured_at: str
    values: dict            # key -> (value, unit)
    extra: dict = field(default_factory=dict)


INSTRUMENTS = {
    "qubit4": "Qubit 4 (CSV / XLSX export)",
    "nanodrop_one": "NanoDrop One (CSV export)",
    "tapestation": "Agilent TapeStation (XML export)",
    "countess3": "Countess 3 / 3 FL (CSV export)",
}


class ParseError(ValueError):
    pass


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ allotropy-backed

def _asm(path, vendor_name):
    try:
        from allotropy.parser_factory import Vendor
        from allotropy.to_allotrope import allotrope_from_file
    except ImportError:
        raise ParseError("allotropy is not installed (pip install allotropy; needs Python 3.10+)")
    try:
        return allotrope_from_file(path, getattr(Vendor, vendor_name))
    except Exception as e:
        raise ParseError(f"allotropy could not read this file as {vendor_name}: {e}")


def parse_qubit4(path):
    asm = _asm(path, "THERMO_FISHER_QUBIT4")
    out = []
    for doc in asm["spectrophotometry aggregate document"]["spectrophotometry document"]:
        mad = doc["measurement aggregate document"]
        for md in mad["measurement document"]:
            sd = md.get("sample document", {})
            custom = sd.get("custom information document", {})
            conc = custom.get("original sample concentration") or {}
            values = {}
            if conc.get("value") is not None:
                values["concentration_ng_ul"] = (conc["value"], conc.get("unit"))
            values["concentration_method"] = ("Qubit", None)
            out.append(Measurement(sd.get("sample identifier", ""), mad.get("measurement time", ""), values,
                                   {"assay": mad.get("experiment type"), "tube_conc": custom.get("qubit tube concentration")}))
    return out


def parse_nanodrop_one(path):
    asm = _asm(path, "THERMO_FISHER_NANODROP_ONE")
    agg = asm["spectrophotometry aggregate document"]
    # calculated ratios reference measurement identifiers
    ratios = {}
    for c in agg.get("calculated data aggregate document", {}).get("calculated data document", []):
        name = c.get("calculated data name", "")
        for src in c.get("data source aggregate document", {}).get("data source document", []):
            ratios.setdefault(src["data source identifier"], {})[name] = c["calculated result"]["value"]
    out = []
    for doc in agg["spectrophotometry document"]:
        mad = doc["measurement aggregate document"]
        first = mad["measurement document"][0]
        sd = first.get("sample document", {})
        values = {"concentration_method": ("NanoDrop", None)}
        pd = first.get("processed data aggregate document", {}).get("processed data document", [{}])[0]
        if pd.get("mass concentration"):
            values["concentration_ng_ul"] = (pd["mass concentration"]["value"], pd["mass concentration"]["unit"])
        r = {}
        for md in mad["measurement document"]:
            r.update(ratios.get(md["measurement identifier"], {}))
        if "A260/A280" in r:
            values["a260_280"] = (r["A260/A280"], None)
        if "A260/A230" in r:
            values["a260_230"] = (r["A260/A230"], None)
        out.append(Measurement(sd.get("sample identifier", ""), mad.get("measurement time", ""), values))
    return out


# ------------------------------------------------------------------ TapeStation XML

def parse_tapestation(path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ParseError(f"not a TapeStation XML export: {e}")
    assay = (root.findtext("FileInformation/Assay") or root.findtext("Assay") or "").strip()
    run_date = (root.findtext("FileInformation/RunEndDate") or "").strip()
    out = []
    for s in root.findall(".//Samples/Sample"):
        if (s.findtext("Observations") or "").strip() == "Ladder":
            continue
        name = (s.findtext("Comment") or "").strip()
        well = (s.findtext("WellNumber") or "").strip()
        values = {}
        conc = _num(s.findtext("Concentration"))
        if conc is not None:
            values["concentration_ng_ul"] = (conc, "ng/µL")
            values["concentration_method"] = ("TapeStation", None)
        rna, dna = s.find("RNA"), s.find("DNA")
        if rna is not None:
            rin = _num(rna.findtext("RINe")) or _num(rna.findtext("RIN"))
            if rin is not None:
                values["rin"] = (rin, None)
            dv = _num(rna.findtext("DV200"))
            if dv is not None:
                values["dv200"] = (dv, "%")
        if dna is not None:
            din = _num(dna.findtext("DIN"))
            if din is not None:
                values["din"] = (din, None)
        regions = []
        for r in s.findall("Regions/Region"):
            regions.append({g.tag: (g.text or "").strip() for g in r})
        if regions:
            first = regions[0]
            if _num(first.get("AverageSize")) is not None:
                values["mean_fragment_bp"] = (_num(first["AverageSize"]), "bp")
            if _num(first.get("Molarity")) is not None:
                values["concentration_nm"] = (_num(first["Molarity"]) / 1000.0, "nM")   # TapeStation reports pmol/L
            if assay.lower().startswith("cfdna") and _num(first.get("PercentOfTotal")) is not None:
                values["cfdna_peak_bp"] = (_num(first["AverageSize"]), "bp")
        out.append(Measurement(name or well, run_date, values,
                               {"well": well, "assay": assay, "observations": (s.findtext("Observations") or "").strip(),
                                "alert": (s.findtext("Alert") or "").strip(), "regions": regions}))
    if not out:
        raise ParseError("no sample lanes found in this TapeStation file")
    return out


# ------------------------------------------------------------------ Countess 3 CSV

COUNTESS_COLUMNS = {
    "Total concentration": ("concentration_cells_ml", "cells/mL"),
    "Live concentration": ("live_concentration_cells_ml", "cells/mL"),
    "Dead concentration": ("dead_concentration_cells_ml", "cells/mL"),
    "Viability (%)": ("viability_pct", "%"),
    "Total cells counted": ("cells_counted", None),
    "Live average size (µm)": ("live_avg_size_um", "µm"),
    "Dead average size (µm)": ("dead_avg_size_um", "µm"),
    "Aggregation(%)": ("aggregation_pct", "%"),
}


def parse_countess3(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        text = f.read()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "Sample name" not in rows[0] or "Viability (%)" not in rows[0]:
        raise ParseError("not a Countess 3 CSV export (expected 'Sample name' and 'Viability (%)' columns)")
    out = []
    for r in rows:
        values = {"count_method": ("Countess", None)}
        for col, (key, unit) in COUNTESS_COLUMNS.items():
            v = _num(r.get(col))
            if v is not None:
                values[key] = (v, unit)
        out.append(Measurement((r.get("Sample name") or "").strip(), (r.get("Date & Time") or "").strip(), values,
                               {"count_id": r.get("Count ID"), "count_mode": r.get("Count mode"),
                                "trypan_blue_corrected": r.get("Trypan blue corrected"),
                                "pre_dilution_corrected": r.get("Pre-Dilution corrected"),
                                "software": r.get("Software revision")}))
    return out


READERS = {"qubit4": parse_qubit4, "nanodrop_one": parse_nanodrop_one, "tapestation": parse_tapestation, "countess3": parse_countess3}


def detect(path, filename=""):
    """Best-effort instrument detection from file name and the first bytes."""
    low = filename.lower()
    if low.endswith(".xml"):
        return "tapestation"
    if low.endswith(".xlsx"):
        return "qubit4"
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            head = f.read(2000)
    except OSError:
        return None
    if head.lstrip().startswith("<?xml") or "<File>" in head:
        return "tapestation"
    if "Qubit" in head and "Original sample conc" in head:
        return "qubit4"
    if "Sample name" in head and "Viability (%)" in head:
        return "countess3"
    if "A260/A280" in head and "Sample Name" in head:
        return "nanodrop_one"
    return None


def parse(path, instrument=None, filename=""):
    inst = instrument or detect(path, filename)
    if inst not in READERS:
        raise ParseError("Could not recognise the instrument format; choose it explicitly")
    return inst, READERS[inst](path)
