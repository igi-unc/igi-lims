"""Demonstration data on nomenclature v2.1.

`flask seed-demo` adds participant P101 / UNC316, which is the worked example from the nomenclature
document (section 5): a pleural fluid collection processed through tumour, immune and CD8 fractions,
pellets, HMW DNA, RNA, culture and a peptide eluate, plus the matched blood collection. Three smaller
participants in the other cohorts follow. Operators MF and KEN do the bench work, as in the document.

Everything goes through the same service functions as the web forms, so the derivation rules,
controlled vocabularies and audit log apply. The lists that ship empty (SOPs, freezers, lots, ...)
get a few plausible entries so the dropdowns are not all NA.
"""
import secrets

from flask import g

from . import audit
from . import samples as svc
from .auth import create_user

# (category, code, meaning) — added with INSERT OR IGNORE, so re-running is safe
LIST_ENTRIES = [
    ("sop", "SOP-001", "Pleural fluid receipt, spin and aliquoting"),
    ("sop", "SOP-002", "Mononuclear cell isolation and cryopreservation"),
    ("sop", "SOP-003", "Thaw and single-cell suspension for 10x"),
    ("sop", "SOP-004", "Tumor cell enrichment (EpCAM MACS)"),
    ("sop", "SOP-005", "Nucleic acid extraction"),
    ("sop", "SOP-006", "Library preparation and submission"),
    ("sop", "SOP-007", "HLA immunoprecipitation and peptide elution"),
    ("sop", "SOP-008", "Blood receipt, plasma and PBMC"),
    ("freezer", "FRZ-A", "-80 C freezer A, PIRL 3rd floor"),
    ("freezer", "FRZ-B", "-80 C freezer B, PIRL 3rd floor"),
    ("freezer", "LN2-1", "LN2 dewar 1"),
    ("rack", "R1", "Rack 1"), ("rack", "R2", "Rack 2"), ("rack", "R3", "Rack 3"), ("rack", "R4", "Rack 4"),
    ("box", "B01", "Box 01"), ("box", "B02", "Box 02"), ("box", "B03", "Box 03"), ("box", "B04", "Box 04"),
    ("kit", "EPCAM_MACS", "Miltenyi CD326 (EpCAM) MicroBeads"),
    ("kit", "CD8_NEG", "STEMCELL EasySep human CD8+ T cell isolation (negative)"),
    ("kit_lot", "LOT-24091", "Nanobind lot 24091"),
    ("kit_lot", "LOT-7A113", "RNeasy lot 7A113"),
    ("kit_lot", "LOT-DN2206", "DNeasy lot DN2206"),
    ("kit_lot", "LOT-CF0910", "QIAamp ccfDNA lot CF0910"),
    ("kit_lot", "LOT-KH338", "KAPA HyperPrep lot KH338"),
    ("antibody_lot", "W632-L0424", "W6/32 hybridoma supernatant, batch 0424"),
    ("index", "SI-TT-A1", "10x Dual Index TT Set A, A1"),
    ("index", "NB01", "ONT Native Barcode 01"),
    ("index", "UDI0012", "IDT UDI 0012"), ("index", "UDI0013", "IDT UDI 0013"), ("index", "UDI0014", "IDT UDI 0014"),
    ("submission", "HTSF-26-0412", "HTSF submission 26-0412 (10x)"),
    ("submission", "HTSF-26-0433", "HTSF submission 26-0433 (Illumina + ONT)"),
    ("instrument", "EXPLORIS480", "Orbitrap Exploris 480"),
    ("instrument", "PROMETHION", "ONT PromethION"),
    ("instrument", "NOVASEQX", "Illumina NovaSeq X"),
    ("spin_protocol", "300G10", "300 g, 10 min, 4 C"),
    ("spin_protocol", "2000G10", "2000 g, 10 min, 4 C"),
    ("party", "CLINIC", "Clinic / OR (collection site)"),
    ("party", "MSCORE", "UNC Proteomics core"),
    ("party", "COLLAB", "Collaborating laboratory (external)"),
    ("cohort", "SY", "Synthetic sequencing test data (not a real participant)"),
    ("submission", "HTSF-26-0501", "HTSF submission 26-0501 (synthetic IGI-SYN-SEQ libraries)"),
    ("instrument", "REVIO", "PacBio Revio"),
]

# Bench staff named in the nomenclature's worked example (display names are placeholders).
OPERATORS = [("mf", "MF (demo operator)", "MF"), ("ken", "KEN (demo operator)", "KEN")]

BUCKET = "gs://igi-mp-trial-data"


def _ensure_operators(conn, password=None):
    for username, name, initials in OPERATORS:
        if conn.execute("SELECT 1 FROM account WHERE initials=?", (initials,)).fetchone():
            continue
        create_user(conn, username, name, initials, password or secrets.token_urlsafe(16), "user")


def _lists(conn):
    for i, (cat, code, meaning) in enumerate(LIST_ENTRIES):
        conn.execute("INSERT OR IGNORE INTO code_list(category, code, meaning, active, sort_order) VALUES (?,?,?,1,?)",
                     (cat, code, meaning, 100 + i))


def _as(conn, username):
    user = conn.execute("SELECT * FROM account WHERE username=? AND active=1", (username,)).fetchone()
    if user is None:
        raise ValueError(f"No active user {username!r}")
    g.user = dict(user)
    return user


class _Seeder:
    """Small helpers that create records through the service layer and count the tubes."""

    def __init__(self, conn, username):
        self.conn, self.username, self.tubes = conn, username, []

    def participant(self, pid, unc, cohort, notes):
        conn = self.conn
        for col, val, what in (("participant_id", pid, pid), ("unc_number", unc, f"UNC{unc}")):
            row = conn.execute(f"SELECT participant_id FROM participant WHERE {col}=?", (val,)).fetchone()
            if row:
                raise ValueError(f"Demo participant already exists as {row['participant_id']} ({what})")
        row = {"participant_id": pid, "cohort_code": cohort, "unc_number": unc, "site_code": "UNC", "notes": notes,
               "created_by": self.username}
        conn.execute("INSERT INTO participant(participant_id, cohort_code, unc_number, site_code, notes, created_by) "
                     "VALUES (:participant_id, :cohort_code, :unc_number, :site_code, :notes, :created_by)", row)
        audit.log(conn, "participant", pid, "insert", after=row)
        return pid

    def collection(self, pid, specimen, received, **f):
        data = {"participant_id": pid, "specimen_code": specimen, "received_date": received, "site_code": "UNC",
                "biobank_source": "IH", "received_from": "CLINIC", "transport_temp": "ambient", "appearance": "NA", **f}
        cid = svc.create_collection(self.conn, data)
        return svc.get_collection(self.conn, cid)

    def tube(self, source, *, op, when, sop, qty, unit, fraction, material, count=1, loc=("NA", "NA", "NA", "NA"),
             status="Available", notes="NA", attrs=None, consumed=False, biobank="IH"):
        """source: a collection row (first-generation tube) or a parent sample ID."""
        payload = {"count": count, "created_datetime": when, "created_by": op, "sop_code": sop, "biobank_source": biobank,
                   "quantity": qty, "unit": unit, "freezer": loc[0], "rack": loc[1], "box": loc[2], "position": loc[3],
                   "status": status, "notes": notes, "attributes": attrs or {}, "parent_consumed": consumed,
                   "fraction": fraction, "material": material}
        if isinstance(source, str):
            payload["parent_id"] = source
        else:
            payload["collection_id"] = source["collection_id"]
        made, violations = svc.create_samples(self.conn, payload)
        if violations:
            raise ValueError(f"Demo data violates rules for {fraction}-{material}: {violations}")
        self.tubes.extend(made)
        return made

    def custody(self, sid, when, frm, to, purpose, notes=None, set_status=None, initials=None):
        conn = self.conn
        cur = conn.execute(
            "INSERT INTO custody_event(sample_id, event_datetime, from_party, to_party, purpose, condition_on_receipt, "
            "initials, notes, recorded_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, when, frm, to, purpose, "good", initials or g.user["initials"], notes, self.username))
        audit.log(conn, "custody_event", cur.lastrowid, "insert",
                  after={"sample_id": sid, "event_datetime": when, "from_party": frm, "to_party": to, "purpose": purpose})
        if set_status:
            svc.update_sample(conn, sid, {"status": set_status})

    def data_file(self, sid, folder, assay, platform, suffix, run_id, md5, pipeline, version, notes=None):
        s = svc.get_sample(self.conn, sid)
        uri = f"{BUCKET}/{folder}/{svc.suggested_file_stem(s, assay, platform)}{suffix}"
        f = {"uri": uri, "assay_code": assay, "platform_code": platform, "run_id": run_id, "checksum_md5": md5,
             "pipeline": pipeline, "pipeline_version": version, "notes": notes}
        cur = self.conn.execute(
            "INSERT INTO data_file(sample_id, uri, assay_code, platform_code, run_id, checksum_md5, pipeline, pipeline_version, notes, recorded_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, uri, assay, platform, run_id, md5, pipeline, version, notes, self.username))
        audit.log(self.conn, "data_file", cur.lastrowid, "insert", after={"sample_id": sid, **f})


CPU_ATTRS = {"cryo_medium": "CS10", "freeze_method": "MRFROSTY", "storage_phase": "LN2 vapor", "qc_result": "pass"}


def seed_demo(conn, username, second=None):
    """Participant P101 / UNC316: the worked example of nomenclature v2.1, section 5. Returns a summary dict."""
    _as(conn, username)
    _lists(conn)
    _ensure_operators(conn)
    if second is None:   # another account that makes one of the demo edits
        row = conn.execute("SELECT username FROM account WHERE active=1 AND role IN ('admin','user') AND username<>? "
                           "AND initials NOT IN ('MF','KEN') ORDER BY role, username", (username,)).fetchone()
        second = row["username"] if row else None
    S = _Seeder(conn, username)
    pid = S.participant("P101", "316", "MP", "Demonstration participant: the worked example from IGI Sample Nomenclature v2.1, "
                                             "section 5. Pleural fluid and matched blood received 29 Sep 2026.")

    # ---- pleural fluid collection, received 29 Sep 2026 ------------------------------------------
    pf = S.collection(pid, "PF", "2026-09-29", received_by="MF", time_collected="2026-09-29T09:40",
                      time_received="2026-09-29T10:30", container_type="BAG", appearance="bloody", quantity=400, unit="mL",
                      notes="Therapeutic thoracentesis, right side. About 400 mL, turbid and slightly bloody. The fluid itself is not labelled.")
    pfs = S.tube(pf, op="MF", when="2026-09-29T11:15", sop="SOP-001", qty=1.5, unit="mL", fraction="PFS", material="FRZ", count=4,
                 loc=("FRZ-A", "R1", "B01", "A1"), notes="Step 1: cell-free supernatant after a 300 g spin, frozen in 4 tubes.",
                 attrs={"spin_protocol": "300G10", "filtered": "0.45", "appearance": "turbid", "volume_ml": 1.5, "freeze_temp": "-80C", "qc_result": "pass"})
    pfm = S.tube(pf, op="MF", when="2026-09-29T14:30", sop="SOP-002", qty=1, unit="mL", fraction="PFM", material="CPU", count=10,
                 loc=("LN2-1", "R1", "B02", "A1"), notes="Step 2: PFMCs isolated (Ficoll) and cryopreserved, 10 vials.",
                 attrs={"isolation_method": "FICOLL", "rbc_lysis": "no", "cell_count": 80000000, "viability_pct": 92,
                        "count_method": "Countess", "cells_per_vial": 8000000, **CPU_ATTRS})
    vial3 = pfm[2]
    [tum_cpu] = S.tube(vial3, op="MF", when="2026-10-01T10:00", sop="SOP-004", qty=1, unit="mL", fraction="TUM", material="CPU",
                       loc=("LN2-1", "R1", "B03", "A1"), notes="Step 3: PFMC vial 03 thawed; tumour cells enriched (EpCAM) and cryopreserved.",
                       attrs={"enrichment_method": "EPCAM", "kit": "EPCAM_MACS", "purity_pct": 86, "purity_method": "flow",
                              "cell_count": 3200000, "viability_pct": 81, "count_method": "flow", "cells_per_vial": 1000000, **CPU_ATTRS})
    [imm_cpu] = S.tube(vial3, op="MF", when="2026-10-01T10:20", sop="SOP-004", qty=1, unit="mL", fraction="IMM", material="CPU",
                       loc=("LN2-1", "R1", "B03", "A2"), notes="Step 3: immune fraction kept from the same run.",
                       attrs={"enrichment_method": "CD45POS", "purity_pct": 91, "purity_method": "flow", "cell_count": 4100000,
                              "viability_pct": 88, "count_method": "flow", **CPU_ATTRS})
    snf = S.tube(vial3, op="MF", when="2026-10-01T11:00", sop="SOP-004", qty=1000000, unit="cells", fraction="TUM", material="SNF",
                 count=2, loc=("FRZ-A", "R2", "B01", "A1"), consumed=True,
                 notes="Step 5: snap-frozen tumour cell pellets from the same run, for Ken.",
                 attrs={"cell_count": 1000000, "wash_buffer": "PBS", "pellet_state": "dry", "intended_use": "DNA+RNA",
                        "freeze_method": "LN2", "qc_result": "pass"})
    [cd8] = S.tube(imm_cpu, op="MF", when="2026-10-02T13:00", sop="SOP-004", qty=1, unit="mL", fraction="CD8", material="CPU",
                   loc=("LN2-1", "R1", "B03", "A3"), notes="Step 4: CD8+ T cells enriched from the immune fraction.",
                   attrs={"selection_mode": "negative", "kit": "CD8_NEG", "purity_pct": 95, "cell_count": 900000,
                          "viability_pct": 90, "count_method": "flow", **CPU_ATTRS})
    for t in snf:
        S.custody(t, "2026-10-01T15:00", "MF", "KEN", "EXTRACT", notes="Pellets handed to Ken for DNA/RNA extraction.")
    _as(conn, "ken") if conn.execute("SELECT 1 FROM account WHERE username='ken'").fetchone() else None
    [hmd] = S.tube(snf[0], op="KEN", when="2026-10-06T11:20", sop="SOP-005", qty=40, unit="uL", fraction="TUM", material="HMD",
                   loc=("FRZ-A", "R2", "B02", "A1"), consumed=True, notes="Step 6: HMW DNA extracted by Ken for ONT.",
                   attrs={"extraction_kit": "NANOBIND", "kit_lot": "LOT-24091", "concentration_ng_ul": 85.2,
                          "concentration_method": "Qubit", "a260_280": 1.84, "a260_230": 2.1, "volume_ul": 40, "din": 9.4,
                          "n50_kb": 62, "shearing": "NONE", "elution_buffer": "EB", "input_cells": 1000000, "qc_result": "pass"})
    [rna] = S.tube(snf[1], op="KEN", when="2026-10-06T12:05", sop="SOP-005", qty=30, unit="uL", fraction="TUM", material="RNA",
                   loc=("FRZ-A", "R2", "B02", "A2"), consumed=True, notes="Step 6: RNA extracted by Ken.",
                   attrs={"extraction_kit": "RNEASY", "kit_lot": "LOT-7A113", "concentration_ng_ul": 120.0,
                          "concentration_method": "Qubit", "a260_280": 2.02, "a260_230": 1.9, "volume_ul": 30, "rin": 8.7,
                          "dv200": 91, "dnase_treated": "yes", "elution_buffer": "H2O", "input_cells": 1000000, "qc_result": "pass"})
    S.custody(hmd, "2026-10-07T09:00", "KEN", "HTSF", "SEQ", notes="ONT sequencing; all material used.", set_status="Depleted")
    S.data_file(hmd, "ont", "WGS", "ONT", ".bam", "PAW12345-261008", "9e107d9d372bb6826bd81d3542a419d6", "dorado", "0.9.1",
                "Basecalled BAM with 5mC/5hmC tags")
    S.custody(rna, "2026-10-07T09:00", "KEN", "HTSF", "SEQ", notes="Bulk RNA-seq submission.")
    S.data_file(rna, "rnaseq", "RSQ", "ILM", "_S1_L001_R1_001.fastq.gz", "NX-261010-0433", "a3f1c0b2e4d5968778695a4b3c2d1e0f",
                "nf-core/rnaseq", "3.14.0", "Paired-end FASTQ (R1 shown)")
    _as(conn, username)
    cul = S.tube(tum_cpu, op="MF", when="2026-10-02T16:00", sop="SOP-004", qty=1, unit="mL", fraction="TUM", material="CUL", count=6,
                 loc=("LN2-1", "R2", "B01", "A1"), consumed=True,
                 notes="Step 7: tumour cells thawed and expanded for immunopeptidomics; excess frozen.",
                 attrs={"medium": "RPMI10", "supplements": "NONE", "stimulation": "NONE", "passage": 2, "days_in_culture": 14,
                        "cell_count": 60000000, "viability_pct": 94, "expansion_fold": 20, "mycoplasma": "negative", "qc_result": "pass"})
    [snf3] = S.tube(cul[0], op="MF", when="2026-10-16T10:00", sop="SOP-004", qty=10000000, unit="cells", fraction="TUM", material="SNF",
                    loc=("FRZ-A", "R2", "B01", "A3"), consumed=True,
                    notes="Step 8: snap-frozen pellet of expanded cells; the CUL parent shows it came from culture.",
                    attrs={"cell_count": 10000000, "wash_buffer": "PBS", "pellet_state": "dry", "intended_use": "IP",
                           "freeze_method": "LN2", "qc_result": "pass"})
    [pep] = S.tube(snf3, op="MF", when="2026-10-17T17:30", sop="SOP-007", qty=20, unit="uL", fraction="TUM", material="PEP",
                   loc=("FRZ-A", "R2", "B03", "A1"), status="In use", notes="Step 9: HLA class I peptide eluate for mass spectrometry.",
                   attrs={"hla_class": "I", "ip_antibody": "W632", "antibody_lot": "W632-L0424", "input_cells": 10000000,
                          "bead_type": "PROTA", "elution": "TFA01", "cleanup": "C18", "resuspension_ul": 20,
                          "target_instrument": "EXPLORIS480", "qc_result": "not assessed"})
    S.custody(pep, "2026-10-18T10:00", "MF", "MSCORE", "IP", notes="Queued on the Exploris 480.")
    S.data_file(pep, "immunopeptidomics", "IPX", "MS", ".raw", "EXP480-261019-07", "0cc175b9c0f1b6a831c399e269772661",
                "FragPipe", "22.0", "Raw file and FragPipe HLA search")

    # ---- matched blood, a separate collection received the same day ------------------------------
    pb = S.collection(pid, "PB", "2026-09-29", received_by="MF", time_collected="2026-09-29T09:15",
                      time_received="2026-09-29T10:30", container_type="EDTA", appearance="clear", quantity=20, unit="mL",
                      notes="Two 10 mL EDTA tubes drawn at the time of the tap.")
    S.tube(pb, op="MF", when="2026-09-29T11:40", sop="SOP-008", qty=1, unit="mL", fraction="SER", material="FRZ",
           loc=("FRZ-A", "R3", "B01", "A1"), attrs={"clot_time_min": 30, "spin_protocol": "2000G10", "hemolysis_grade": "none", "qc_result": "pass"})
    pla = S.tube(pb, op="MF", when="2026-09-29T11:30", sop="SOP-008", qty=1, unit="mL", fraction="PLA", material="FRZ", count=3,
                 loc=("FRZ-A", "R3", "B01", "A2"), notes="Double-spun plasma.",
                 attrs={"spin_protocol": "2000G10", "time_to_spin_min": 45, "hemolysis_grade": "none", "qc_result": "pass"})
    [bfc] = S.tube(pb, op="MF", when="2026-09-29T11:45", sop="SOP-008", qty=0.5, unit="mL", fraction="BFC", material="FRZ",
                   loc=("FRZ-A", "R3", "B01", "A5"), notes="Buffy coat for germline DNA.",
                   attrs={"spin_protocol": "2000G10", "rbc_lysis": "no", "qc_result": "pass"})
    pbm = S.tube(pb, op="MF", when="2026-09-29T18:10", sop="SOP-002", qty=1, unit="mL", fraction="PBM", material="CPU", count=4,
                 loc=("LN2-1", "R1", "B04", "A1"), notes="SepMate PBMC; 4 vials at 5e6 cells/vial.",
                 attrs={"isolation_method": "SEPMATE", "rbc_lysis": "no", "cell_count": 21000000, "viability_pct": 96,
                        "count_method": "Countess", "cells_per_vial": 5000000, **CPU_ATTRS})
    [cfd] = S.tube(pla[0], op="MF", when="2026-09-30T14:00", sop="SOP-005", qty=50, unit="uL", fraction="PLA", material="CFD",
                   loc=("FRZ-A", "R3", "B02", "A1"), consumed=True, notes="Cell-free DNA from 1 mL plasma.",
                   attrs={"plasma_input_ml": 1.0, "extraction_kit": "CCFDNA", "kit_lot": "LOT-CF0910", "concentration_ng_ul": 0.8,
                          "concentration_method": "TapeStation", "total_yield_ng": 40, "cfdna_peak_bp": 167,
                          "hmw_contamination_pct": 5, "volume_ul": 50, "elution_buffer": "EB", "qc_result": "pass"})
    S.custody(bfc, "2026-10-01T15:00", "MF", "KEN", "EXTRACT", notes="Buffy coat for germline DNA.")
    _as(conn, "ken") if conn.execute("SELECT 1 FROM account WHERE username='ken'").fetchone() else None
    [gdna] = S.tube(bfc, op="KEN", when="2026-10-06T14:40", sop="SOP-005", qty=100, unit="uL", fraction="BFC", material="DNA",
                    loc=("FRZ-A", "R3", "B02", "A2"), consumed=True, notes="Germline DNA for the matched-normal exome.",
                    attrs={"extraction_kit": "DNEASY", "kit_lot": "LOT-DN2206", "concentration_ng_ul": 45.0,
                           "concentration_method": "Qubit", "a260_280": 1.86, "a260_230": 2.05, "volume_ul": 100, "din": 8.9,
                           "elution_buffer": "EB", "qc_result": "pass"})
    S.custody(gdna, "2026-10-07T09:00", "KEN", "HTSF", "SEQ", notes="Germline exome submission.", set_status="Depleted")
    S.data_file(gdna, "wes", "WES", "ILM", ".bam", "NX-261010-0433", "8277e0910d750195b448797616e091ad", "nf-core/sarek", "3.4.4",
                "Germline exome BAM")
    _as(conn, username)

    # ---- flagged history: two direct edits (one by a second account) and one correction --------------
    edits = []
    svc.update_sample(conn, pfs[0], {"quantity": 1.0},
                      reason="Took 0.5 mL of supernatant for the cytokine panel (not tracked as a tube).")
    edits.append(pfs[0])
    if second:
        me = g.user
        g.user = dict(conn.execute("SELECT * FROM account WHERE username=?", (second,)).fetchone())
        svc.update_sample(conn, pfm[4], {"box": "B04", "position": "C3"},
                          reason="Vial moved to box B04 during the LN2-1 reorganisation on 2026-10-12.")
        g.user = me
        edits.append(pfm[4])
    svc.add_correction(conn, "created_datetime", "2026-09-29T19:40",
                       "Logged at 18:10 when the spin started; the vials went into the Mr Frosty at 19:40.", sample_id=pbm[0])

    return {"participant": pid, "unc_id": "UNC316", "tubes": len(S.tubes), "collections": [pf["collection_id"], pb["collection_id"]],
            "edits": edits, "second": second, "corrected": pbm[0]}


# Smaller participants in the other cohorts, so the picker and the trees have something to compare.
EXTRA_PARTICIPANTS = [
    ("P102", "327", "AM", "Demonstration participant. Diagnostic marrow and blood at presentation; one vial shipped to a collaborator."),
    ("P103", "341", "TN", "Demonstration participant. Core biopsy before neoadjuvant therapy as FFPE and OCT blocks, plus blood."),
    ("P104", "352", "NC", "Demonstration participant. Lymph node resection; blood received but not yet processed."),
]


def seed_extra_participants(conn, username):
    """Three shorter participants (AML, TNBC, NUT carcinoma). Returns {participant_id: tube_count}."""
    _as(conn, username)
    _lists(conn)
    _ensure_operators(conn)
    out = {}

    # ---- AML: marrow + blood ---------------------------------------------------------------------
    pid, unc, cohort, note = EXTRA_PARTICIPANTS[0]
    S = _Seeder(conn, username)
    S.participant(pid, unc, cohort, note)
    bm = S.collection(pid, "BM", "2026-09-30", received_by="MF", time_collected="2026-09-30T10:55", time_received="2026-09-30T11:40",
                      container_type="HEP", appearance="bloody", quantity=8, unit="mL", notes="Diagnostic marrow aspirate, 8 mL in heparin.")
    blasts = S.tube(bm, op="MF", when="2026-09-30T15:30", sop="SOP-002", qty=1, unit="mL", fraction="TUM", material="CPU", count=5,
                    loc=("LN2-1", "R2", "B01", "A1"), notes="Ficoll mononuclear cells, 85% blasts by morphology.",
                    attrs={"enrichment_method": "NONE", "purity_pct": 85, "purity_method": "cytology", "cell_count": 50000000,
                           "viability_pct": 94, "count_method": "Countess", "cells_per_vial": 10000000, **CPU_ATTRS})
    [dna] = S.tube(blasts[0], op="KEN", when="2026-10-02T10:15", sop="SOP-005", qty=60, unit="uL", fraction="TUM", material="DNA",
                   loc=("FRZ-A", "R4", "B01", "A1"), consumed=True, notes="DNeasy from vial 1 for the diagnostic exome.",
                   attrs={"extraction_kit": "DNEASY", "kit_lot": "LOT-DN2206", "concentration_ng_ul": 110.0, "concentration_method": "Qubit",
                          "a260_280": 1.85, "a260_230": 2.2, "volume_ul": 60, "din": 9.1, "elution_buffer": "EB", "qc_result": "pass"})
    S.custody(dna, "2026-10-08T09:15", "KEN", "HTSF", "SEQ", notes="Tumour exome submission.", set_status="Depleted", initials="KEN")
    S.data_file(dna, "wes", "WES", "ILM", ".bam", "NX-261010-0433", "45c48cce2e2d7fbdea1afc51c7c6ad26", "nf-core/sarek", "3.4.4",
                "Tumour-only exome")
    S.custody(blasts[1], "2026-10-09T14:00", "MF", "COLLAB", "SHIP", notes="Dry shipper to the collaborating lab for the drug screen.",
              set_status="Shipped")
    svc.update_sample(conn, blasts[2], {"status": "Destroyed"},
                      reason="Vial found thawed in the LN2-1 rack during the 2026-10-12 inventory; discarded per SOP-002.")
    pb = S.collection(pid, "PB", "2026-09-30", received_by="MF", time_collected="2026-09-30T10:50", time_received="2026-09-30T11:40",
                      container_type="EDTA", appearance="clear", quantity=10, unit="mL", notes="One 10 mL EDTA tube drawn with the marrow.")
    S.tube(pb, op="MF", when="2026-09-30T13:00", sop="SOP-008", qty=1, unit="mL", fraction="PLA", material="FRZ", count=3,
           loc=("FRZ-A", "R3", "B03", "A1"), attrs={"spin_protocol": "2000G10", "time_to_spin_min": 60, "hemolysis_grade": "none"})
    S.tube(pb, op="MF", when="2026-09-30T16:10", sop="SOP-002", qty=1, unit="mL", fraction="PBM", material="CPU", count=2,
           loc=("LN2-1", "R2", "B01", "B1"), notes="PBMC as the germline comparator.",
           attrs={"isolation_method": "FICOLL", "cell_count": 9000000, "viability_pct": 95, "count_method": "Countess",
                  "cells_per_vial": 4500000, **CPU_ATTRS})
    out[pid] = len(S.tubes)

    # ---- TNBC: core biopsy as FFPE and OCT, blood ----------------------------------------------------
    pid, unc, cohort, note = EXTRA_PARTICIPANTS[1]
    S = _Seeder(conn, username)
    S.participant(pid, unc, cohort, note)
    tu = S.collection(pid, "TU", "2026-10-01", received_by="MF", time_collected="2026-10-01T09:20", time_received="2026-10-01T09:50",
                      container_type="PLAIN", transport_temp="ice", quantity=4, unit="NA",
                      notes="Four 14G cores from the primary breast lesion: two to FFPE, two to OCT.")
    [ffpe] = S.tube(tu, op="MF", when="2026-10-02T12:00", sop="SOP-001", qty=1, unit="NA", fraction="TUM", material="FFP",
                    notes="FFPE block from cores 1-2, kept in the pathology archive.",
                    attrs={"block_id": "NA", "fixation_time_h": 18, "block_age_years": 0, "section_thickness_um": 5,
                           "tumor_pct": 70, "macrodissected": "no", "qc_result": "pass"})
    S.tube(tu, op="MF", when="2026-10-01T10:10", sop="SOP-001", qty=1, unit="NA", fraction="TUM", material="OCT",
           loc=("FRZ-A", "R4", "B02", "A1"), notes="Cores 3-4 in OCT, frozen on dry ice.",
           attrs={"tissue_mass_mg": 30, "block_id": "NA", "sections_cut": 0, "tumor_pct": 65, "qc_result": "pass"})
    S.tube(ffpe, op="KEN", when="2026-10-07T11:30", sop="SOP-005", qty=25, unit="uL", fraction="TUM", material="RNA",
           loc=("FRZ-A", "R4", "B03", "A1"), notes="AllPrep FFPE RNA from 6 x 10 um sections; RIN low as expected for FFPE.",
           attrs={"extraction_kit": "ALLPREP", "concentration_ng_ul": 22.0, "concentration_method": "Qubit", "a260_280": 1.95,
                  "a260_230": 1.6, "volume_ul": 25, "rin": 2.4, "dv200": 48, "dnase_treated": "yes", "elution_buffer": "H2O",
                  "qc_result": "borderline"})
    pb = S.collection(pid, "PB", "2026-10-01", received_by="MF", time_collected="2026-10-01T09:05", time_received="2026-10-01T09:50",
                      container_type="EDTA", appearance="clear", quantity=10, unit="mL", notes="One 10 mL EDTA tube drawn before the biopsy.")
    S.tube(pb, op="MF", when="2026-10-01T11:00", sop="SOP-008", qty=1, unit="mL", fraction="PLA", material="FRZ", count=2,
           loc=("FRZ-A", "R3", "B03", "B1"), attrs={"spin_protocol": "2000G10", "time_to_spin_min": 50, "hemolysis_grade": "mild"})
    pbm = S.tube(pb, op="MF", when="2026-10-01T14:20", sop="SOP-002", qty=1, unit="mL", fraction="PBM", material="CPU", count=2,
                 loc=("LN2-1", "R2", "B02", "A1"), attrs={"isolation_method": "SEPMATE", "cell_count": 8000000, "viability_pct": 97,
                                                         "count_method": "Countess", "cells_per_vial": 4000000, **CPU_ATTRS})
    svc.update_sample(conn, pbm[0], {"status": "In use"}, reason="Checked out for the germline DNA extraction.")
    out[pid] = len(S.tubes)

    # ---- NUT carcinoma: lymph node -> pellets -> HMW RNA; blood received, not processed -------------
    pid, unc, cohort, note = EXTRA_PARTICIPANTS[2]
    S = _Seeder(conn, username)
    S.participant(pid, unc, cohort, note)
    ln = S.collection(pid, "LN", "2026-10-08", received_by="MF", time_collected="2026-10-08T12:45", time_received="2026-10-08T13:30",
                      container_type="PLAIN", transport_temp="ice", quantity=1200, unit="mg",
                      notes="Cervical lymph node from the resection, 1.2 g fresh in saline; dissociated on arrival.")
    snf = S.tube(ln, op="MF", when="2026-10-08T15:00", sop="SOP-004", qty=5000000, unit="cells", fraction="TUM", material="SNF", count=4,
                 loc=("FRZ-A", "R4", "B04", "A1"), consumed=False, notes="Dissociated tumour cells, four pellets snap frozen.",
                 attrs={"cell_count": 5000000, "pellet_state": "dry", "intended_use": "RNA", "freeze_method": "LN2", "qc_result": "pass"})
    [hmr] = S.tube(snf[0], op="KEN", when="2026-10-10T10:00", sop="SOP-005", qty=50, unit="uL", fraction="TUM", material="HMR",
                   loc=("FRZ-A", "R4", "B03", "B1"), status="In use", notes="TRIzol HMW RNA from pellet 1 for direct-RNA nanopore.",
                   attrs={"extraction_kit": "TRIZOL", "concentration_ng_ul": 310.0, "concentration_method": "NanoDrop", "a260_280": 2.05,
                          "a260_230": 2.1, "volume_ul": 50, "rin": 9.0, "dv200": 95, "dnase_treated": "yes", "elution_buffer": "H2O",
                          "qc_result": "pass"})
    svc.update_sample(conn, snf[0], {"status": "Depleted"}, reason="Whole pellet used for the RNA extraction.")
    S.custody(hmr, "2026-10-13T09:00", "KEN", "HTSF", "SEQ", notes="Direct RNA library and PromethION run at HTSF.")
    S.collection(pid, "PB", "2026-10-08", received_by="MF", time_collected="2026-10-08T07:30", time_received="2026-10-08T13:30",
                 container_type="EDTA", appearance="clear", transport_temp="4C", quantity=10, unit="mL",
                 notes="Pre-op EDTA tube held at 4 C; not processed yet, so it has no tubes.")
    out[pid] = len(S.tubes)
    return out


# Synthetic patients whose reads are real files on the cluster (RAFT/LENS test inputs). The tubes, dates and
# lab details are invented; the file paths are the full-release files listed in each dataset's LENS manifest.
SYN_ROOT = "/datastore/nextgenout5/share/labs/Vincent_Lab/members/spvensko/raft/inputs"
SYN_PARTICIPANTS = [("P105", "901", "IGI-SYN-SEQ-01", "2026-10-20"), ("P106", "902", "IGI-SYN-SEQ-02", "2026-10-21")]
# (extract, manifest run name, file names with {ds}, assay, platform)
SYN_LIBRARIES = [
    ("tum_dna", "ad-wes-tumor", ["fastqs/{ds}/full/{ds}_tumor_wes_R1.fastq.gz", "fastqs/{ds}/full/{ds}_tumor_wes_R2.fastq.gz"], "WES", "ILM"),
    ("tum_dna", "ad-wgs-tumor", ["fastqs/{ds}/full/{ds}_tumor_wgs_R1.fastq.gz", "fastqs/{ds}/full/{ds}_tumor_wgs_R2.fastq.gz"], "WGS", "ILM"),
    ("nrm_dna", "nd-wes-normal", ["fastqs/{ds}/full/{ds}_normal_wes_R1.fastq.gz", "fastqs/{ds}/full/{ds}_normal_wes_R2.fastq.gz"], "WES", "ILM"),
    ("nrm_dna", "nd-wgs-normal", ["fastqs/{ds}/full/{ds}_normal_wgs_R1.fastq.gz", "fastqs/{ds}/full/{ds}_normal_wgs_R2.fastq.gz"], "WGS", "ILM"),
    ("tum_hmd", "ad-ont-wgs-tumor", ["fastqs/{ds}/full/{ds}_tumor_ont_wgs.fastq.gz"], "WGS", "ONT"),
    ("tum_hmd", "ad-hifi-wgs-tumor", ["bams/{ds}/full/{ds}_tumor_hifi.bam"], "WGS", "PAC"),
    ("nrm_hmd", "nd-ont-wgs-normal", ["fastqs/{ds}/full/{ds}_normal_ont_wgs.fastq.gz"], "WGS", "ONT"),
    ("nrm_hmd", "nd-hifi-wgs-normal", ["bams/{ds}/full/{ds}_normal_hifi.bam"], "WGS", "PAC"),
    ("tum_rna", "ar-rna-tumor", ["fastqs/{ds}/full/{ds}_full_rna_R1.fastq.gz", "fastqs/{ds}/full/{ds}_full_rna_R2.fastq.gz"], "RSQ", "ILM"),
    ("tum_rna", "ar-ont-bulk-rna", ["fastqs/{ds}/full/{ds}_full_ont_bulk_rna.fastq.gz"], "RSQ", "ONT"),
    ("tum_rna", "ar-kinnex-bulk", ["bams/{ds}/full/{ds}_full_kinnex_bulk_segmented.bam"], "RSQ", "PAC"),
    ("tum_scs", "ar-gex-tumor", ["fastqs/{ds}/full/{ds}-GEX_S1_L001_R1_001.fastq.gz", "fastqs/{ds}/full/{ds}-GEX_S1_L001_R2_001.fastq.gz"], "SCR", "10X"),
    ("tum_scs", "ar-tcr-tumor", ["fastqs/{ds}/full/{ds}-TCR_S1_L001_R1_001.fastq.gz", "fastqs/{ds}/full/{ds}-TCR_S1_L001_R2_001.fastq.gz"], "VDJ", "10X"),
    ("tum_scs", "ar-ont-sc-rna", ["fastqs/{ds}/full/{ds}_full_ont_sc_rna.fastq.gz"], "SCR", "ONT"),
    ("tum_scs", "ar-kinnex-sc", ["bams/{ds}/full/{ds}_full_kinnex_sc_segmented.bam"], "SCR", "PAC"),
]
_SYN_RUN = {"ILM": "NX-261027-0501", "10X": "NX-261027-0501", "ONT": "PAW90501-261028", "PAC": "r84501_261029"}


def seed_synthetic_participants(conn, username):
    """P105 / P106: synthetic patients IGI-SYN-SEQ-01 and -02 (tumour + matched blood), with every library in
    their LENS manifests linked to the extract it was made from. Returns {participant_id: tube_count}."""
    _as(conn, username)
    _lists(conn)
    _ensure_operators(conn)
    out = {}
    for pid, unc, ds, day in SYN_PARTICIPANTS:
        S = _Seeder(conn, username)
        S.participant(pid, unc, "SY", f"Synthetic patient {ds}: invented tube history; the reads are the simulated "
                                      f"RAFT/LENS test inputs on the cluster (inputs/fastqs/{ds}, inputs/bams/{ds}).")
        conn.execute("UPDATE participant SET external_participant_id=? WHERE participant_id=?", (ds, pid))
        tu = S.collection(pid, "TU", day, received_by="MF", time_collected=f"{day}T09:00", time_received=f"{day}T09:45",
                          container_type="PLAIN", transport_temp="ice", quantity=500, unit="mg",
                          notes=f"Synthetic resection for {ds}; dissociated on arrival.")
        [cells] = S.tube(tu, op="MF", when=f"{day}T13:00", sop="SOP-004", qty=1, unit="mL", fraction="TUM", material="CPU",
                         loc=("LN2-1", "R4", "B01", "A1"), notes="Dissociated tumour cells, cryopreserved.",
                         attrs={"enrichment_method": "NONE", "cell_count": 20000000, "viability_pct": 90, "count_method": "Countess",
                                "cells_per_vial": 20000000, **CPU_ATTRS})
        pb = S.collection(pid, "PB", day, received_by="MF", time_collected=f"{day}T08:40", time_received=f"{day}T09:45",
                          container_type="EDTA", appearance="clear", quantity=10, unit="mL", notes="Matched normal blood.")
        [pbmc] = S.tube(pb, op="MF", when=f"{day}T15:00", sop="SOP-002", qty=1, unit="mL", fraction="PBM", material="CPU",
                        loc=("LN2-1", "R4", "B01", "B1"), notes="PBMC, germline comparator.",
                        attrs={"isolation_method": "SEPMATE", "cell_count": 10000000, "viability_pct": 95, "count_method": "Countess",
                               "cells_per_vial": 10000000, **CPU_ATTRS})
        ext = {}
        for key, parent, frac, mat, unit, qty, when in (
                ("tum_dna", cells, "TUM", "DNA", "uL", 60, "T10:00"), ("tum_hmd", cells, "TUM", "HMD", "uL", 50, "T10:30"),
                ("tum_rna", cells, "TUM", "RNA", "uL", 40, "T11:00"), ("tum_scs", cells, "TUM", "SCS", "uL", 50, "T09:30"),
                ("nrm_dna", pbmc, "PBM", "DNA", "uL", 60, "T13:00"), ("nrm_hmd", pbmc, "PBM", "HMD", "uL", 50, "T13:30")):
            next_day = f"{day[:8]}{int(day[8:]) + 2:02d}"
            [ext[key]] = S.tube(parent, op="KEN", when=next_day + when, sop="SOP-003" if mat == "SCS" else "SOP-005",
                                qty=qty, unit=unit, fraction=frac, material=mat, loc=("FRZ-A", "R4", "B04", "NA"),
                                notes="10x 5' single-cell suspension; GEX and TCR libraries, cDNA also read on ONT and Kinnex."
                                if mat == "SCS" else "Extract for the synthetic library set.")
        for key, run_name, files, assay, platform in SYN_LIBRARIES:
            for f in files:
                uri = f"{SYN_ROOT}/{f.format(ds=ds)}"
                cur = conn.execute(
                    "INSERT INTO data_file(sample_id, uri, assay_code, platform_code, run_id, notes, recorded_by) VALUES (?,?,?,?,?,?,?)",
                    (ext[key], uri, assay, platform, _SYN_RUN[platform], f"Synthetic reads; LENS manifest run {run_name} ({ds}).", username))
                audit.log(conn, "data_file", cur.lastrowid, "insert", after={"sample_id": ext[key], "uri": uri, "assay_code": assay,
                                                                              "platform_code": platform})
        for key in ext:
            S.custody(ext[key], f"{day[:8]}{int(day[8:]) + 5:02d}T09:00", "KEN", "HTSF", "SEQ",
                      notes="Library prep and sequencing (HTSF-26-0501).", initials="KEN")
        out[pid] = len(S.tubes)
    return out


# Fictional reagent boxes for trying "Scan kit / reagent" on the demo. GTINs use GS1's restricted-circulation prefix
# 02 (never a real product). (gtin, field, code it is known as or None = not learned yet, lot, expiry YYMMDD, label)
DEMO_REAGENTS = [
    ("02000000100012", "kit", "EPCAM_MACS", "E2611A", "271130", "EpCAM MicroBeads (known product, new lot)"),
    ("02000000100029", "extraction_kit", "DNEASY", "LOT-DN2206", "270630", "DNeasy kit (known product and lot)"),
    ("02000000100036", "extraction_kit", "RNEASY", "7A099", "260131", "RNeasy kit (expired)"),
    ("02000000100043", None, None, "CF1104", "280228", "ccfDNA kit (not learned yet)"),
]


def seed_demo_reagents(conn, username):
    from . import audit
    for gtin, field, code, *_ in DEMO_REAGENTS:
        if field and code:
            cur = conn.execute("INSERT OR IGNORE INTO reagent_barcode(product_key, field_key, code, created_by) VALUES (?,?,?,?)",
                               (gtin, field, code, username))
            if cur.rowcount:
                audit.log(conn, "reagent_barcode", cur.lastrowid, "insert", after={"product_key": gtin, "field": field, "code": code})


# Fictional quick-qc results so the Sequencing QC page has something to show on the demo. Values are invented
# (seeded, so every reset gives the same numbers) and marked "demo values" in the workflow version.
QC_CHECKS_ALL = ["inputs.resolved", "inputs.integrity", "inputs.mate_names", "reads.depth", "reads.quality", "species",
                 "assay.molecule", "assay.capture", "assay.receptor", "reads.type", "reads.platform", "singlecell.barcodes",
                 "singlecell.chemistry", "manifest.consistency", "identity.patient", "identity.cross_patient", "identity.sex",
                 "identity.contamination", "identity.tumor_normal", "reads.coverage", "reads.duplication"]
# (participant, library) -> (check, status, observed, expected, reason): the few results that are not clean
_QC_SURPRISES = {
    ("P106", "ad-wgs-tumor"): ("reads.coverage", "warn", "14.2x", ">= 20x", "projected mean depth below the WGS warn threshold"),
    ("P106", "nd-wes-normal"): ("identity.contamination", "warn", "3.1%", "< 2%", "other-allele reads at homozygous sites"),
    ("P106", "nd-ont-wgs-normal"): ("identity.tumor_normal", "fail", "imbalance on 3 arms", "declared normal: none",
                                     "declared normal shows tumour-like allele imbalance; likely swap partner ad-ont-wgs-tumor"),
    ("P105", "ar-ont-sc-rna"): ("singlecell.barcodes", "warn", "61% on whitelist", ">= 70%", "low 10x barcode rate"),
    ("P101", "rnaseq"): ("reads.duplication", "warn", "47%", "< 40%", "information only for RNA"),
}


def _qc_values(rng, assay, platform, normal):
    """Plausible-looking invented metrics for one library."""
    u = rng.uniform
    m, x = {}, {}
    if platform in ("ILM", "10X"):
        reads = {"WGS": u(6e8, 9e8), "WES": u(8e7, 1.2e8), "RSQ": u(4e7, 7e7), "SCR": u(2e8, 4e8), "VDJ": u(2e7, 4e7)}.get(assay, u(5e7, 1e8))
        m.update(total_reads=int(reads), mean_read_length=round(u(146, 150), 1), mean_quality=round(u(34.5, 36.8), 1),
                 pct_q30=round(u(88, 94.5), 1), pct_gc=round(u(40, 44) if assay != "RSQ" else u(46, 51), 1))
        m["total_bases"] = int(reads * m["mean_read_length"])
        x["q20_frac"] = round(u(0.95, 0.985), 3)
        if assay in ("WGS", "WES", "RSQ"):
            m["pct_duplication"] = round({"WGS": u(7, 15), "WES": u(10, 24), "RSQ": u(28, 39)}[assay], 1)
    elif platform == "ONT":
        reads = u(4e6, 9e6) if assay == "WGS" else u(1e7, 2.2e7)
        rl = u(8000, 15000) if assay == "WGS" else u(700, 1400)
        m.update(total_reads=int(reads), mean_read_length=round(rl), read_n50=round(rl * u(1.6, 2.1)), mean_quality=round(u(15, 19.5), 1))
        m["total_bases"] = int(reads * rl)
    elif platform == "PAC":
        reads = u(1.8e6, 3.5e6) if assay == "WGS" else u(2e7, 5e7)
        rl = u(14000, 19000) if assay == "WGS" else u(1500, 3000)
        m.update(total_reads=int(reads), mean_read_length=round(rl), read_n50=round(rl * u(1.05, 1.2)), mean_quality=round(u(30, 34), 1))
        m["total_bases"] = int(reads * rl)
    if assay == "WGS":
        m["mean_coverage"] = round(m["total_bases"] / 3.1e9 * u(0.85, 0.95), 1)
    if assay == "WES":
        m["mean_coverage"] = round(u(120, 185) if platform == "ILM" else u(60, 90), 1)
        m["pct_target_20x"] = round(u(95, 98.5), 1)
    x["species_human_frac"] = round(u(0.985, 0.999), 4)
    x["intron_frac"] = round(u(0.22, 0.4) if assay in ("RSQ", "SCR") else u(0.005, 0.02), 3)
    x["exome_frac"] = round(u(0.6, 0.76) if assay == "WES" else u(0.015, 0.03), 3)
    if assay in ("WGS", "WES"):
        x["contamination_pct"] = round(u(0.05, 0.9), 2)
    return m, x


def _qc_checks(assay, platform):
    rna, sc, dna = assay in ("RSQ", "SCR", "VDJ"), assay in ("SCR", "VDJ"), assay in ("WGS", "WES")
    na = set()
    if platform != "ILM" and platform != "10X":
        na.add("inputs.mate_names")
    if not dna:
        na |= {"assay.capture", "identity.contamination"}
    if not sc:
        na |= {"singlecell.barcodes", "singlecell.chemistry"}
    if assay != "VDJ":
        pass
    if not (dna or assay == "RSQ"):
        na.add("reads.coverage")
    if rna:
        na.add("reads.duplication")
    return [(c, "not_assessed" if c in na else "pass") for c in QC_CHECKS_ALL]


def seed_demo_seq_qc(conn):
    """One fictional quick-qc result per sequenced library (synthetic patients: per manifest row; others: per file)."""
    import random
    from . import seqqc
    libs = []    # (sample_id, participant, library name, assay, platform, a file of the library)
    syn_files = {}
    for pid, unc, ds, day in SYN_PARTICIPANTS:
        for f in conn.execute("SELECT d.*, s.participant_id FROM data_file d JOIN sample s USING(sample_id) WHERE s.participant_id=? "
                              "AND d.deleted_at IS NULL ORDER BY d.id", (pid,)):
            run = (f["notes"] or "").split("LENS manifest run ")[-1].split(" ")[0]
            syn_files.setdefault((f["sample_id"], run), f)
    for (sid, run), f in syn_files.items():
        libs.append((sid, f["participant_id"], run, f["assay_code"], f["platform_code"], f["uri"]))
    for f in conn.execute("SELECT d.*, s.participant_id FROM data_file d JOIN sample s USING(sample_id) WHERE d.deleted_at IS NULL "
                          "AND d.platform_code IN ('ILM','ONT','PAC','10X') AND s.cohort_code <> 'SY' ORDER BY d.id"):
        libs.append((f["sample_id"], f["participant_id"], f["uri"].split("/")[-2], f["assay_code"], f["platform_code"], f["uri"]))
    n = 0
    for sid, pid, lib, assay, platform, uri in libs:
        s = conn.execute("SELECT * FROM sample WHERE sample_id=?", (sid,)).fetchone()
        normal = s["specimen_code"] == "PB"
        rng = random.Random(f"{sid}|{lib}")
        m, x = _qc_values(rng, assay, platform, normal)
        checks = [{"check": c, "status": st} for c, st in _qc_checks(assay, platform)]
        surprise = _QC_SURPRISES.get((pid, lib))
        if surprise:
            c, st, obs, exp, why = surprise
            for ch in checks:
                if ch["check"] == c:
                    ch.update(status=st, observed=obs, expected=exp, reason=why)
            if c == "reads.coverage":
                m["mean_coverage"] = 14.2
            if c == "identity.contamination":
                x["contamination_pct"] = 3.1
        worst = next((st for st in ("fail", "warn") if any(ch["status"] == st for ch in checks)), "pass")
        reason = "; ".join(f"{ch['check']}: {ch.get('reason', '')}" for ch in checks if ch["status"] in ("fail", "warn")) or None
        seqqc.store(conn, s, {"workflow_id": "quick-qc", "workflow_version": "1.0.0-dev (demo values)",
                              "workflow_run_id": f"demo-quick-qc-{pid}",
                              "results": [{"library": lib, "path": uri, "qc_status": worst, "status_reason": reason, "metrics": {**m, **x},
                                           "checks": checks}]}, user="bot:igi")
        n += 1
    return n


# ---------------------------------------------------------------- public demonstration instance

DEMO_USERS = [  # username, display name, initials, role
    ("demo", "Demo Admin", "DA", "admin"),
    ("reviewer", "Second Reviewer", "SR", "user"),
    ("viewer", "Read-only Viewer", "RV", "viewer"),
    ("station", "Print station", "PRN", "printer"),
]


def reset_demo(conn, password):
    """Wipe the database and rebuild it with the demo accounts, the worked-example participant, three smaller ones and the two synthetic ones."""
    from .db import reset_db
    reset_db(conn)
    for username, name, initials, role in DEMO_USERS:
        create_user(conn, username, name, initials, password, role)
    _ensure_operators(conn, password)
    info = seed_demo(conn, "demo", second="reviewer")
    info["extra"] = seed_extra_participants(conn, "demo")
    info["extra"].update(seed_synthetic_participants(conn, "demo"))
    info["qc_results"] = seed_demo_seq_qc(conn)
    seed_demo_reagents(conn, "demo")
    conn.commit()
    return info
