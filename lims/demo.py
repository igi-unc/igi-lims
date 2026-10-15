"""One participant's worth of realistic demonstration data.

`flask seed-demo` adds a malignant-pleural-effusion participant with three
collections (two pleural taps and one blood draw) processed all the way to
sequencing libraries, a peptide eluate and data files, plus custody events
and two audited edits (one of them a second user's) so the flagged history
has something to show.

Everything goes through the same service functions as the web forms, so the
derivation rules, controlled vocabularies and audit log apply. The lists that
ship empty (SOPs, freezers, racks, boxes, lots, indexes, ...) get a few
plausible entries so the dropdowns are not all NA.
"""
from flask import g

from . import attributes, audit, ids
from . import samples as svc

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
]

EXTERNAL_ID = "MPE-021"


def _code(conn, cat, code):
    return conn.execute("SELECT 1 FROM code_list WHERE category=? AND code=? AND active=1", (cat, code)).fetchone()


def seed_demo(conn, username, second=None):
    """Create the main demo participant. Returns a summary dict. Raises if the data would violate the rules."""
    user = conn.execute("SELECT * FROM account WHERE username=? AND active=1", (username,)).fetchone()
    if user is None:
        raise ValueError(f"No active user {username!r}")
    g.user = dict(user)
    ini = user["initials"]
    if second is None:   # another account that makes one of the demo edits
        row = conn.execute("SELECT username FROM account WHERE active=1 AND role IN ('admin','user') AND username<>? "
                           "ORDER BY role, username", (username,)).fetchone()
        second = row["username"] if row else None

    for i, (cat, code, meaning) in enumerate(LIST_ENTRIES):
        conn.execute("INSERT OR IGNORE INTO code_list(category, code, meaning, active, sort_order) VALUES (?,?,?,1,?)",
                     (cat, code, meaning, 100 + i))
    for cat in ("cohort", "specimen", "fraction", "material"):
        pass  # core vocabularies come from seed.py

    # --- participant -------------------------------------------------------
    pid = _new_participant(conn, username, "MP", EXTERNAL_ID,
                           "Demonstration participant. Enrolled 2026-09-22, consent v3. Two pleural taps and one blood draw.")

    created = []
    tube, custody, data_file = _helpers(conn, username, ini, pid, created)

    bucket = "gs://igi-mp-trial-data"

    # =====================================================================
    # Collection A: first pleural tap, 2026-09-22
    # =====================================================================
    [pf1] = tube(participant=pid, collection_date="2026-09-22", specimen="PF", fraction="BLK", material="NAT",
                 when="2026-09-22T14:05", sop="SOP-001", qty=400, unit="mL", status="Available",
                 notes="Therapeutic thoracentesis, right side. Received from OR in a drainage bag, about 400 mL, turbid and slightly bloody.",
                 attrs={"container_type": "BAG", "time_collected": "2026-09-22T13:10", "time_received": "2026-09-22T14:05",
                        "transport_temp": "ambient", "appearance": "bloody", "hemolysis_grade": "mild", "qc_result": "pass"})
    custody(pf1, "2026-09-22T14:05", "CLINIC", ini, "STORE", notes="Receipt from OR; logged on arrival.")

    pfs = tube(pf1, count=4, when="2026-09-22T15:10", sop="SOP-001", qty=1.5, unit="mL", loc=("FRZ-A", "R1", "B01", "A1"),
               fraction="PFS", material="NAT", notes="Cell-free supernatant after 300 g spin; 0.45 um filtered.",
               attrs={"spin_protocol": "300G10", "filtered": "0.45", "appearance": "turbid", "qc_result": "pass"})
    cpu = tube(pf1, count=6, when="2026-09-22T17:45", sop="SOP-002", qty=1, unit="mL", loc=("LN2-1", "R1", "B02", "A1"),
               fraction="PFM", material="CPU", consumed=True,
               notes="Ficoll prep of the cell pellet; 6 vials at 8e6 cells/vial in CS10.",
               attrs={"isolation_method": "FICOLL", "rbc_lysis": "no", "cell_count": 48000000, "viability_pct": 92,
                      "count_method": "Countess", "cryo_medium": "CS10", "cells_per_vial": 8000000,
                      "freeze_method": "MRFROSTY", "storage_phase": "LN2 vapor", "qc_result": "pass"})

    # --- vial 1: single-cell RNA-seq -----------------------------------------
    [scs] = tube(cpu[0], when="2026-09-29T10:30", sop="SOP-003", qty=100, unit="uL", consumed=True,
                 fraction="PFM", material="SCS", notes="Thawed vial 1; dead-cell removal; loaded 10,000 cells on the Chromium.",
                 attrs={"dissociation_method": "NA", "viability_pct": 88, "concentration_cells_ul": 1000,
                        "dead_cell_removal": "yes", "hashtag": "NONE", "buffer": "PBS", "target_cells": 10000, "qc_result": "pass"})
    [lib_sc] = tube(scs, when="2026-09-30T16:00", sop="SOP-006", qty=20, unit="uL", loc=("FRZ-B", "R1", "B01", "A1"),
                    status="Depleted", consumed=True, fraction="PFM", material="LIB", notes="10x 5' v2 GEX + VDJ library; submitted to HTSF.",
                    attrs={"assay": "SCR", "prep_kit": "10X_5P_V2", "capture_kit": "NONE", "pcr_cycles": 12, "umi": "yes",
                           "rna_selection": "polyA", "stranded": "NA", "mean_fragment_bp": 450, "concentration_nm": 12.5,
                           "submission_id": "HTSF-26-0412", "input_cells": 10000, "index_id": "SI-TT-A1", "qc_result": "pass"})
    custody(lib_sc, "2026-10-01T09:30", ini, "HTSF", "SEQ", notes="Submission HTSF-26-0412; NovaSeq X 10B.")
    data_file(lib_sc, f"{bucket}/scrna/{lib_sc}/", "SCR", "NX-260410-0412", "d41d8cd98f00b204e9800998ecf8427e",
              "cellranger", "8.0.1", "GEX + VDJ fastq and cellranger multi output")

    # --- vial 2: EpCAM-enriched tumor cells -> HMW DNA, RNA, peptides --------
    cpl_t = tube(cpu[1], count=3, when="2026-10-03T13:20", sop="SOP-004", qty=1000000, unit="cells",
                 loc=("FRZ-A", "R2", "B01", "A1"), consumed=True, fraction="TUM", material="CPL",
                 notes="Thawed vial 2; EpCAM MACS positive fraction; three dry pellets at 1e6 cells.",
                 attrs={"enrichment_method": "EPCAM", "kit": "EPCAM_MACS", "kit_lot": "NA", "markers": "EPCAM",
                        "purity_pct": 86, "purity_method": "flow", "cell_count": 3200000, "viability_pct": 81,
                        "count_method": "flow", "wash_buffer": "PBS", "pellet_state": "dry", "intended_use": "DNA+RNA",
                        "qc_result": "pass"})
    [hmd] = tube(cpl_t[0], when="2026-10-06T11:20", sop="SOP-005", qty=40, unit="uL", loc=("FRZ-A", "R2", "B02", "B3"),
                 consumed=True, fraction="TUM", material="HMD", notes="Nanobind extraction for ONT long reads.",
                 attrs={"extraction_kit": "NANOBIND", "kit_lot": "LOT-24091", "concentration_ng_ul": 85.2,
                        "concentration_method": "Qubit", "a260_280": 1.84, "a260_230": 2.1, "volume_ul": 40, "din": 9.4,
                        "n50_kb": 62, "shearing": "NONE", "elution_buffer": "EB", "input_cells": 1000000, "qc_result": "pass"})
    [lib_ont] = tube(hmd, when="2026-10-07T15:40", sop="SOP-006", qty=12, unit="uL", loc=("FRZ-B", "R1", "B01", "A2"),
                     status="Depleted", fraction="TUM", material="LIB", notes="LSK114 ligation library, native barcode 01.",
                     attrs={"assay": "ONT", "prep_kit": "LSK114", "capture_kit": "NONE", "pcr_cycles": 0, "umi": "no",
                            "rna_selection": "NA", "stranded": "NA", "concentration_nm": 15.0, "input_ng": 1000,
                            "submission_id": "HTSF-26-0433", "index_id": "NB01", "qc_result": "pass"})
    custody(hmd, "2026-10-07T09:00", ini, "HTSF", "SEQ", notes="Remaining 20 uL retained at HTSF for a second flow cell if needed.")
    custody(lib_ont, "2026-10-08T09:15", ini, "HTSF", "SEQ", notes="Submission HTSF-26-0433; PromethION.")
    data_file(lib_ont, f"{bucket}/ont/{lib_ont}/", "ONT", "PAW12345-260410", "9e107d9d372bb6826bd81d3542a419d6",
              "dorado", "0.9.1", "pod5 + basecalled BAM, 5mC/5hmC")

    [rna_t] = tube(cpl_t[1], when="2026-10-06T12:05", sop="SOP-005", qty=30, unit="uL", loc=("FRZ-A", "R2", "B02", "B4"),
                   consumed=True, fraction="TUM", material="RNA", notes="RNeasy with on-column DNase.",
                   attrs={"extraction_kit": "RNEASY", "kit_lot": "LOT-7A113", "concentration_ng_ul": 120.0,
                          "concentration_method": "Qubit", "a260_280": 2.02, "a260_230": 1.9, "volume_ul": 30, "rin": 8.7,
                          "dv200": 91, "dnase_treated": "yes", "elution_buffer": "H2O", "input_cells": 1000000, "qc_result": "pass"})
    [lib_rna] = tube(rna_t, when="2026-10-08T14:30", sop="SOP-006", qty=15, unit="uL", loc=("FRZ-B", "R1", "B01", "A3"),
                     status="Depleted", fraction="TUM", material="LIB", notes="Stranded polyA RNA-seq library.",
                     attrs={"assay": "RSQ", "prep_kit": "KAPA_HYPER", "capture_kit": "NONE", "pcr_cycles": 10, "umi": "no",
                            "rna_selection": "polyA", "stranded": "yes", "mean_fragment_bp": 350, "concentration_nm": 8.2,
                            "submission_id": "HTSF-26-0433", "kit_lot": "LOT-KH338", "input_ng": 100, "index_id": "UDI0012",
                            "qc_result": "pass"})
    custody(lib_rna, "2026-10-08T09:15", ini, "HTSF", "SEQ", notes="Submission HTSF-26-0433; NovaSeq X.")
    data_file(lib_rna, f"{bucket}/rnaseq/{lib_rna}/", "RSQ", "NX-260412-0433", "a3f1c0b2e4d5968778695a4b3c2d1e0f",
              "nf-core/rnaseq", "3.14.0", "paired-end fastq + STAR/salmon output")

    [pep] = tube(cpl_t[2], when="2026-10-09T17:30", sop="SOP-007", qty=20, unit="uL", loc=("FRZ-A", "R2", "B03", "A1"),
                 status="In use", consumed=True, fraction="TUM", material="PEP",
                 notes="HLA class I immunoprecipitation (W6/32); eluate cleaned on C18, dried and resuspended.",
                 attrs={"hla_class": "I", "ip_antibody": "W632", "antibody_lot": "W632-L0424", "input_cells": 1000000,
                        "bead_type": "PROTA", "lysis_buffer": "PBS", "elution": "TFA01", "cleanup": "C18",
                        "offline_fractions": 1, "resuspension_ul": 20, "target_instrument": "EXPLORIS480", "qc_result": "not assessed"})
    custody(pep, "2026-10-10T10:00", ini, "MSCORE", "IP", notes="Queued on the Exploris 480.")
    data_file(pep, f"{bucket}/immunopeptidomics/{pep}/", "IPX", "EXP480-261011-07", "0cc175b9c0f1b6a831c399e269772661",
              "FragPipe", "22.0", "raw + FragPipe nonspecific HLA search")

    # --- vial 3: CD8 T cells -> RNA -> TCR library --------------------------
    [cpl_cd8] = tube(cpu[2], when="2026-10-03T15:00", sop="SOP-004", qty=2000000, unit="cells", loc=("FRZ-A", "R2", "B01", "A4"),
                     consumed=True, fraction="CD8", material="CPL", notes="Thawed vial 3; EasySep CD8 negative selection; dry pellet.",
                     attrs={"selection_mode": "negative", "kit": "CD8_NEG", "kit_lot": "NA", "purity_pct": 95,
                            "cell_count": 2100000, "viability_pct": 90, "count_method": "flow", "wash_buffer": "PBS",
                            "pellet_state": "dry", "intended_use": "RNA", "qc_result": "pass"})
    [rna_cd8] = tube(cpl_cd8, when="2026-10-06T12:40", sop="SOP-005", qty=25, unit="uL", loc=("FRZ-A", "R2", "B02", "B5"),
                     consumed=True, fraction="CD8", material="RNA", notes="RNeasy; for TCR-seq.",
                     attrs={"extraction_kit": "RNEASY", "kit_lot": "LOT-7A113", "concentration_ng_ul": 38.0,
                            "concentration_method": "Qubit", "a260_280": 2.0, "a260_230": 1.8, "volume_ul": 25, "rin": 9.1,
                            "dv200": 94, "dnase_treated": "yes", "elution_buffer": "H2O", "input_cells": 2000000, "qc_result": "pass"})
    [lib_tcr] = tube(rna_cd8, when="2026-10-08T16:10", sop="SOP-006", qty=15, unit="uL", loc=("FRZ-B", "R1", "B01", "A4"),
                     status="Depleted", fraction="CD8", material="LIB", notes="SMARTer TCR a/b profiling library.",
                     attrs={"assay": "TCR", "prep_kit": "SMARTER", "capture_kit": "NONE", "pcr_cycles": 20, "umi": "yes",
                            "rna_selection": "NA", "stranded": "NA", "mean_fragment_bp": 600, "concentration_nm": 4.1,
                            "submission_id": "HTSF-26-0433", "input_ng": 50, "index_id": "UDI0013", "qc_result": "borderline"})
    custody(lib_tcr, "2026-10-08T09:15", ini, "HTSF", "SEQ", notes="Submission HTSF-26-0433; MiSeq.")
    data_file(lib_tcr, f"{bucket}/tcr/{lib_tcr}/", "TCR", "MS-260413-0433", "92eb5ffee6ae2fec3ad71c777531578f",
              "MiXCR", "4.7.0", "fastq + clonotype tables")

    # =====================================================================
    # Collection B: peripheral blood, same day
    # =====================================================================
    [pb1] = tube(participant=pid, collection_date="2026-09-22", specimen="PB", fraction="BLK", material="NAT",
                 when="2026-09-22T14:05", sop="SOP-008", qty=20, unit="mL",
                 notes="Two 10 mL EDTA tubes drawn at the time of the tap.",
                 attrs={"container_type": "EDTA", "time_collected": "2026-09-22T12:50", "time_received": "2026-09-22T14:05",
                        "transport_temp": "ambient", "appearance": "clear", "hemolysis_grade": "none", "qc_result": "pass"})
    custody(pb1, "2026-09-22T14:05", "CLINIC", ini, "STORE", notes="Receipt with the pleural fluid.")
    pla = tube(pb1, count=4, when="2026-09-22T15:30", sop="SOP-008", qty=1, unit="mL", loc=("FRZ-A", "R3", "B01", "A1"),
               fraction="PLA", material="NAT", notes="Double-spun plasma.",
               attrs={"spin_protocol": "2000G10", "time_to_spin_min": 45, "hemolysis_grade": "none", "qc_result": "pass"})
    pbm = tube(pb1, count=4, when="2026-09-22T18:10", sop="SOP-002", qty=1, unit="mL", loc=("LN2-1", "R1", "B03", "A1"),
               fraction="PBM", material="CPU", consumed=True, notes="SepMate PBMC; 4 vials at 5e6 cells/vial.",
               attrs={"isolation_method": "SEPMATE", "rbc_lysis": "no", "cell_count": 21000000, "viability_pct": 96,
                      "count_method": "Countess", "cryo_medium": "CS10", "cells_per_vial": 5000000,
                      "freeze_method": "MRFROSTY", "storage_phase": "LN2 vapor", "qc_result": "pass"})

    [cfd] = tube(pla[0], when="2026-10-06T14:00", sop="SOP-005", qty=50, unit="uL", loc=("FRZ-A", "R3", "B02", "A1"),
                 consumed=True, fraction="PLA", material="CFD", notes="QIAamp ccfDNA from 1 mL plasma.",
                 attrs={"plasma_input_ml": 1.0, "extraction_kit": "CCFDNA", "kit_lot": "LOT-CF0910", "concentration_ng_ul": 0.8,
                        "concentration_method": "TapeStation", "total_yield_ng": 40, "cfdna_peak_bp": 167,
                        "hmw_contamination_pct": 5, "volume_ul": 50, "elution_buffer": "EB", "qc_result": "pass"})
    [lib_cf] = tube(cfd, when="2026-10-08T15:20", sop="SOP-006", qty=15, unit="uL", loc=("FRZ-B", "R1", "B01", "A5"),
                    status="Depleted", fraction="PLA", material="LIB", notes="Low-pass WGS library from cfDNA.",
                    attrs={"assay": "WGS", "prep_kit": "KAPA_HYPER", "capture_kit": "NONE", "pcr_cycles": 6, "umi": "yes",
                           "rna_selection": "NA", "stranded": "NA", "mean_fragment_bp": 320, "concentration_nm": 5.1,
                           "submission_id": "HTSF-26-0433", "kit_lot": "LOT-KH338", "input_ng": 20, "index_id": "UDI0014",
                           "qc_result": "pass"})
    custody(lib_cf, "2026-10-08T09:15", ini, "HTSF", "SEQ", notes="Submission HTSF-26-0433; NovaSeq X, 1x coverage.")
    data_file(lib_cf, f"{bucket}/cfdna/{lib_cf}/", "WGS", "NX-260412-0433", "e1671797c52e15f763380b45e841ec32",
              "nf-core/sarek", "3.4.4", "fastq + ichorCNA")

    [gdna] = tube(pbm[0], when="2026-10-06T14:40", sop="SOP-005", qty=100, unit="uL", loc=("FRZ-A", "R3", "B02", "A2"),
                  consumed=True, fraction="PBM", material="DNA", notes="Germline DNA for the matched-normal exome.",
                  attrs={"extraction_kit": "DNEASY", "kit_lot": "LOT-DN2206", "concentration_ng_ul": 45.0,
                         "concentration_method": "Qubit", "a260_280": 1.86, "a260_230": 2.05, "volume_ul": 100, "din": 8.9,
                         "elution_buffer": "EB", "input_cells": 5000000, "qc_result": "pass"})
    [lib_wes] = tube(gdna, when="2026-10-08T15:50", sop="SOP-006", qty=15, unit="uL", loc=("FRZ-B", "R1", "B01", "A6"),
                     status="Depleted", fraction="PBM", material="LIB", notes="Germline exome, xGen v2 capture.",
                     attrs={"assay": "WES", "prep_kit": "ILMN_DNA", "capture_kit": "XGEN_V2", "pcr_cycles": 8, "umi": "no",
                            "rna_selection": "NA", "stranded": "NA", "mean_fragment_bp": 300, "concentration_nm": 6.4,
                            "submission_id": "HTSF-26-0433", "input_ng": 200, "index_id": "UDI0014", "qc_result": "pass"})
    custody(lib_wes, "2026-10-08T09:15", ini, "HTSF", "SEQ", notes="Submission HTSF-26-0433; NovaSeq X.")
    data_file(lib_wes, f"{bucket}/wes/{lib_wes}/", "WES", "NX-260412-0433", "8277e0910d750195b448797616e091ad",
              "nf-core/sarek", "3.4.4", "fastq + germline VCF")

    # =====================================================================
    # Collection C: second pleural tap at progression, 2026-10-06
    # =====================================================================
    [pf2] = tube(participant=pid, collection_date="2026-10-06", specimen="PF", fraction="BLK", material="NAT",
                 when="2026-10-06T16:20", sop="SOP-001", qty=250, unit="mL",
                 notes="Second tap at progression. Less bloody than the first.",
                 attrs={"container_type": "BAG", "time_collected": "2026-10-06T15:05", "time_received": "2026-10-06T16:20",
                        "transport_temp": "ambient", "appearance": "turbid", "hemolysis_grade": "none", "qc_result": "pass"})
    custody(pf2, "2026-10-06T16:20", "CLINIC", ini, "STORE")
    tube(pf2, count=2, when="2026-10-06T17:00", sop="SOP-001", qty=1.5, unit="mL", loc=("FRZ-A", "R1", "B01", "A5"),
         fraction="PFS", material="NAT", attrs={"spin_protocol": "300G10", "filtered": "0.45", "appearance": "turbid", "qc_result": "pass"})
    tube(pf2, count=3, when="2026-10-06T19:30", sop="SOP-002", qty=1, unit="mL", loc=("LN2-1", "R1", "B02", "A7"),
         fraction="PFM", material="CPU", consumed=True, notes="Ficoll prep; 3 vials at 6e6 cells/vial.",
         attrs={"isolation_method": "FICOLL", "rbc_lysis": "no", "cell_count": 18000000, "viability_pct": 89,
                "count_method": "Countess", "cryo_medium": "CS10", "cells_per_vial": 6000000,
                "freeze_method": "MRFROSTY", "storage_phase": "LN2 vapor", "qc_result": "pass"})

    # =====================================================================
    # Audited edits: one by the seeding user, one by a second account
    # =====================================================================
    edits = []
    svc.update_sample(conn, pfs[0], {"quantity": 1.0},
                      reason="Took 0.5 mL of supernatant for the cytokine panel (not tracked as a tube).")
    edits.append(pfs[0])
    if second:
        me = g.user
        g.user = dict(conn.execute("SELECT * FROM account WHERE username=?", (second,)).fetchone())
        svc.update_sample(conn, cpu[4], {"box": "B04", "position": "A1"},
                          reason="Vial moved to box B04 during the LN2-1 reorganisation on 2026-10-12.")
        g.user = me
        edits.append(cpu[4])

    return {"participant": pid, "external_id": EXTERNAL_ID, "tubes": len(created), "roots": [pf1, pb1, pf2],
            "edits": edits, "second": second}


def _helpers(conn, username, ini, pid, created):
    """Closures that create tubes, custody events and data files for one participant through the service layer."""

    def tube(parent=None, *, count=1, when, sop, qty, unit, loc=("NA", "NA", "NA", "NA"), status="Available",
             notes="NA", attrs=None, consumed=False, biobank="IH", **comp):
        payload = {"count": count, "created_datetime": when, "created_by": ini, "sop_code": sop,
                   "biobank_source": biobank, "quantity": qty, "unit": unit,
                   "freezer": loc[0], "rack": loc[1], "box": loc[2], "position": loc[3],
                   "status": status, "notes": notes, "attributes": attrs or {}, "parent_consumed": consumed}
        if parent:
            payload["parent_id"] = parent
        else:
            payload["participant"] = pid
        payload.update(comp)
        made, violations = svc.create_samples(conn, payload)
        if violations:
            raise ValueError(f"Demo data violates rules for {comp}: {violations}")
        created.extend(made)
        return made

    def custody(sid, when, frm, to, purpose, condition="good", notes=None, set_status=None):
        cur = conn.execute(
            "INSERT INTO custody_event(sample_id, event_datetime, from_party, to_party, purpose, condition_on_receipt, "
            "initials, notes, recorded_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, when, frm, to, purpose, condition, ini, notes, username))
        audit.log(conn, "custody_event", cur.lastrowid, "insert",
                  after={"sample_id": sid, "event_datetime": when, "from_party": frm, "to_party": to, "purpose": purpose})
        if set_status:
            svc.update_sample(conn, sid, {"status": set_status})

    def data_file(sid, uri, assay, run_id, md5, pipeline, version, notes=None):
        f = {"uri": uri, "assay_code": assay, "run_id": run_id, "checksum_md5": md5, "pipeline": pipeline,
             "pipeline_version": version, "notes": notes}
        cur = conn.execute(
            "INSERT INTO data_file(sample_id, uri, assay_code, run_id, checksum_md5, pipeline, pipeline_version, notes, recorded_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, uri, assay, run_id, md5, pipeline, version, notes, username))
        audit.log(conn, "data_file", cur.lastrowid, "insert", after={"sample_id": sid, **f})

    return tube, custody, data_file


def _new_participant(conn, username, cohort, external_id, notes):
    existing = conn.execute("SELECT participant_id FROM participant WHERE external_participant_id=?", (external_id,)).fetchone()
    if existing:
        raise ValueError(f"Demo participant already exists as {existing['participant_id']} (site ID {external_id})")
    pid = ids.new_participant_code(conn)
    prow = {"participant_id": pid, "cohort_code": cohort, "external_participant_id": external_id, "site_code": "UNC",
            "notes": notes, "created_by": username}
    conn.execute("INSERT INTO participant(participant_id, cohort_code, external_participant_id, site_code, notes, created_by) "
                 "VALUES (:participant_id, :cohort_code, :external_participant_id, :site_code, :notes, :created_by)", prow)
    audit.log(conn, "participant", pid, "insert", after=prow)
    return pid


# Smaller participants in the other cohorts, so the picker and the trees have something to compare.
EXTRA_PARTICIPANTS = [
    ("AM", "AML-007", "Demonstration participant. Diagnostic marrow and blood at presentation; marrow shipped for a collaborator's assay."),
    ("TN", "TNBC-103", "Demonstration participant. Core biopsy before neoadjuvant therapy: FFPE and OCT blocks plus a blood draw."),
    ("NC", "NUT-002", "Demonstration participant. Lymph node resection with snap-frozen tumour; blood received, not yet processed."),
]


def seed_extra_participants(conn, username):
    """Three shorter participants (AML, TNBC, NUT carcinoma). Returns {participant_id: tube_count}."""
    user = conn.execute("SELECT * FROM account WHERE username=? AND active=1", (username,)).fetchone()
    if user is None:
        raise ValueError(f"No active user {username!r}")
    g.user = dict(user)
    ini = user["initials"]
    conn.execute("INSERT OR IGNORE INTO code_list(category, code, meaning, active, sort_order) VALUES (?,?,?,1,?)",
                 ("party", "COLLAB", "Collaborating laboratory (external)", 199))
    for i, (cat, code, meaning) in enumerate(LIST_ENTRIES):
        conn.execute("INSERT OR IGNORE INTO code_list(category, code, meaning, active, sort_order) VALUES (?,?,?,1,?)",
                     (cat, code, meaning, 100 + i))
    out = {}
    bucket = "gs://igi-mp-trial-data"

    # --- AML: bone marrow aspirate + blood, 2026-09-30 -------------------------
    cohort, ext, note = EXTRA_PARTICIPANTS[0]
    pid = _new_participant(conn, username, cohort, ext, note)
    created = []
    tube, custody, data_file = _helpers(conn, username, ini, pid, created)
    [bm] = tube(participant=pid, collection_date="2026-09-30", specimen="BM", fraction="BLK", material="NAT",
                when="2026-09-30T11:40", sop="SOP-008", qty=8, unit="mL", notes="Diagnostic marrow aspirate, 8 mL in heparin. Fully used for the mononuclear prep.",
                attrs={"container_type": "HEP", "time_collected": "2026-09-30T10:55", "time_received": "2026-09-30T11:40",
                       "transport_temp": "ambient", "appearance": "bloody", "hemolysis_grade": "none", "qc_result": "pass"})
    custody(bm, "2026-09-30T11:40", "CLINIC", ini, "STORE", notes="Receipt from the hematology clinic.")
    blasts = tube(bm, count=5, when="2026-09-30T15:30", sop="SOP-002", qty=1, unit="mL", loc=("LN2-1", "R2", "B01", "A1"),
                  fraction="TUM", material="CPU", consumed=True, notes="Ficoll mononuclear cells, 85% blasts by morphology; 5 vials.",
                  attrs={"enrichment_method": "NONE", "kit": "NA", "kit_lot": "NA", "markers": "NA", "purity_pct": 85,
                         "purity_method": "cytology", "cell_count": 50000000, "viability_pct": 94, "count_method": "Countess",
                         "cryo_medium": "FBS_DMSO", "cells_per_vial": 10000000, "freeze_method": "MRFROSTY",
                         "storage_phase": "LN2 vapor", "qc_result": "pass"})
    [dna] = tube(blasts[0], when="2026-10-02T10:15", sop="SOP-005", qty=60, unit="uL", loc=("FRZ-A", "R4", "B01", "A1"),
                 consumed=True, fraction="TUM", material="DNA", notes="DNeasy from vial 1 for the diagnostic exome.",
                 attrs={"extraction_kit": "DNEASY", "kit_lot": "LOT-DN2206", "concentration_ng_ul": 110.0,
                        "concentration_method": "Qubit", "a260_280": 1.85, "a260_230": 2.2, "volume_ul": 60, "din": 9.1,
                        "elution_buffer": "EB", "input_cells": 10000000, "qc_result": "pass"})
    [lib] = tube(dna, when="2026-10-03T16:00", sop="SOP-006", qty=15, unit="uL", loc=("FRZ-B", "R1", "B02", "A1"),
                 status="Depleted", fraction="TUM", material="LIB", notes="Tumour exome, xGen v2 capture.",
                 attrs={"assay": "WES", "prep_kit": "ILMN_DNA", "capture_kit": "XGEN_V2", "pcr_cycles": 8, "umi": "no",
                        "rna_selection": "NA", "stranded": "NA", "mean_fragment_bp": 310, "concentration_nm": 7.0,
                        "submission_id": "HTSF-26-0433", "input_ng": 200, "index_id": "UDI0012", "qc_result": "pass"})
    custody(lib, "2026-10-08T09:15", ini, "HTSF", "SEQ", notes="Submission HTSF-26-0433; NovaSeq X.")
    data_file(lib, f"{bucket}/wes/{lib}/", "WES", "NX-260412-0433", "45c48cce2e2d7fbdea1afc51c7c6ad26",
              "nf-core/sarek", "3.4.4", "fastq + somatic VCF (tumour only)")
    # one vial shipped to a collaborator, one destroyed after a thaw
    custody(blasts[1], "2026-10-09T14:00", ini, "COLLAB", "SHIP", notes="Dry-shipper to the collaborating lab for the ex vivo drug screen.",
            set_status="Shipped")
    svc.update_sample(conn, blasts[2], {"status": "Destroyed"},
                      reason="Vial found thawed in the LN2-1 rack during the 2026-10-12 inventory; discarded per SOP-002.")
    [pb] = tube(participant=pid, collection_date="2026-09-30", specimen="PB", fraction="BLK", material="NAT",
                when="2026-09-30T11:40", sop="SOP-008", qty=10, unit="mL", notes="One 10 mL EDTA tube drawn with the marrow.",
                attrs={"container_type": "EDTA", "time_collected": "2026-09-30T10:50", "time_received": "2026-09-30T11:40",
                       "transport_temp": "ambient", "appearance": "clear", "hemolysis_grade": "none", "qc_result": "pass"})
    custody(pb, "2026-09-30T11:40", "CLINIC", ini, "STORE")
    tube(pb, count=3, when="2026-09-30T13:00", sop="SOP-008", qty=1, unit="mL", loc=("FRZ-A", "R3", "B03", "A1"),
         fraction="PLA", material="NAT", notes="Double-spun plasma.",
         attrs={"spin_protocol": "2000G10", "time_to_spin_min": 60, "hemolysis_grade": "none", "qc_result": "pass"})
    tube(pb, count=2, when="2026-09-30T16:10", sop="SOP-002", qty=1, unit="mL", loc=("LN2-1", "R2", "B01", "B1"),
         fraction="PBM", material="CPU", consumed=True, notes="PBMC as the germline comparator; 2 vials.",
         attrs={"isolation_method": "FICOLL", "rbc_lysis": "no", "cell_count": 9000000, "viability_pct": 95,
                "count_method": "Countess", "cryo_medium": "CS10", "cells_per_vial": 4500000,
                "freeze_method": "MRFROSTY", "storage_phase": "LN2 vapor", "qc_result": "pass"})
    out[pid] = len(created)

    # --- TNBC: core biopsy -> FFPE + OCT, blood -> PBMC in use ---------------
    cohort, ext, note = EXTRA_PARTICIPANTS[1]
    pid = _new_participant(conn, username, cohort, ext, note)
    created = []
    tube, custody, data_file = _helpers(conn, username, ini, pid, created)
    [tu] = tube(participant=pid, collection_date="2026-10-01", specimen="TU", fraction="BLK", material="NAT",
                when="2026-10-01T09:50", sop="SOP-001", qty=4, unit="NA", notes="Four ultrasound-guided 14G cores from the primary breast lesion. Two to pathology (FFPE), two frozen in OCT.",
                attrs={"container_type": "PLAIN", "time_collected": "2026-10-01T09:20", "time_received": "2026-10-01T09:50",
                       "transport_temp": "ice", "appearance": "NA", "hemolysis_grade": "NA", "qc_result": "pass"})
    custody(tu, "2026-10-01T09:50", "CLINIC", ini, "STORE", notes="Cores received on ice from radiology.")
    [ffpe] = tube(tu, when="2026-10-02T12:00", sop="SOP-001", qty=1, unit="NA", loc=("NA", "NA", "NA", "NA"),
                  fraction="TUM", material="FFP", notes="FFPE block from cores 1-2 (pathology accession in Notes of the data file). Stored at room temperature in the pathology archive.",
                  attrs={"block_id": "NA", "fixation_time_h": 18, "block_age_years": 0, "sections_count": 0,
                         "section_thickness_um": 5, "tumor_pct": 70, "macrodissected": "no", "qc_result": "pass"})
    [oct_] = tube(tu, when="2026-10-01T10:10", sop="SOP-001", qty=1, unit="NA", loc=("FRZ-A", "R4", "B02", "A1"),
                  consumed=True, fraction="TUM", material="OCT", notes="Cores 3-4 embedded in OCT and frozen on dry ice.",
                  attrs={"tissue_mass_mg": 30, "block_id": "NA", "sections_cut": 0, "tumor_pct": 65, "qc_result": "pass"})
    [rna] = tube(ffpe, when="2026-10-07T11:30", sop="SOP-005", qty=25, unit="uL", loc=("FRZ-A", "R4", "B03", "A1"),
                 fraction="TUM", material="RNA", notes="AllPrep FFPE from 6 x 10 um sections.",
                 attrs={"extraction_kit": "ALLPREP", "kit_lot": "NA", "input_mass_mg": 0, "concentration_ng_ul": 22.0,
                        "concentration_method": "Qubit", "a260_280": 1.95, "a260_230": 1.6, "volume_ul": 25, "rin": 2.4,
                        "dv200": 48, "dnase_treated": "yes", "elution_buffer": "H2O", "qc_result": "borderline"})
    [lib] = tube(rna, when="2026-10-09T15:00", sop="SOP-006", qty=15, unit="uL", loc=("FRZ-B", "R1", "B02", "A2"),
                 fraction="TUM", material="LIB", notes="rRNA-depleted RNA-seq library from FFPE RNA; awaiting submission.",
                 attrs={"assay": "RSQ", "prep_kit": "KAPA_HYPER", "capture_kit": "NONE", "pcr_cycles": 14, "umi": "no",
                        "rna_selection": "rRNA depletion", "stranded": "yes", "mean_fragment_bp": 280, "concentration_nm": 3.9,
                        "submission_id": "NA", "kit_lot": "LOT-KH338", "input_ng": 100, "index_id": "UDI0013", "qc_result": "borderline"})
    [pb] = tube(participant=pid, collection_date="2026-10-01", specimen="PB", fraction="BLK", material="NAT",
                when="2026-10-01T09:50", sop="SOP-008", qty=10, unit="mL", notes="One 10 mL EDTA tube drawn before the biopsy.",
                attrs={"container_type": "EDTA", "time_collected": "2026-10-01T09:05", "time_received": "2026-10-01T09:50",
                       "transport_temp": "ambient", "appearance": "clear", "hemolysis_grade": "mild", "qc_result": "pass"})
    custody(pb, "2026-10-01T09:50", "CLINIC", ini, "STORE")
    tube(pb, count=2, when="2026-10-01T11:00", sop="SOP-008", qty=1, unit="mL", loc=("FRZ-A", "R3", "B03", "B1"),
         fraction="PLA", material="NAT", attrs={"spin_protocol": "2000G10", "time_to_spin_min": 50, "hemolysis_grade": "mild", "qc_result": "pass"})
    pbm = tube(pb, count=2, when="2026-10-01T14:20", sop="SOP-002", qty=1, unit="mL", loc=("LN2-1", "R2", "B02", "A1"),
               fraction="PBM", material="CPU", consumed=True, notes="SepMate PBMC; 2 vials.",
               attrs={"isolation_method": "SEPMATE", "rbc_lysis": "no", "cell_count": 8000000, "viability_pct": 97,
                      "count_method": "Countess", "cryo_medium": "CS10", "cells_per_vial": 4000000,
                      "freeze_method": "MRFROSTY", "storage_phase": "LN2 vapor", "qc_result": "pass"})
    svc.update_sample(conn, pbm[0], {"status": "In use"}, reason="Checked out for the germline DNA extraction.")
    out[pid] = len(created)

    # --- NUT carcinoma: lymph node resection, snap frozen -> HMW RNA -> ONT; blood untouched ---
    cohort, ext, note = EXTRA_PARTICIPANTS[2]
    pid = _new_participant(conn, username, cohort, ext, note)
    created = []
    tube, custody, data_file = _helpers(conn, username, ini, pid, created)
    [ln] = tube(participant=pid, collection_date="2026-10-08", specimen="LN", fraction="BLK", material="NAT",
                when="2026-10-08T13:30", sop="SOP-001", qty=1200, unit="mg", notes="Cervical lymph node from the resection; 1.2 g received fresh from the OR in saline.",
                attrs={"container_type": "PLAIN", "time_collected": "2026-10-08T12:45", "time_received": "2026-10-08T13:30",
                       "transport_temp": "ice", "appearance": "NA", "hemolysis_grade": "NA", "qc_result": "pass"})
    custody(ln, "2026-10-08T13:30", "CLINIC", ini, "STORE", notes="Receipt from the OR; divided within 20 min.")
    snf = tube(ln, count=4, when="2026-10-08T13:50", sop="SOP-001", qty=200, unit="mg", loc=("FRZ-A", "R4", "B04", "A1"),
               fraction="TUM", material="SNF", consumed=True, notes="Four ~200 mg pieces snap frozen in isopentane; remainder to pathology.",
               attrs={"tissue_mass_mg": 200, "ischemia_time_min": 55, "freeze_method": "ISOPENTANE", "tumor_pct": 80,
                      "necrosis_pct": 10, "qc_result": "pass"})
    [hmr] = tube(snf[0], when="2026-10-10T10:00", sop="SOP-005", qty=50, unit="uL", loc=("FRZ-A", "R4", "B03", "B1"),
                 consumed=True, fraction="TUM", material="HMR", notes="TRIzol RNA from piece 1 for direct-RNA nanopore.",
                 attrs={"extraction_kit": "TRIZOL", "kit_lot": "NA", "input_mass_mg": 200, "concentration_ng_ul": 310.0,
                        "concentration_method": "NanoDrop", "a260_280": 2.05, "a260_230": 2.1, "volume_ul": 50, "rin": 9.0,
                        "dv200": 95, "dnase_treated": "yes", "elution_buffer": "H2O", "qc_result": "pass"})
    [lib] = tube(hmr, when="2026-10-13T14:30", sop="SOP-006", qty=30, unit="uL", loc=("FRZ-B", "R1", "B02", "A3"),
                 status="In use", fraction="TUM", material="LIB", notes="Direct RNA library; loading on the PromethION this week.",
                 attrs={"assay": "ONT", "prep_kit": "NA", "capture_kit": "NONE", "pcr_cycles": 0, "umi": "no",
                        "rna_selection": "polyA", "stranded": "yes", "concentration_nm": 20.0, "input_ng": 500,
                        "submission_id": "NA", "index_id": "NA", "qc_result": "not assessed"})
    [pb] = tube(participant=pid, collection_date="2026-10-08", specimen="PB", fraction="BLK", material="NAT",
                when="2026-10-08T13:30", sop="SOP-008", qty=10, unit="mL", loc=("FRZ-A", "R3", "B04", "A1"),
                notes="One 10 mL EDTA tube from the pre-op draw; whole blood held at 4 C, not yet processed.",
                attrs={"container_type": "EDTA", "time_collected": "2026-10-08T07:30", "time_received": "2026-10-08T13:30",
                       "transport_temp": "4C", "appearance": "clear", "hemolysis_grade": "none", "qc_result": "not assessed"})
    custody(pb, "2026-10-08T13:30", "CLINIC", ini, "STORE")
    out[pid] = len(created)
    return out


# ---------------------------------------------------------------- public demonstration instance

DEMO_USERS = [  # username, display name, initials, role
    ("demo", "Demo Admin", "DA", "admin"),
    ("reviewer", "Second Reviewer", "SR", "user"),
    ("viewer", "Read-only Viewer", "RV", "viewer"),
]


def reset_demo(conn, password):
    """Wipe the database and rebuild it with the demo accounts, the main demo participant and three smaller ones."""
    from .db import reset_db
    from .auth import create_user
    reset_db(conn)
    for username, name, initials, role in DEMO_USERS:
        create_user(conn, username, name, initials, password, role)
    info = seed_demo(conn, "demo", second="reviewer")
    info["extra"] = seed_extra_participants(conn, "demo")
    conn.commit()
    return info
