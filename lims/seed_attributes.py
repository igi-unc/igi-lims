"""Initial per-fraction / per-material metadata fields. Edit later under Admin > Fields."""

# (scope, code, key, label, type, unit, choices, required)
ATTRS = []


def _a(scope, code, key, label, type="text", unit=None, choices=None, required=0):
    ATTRS.append((scope, code, key, label, type, unit, choices, required))


def _many(scope, codes, fields):
    for c in codes:
        for f in fields:
            _a(scope, c, *f)


YN = "yes|no"
# field tuples: (key, label, type, unit, choices, required)
CELLS = [("cell_count", "Cell count", "number", "cells"), ("viability_pct", "Viability", "number", "%"),
         ("count_method", "Counting method", "choice", None, "trypan blue|AO/PI|Countess|hemocytometer|flow|other")]
SPIN = [("spin_protocol", "Spin protocol (speed, time, temp)", "text")]
KIT = [("kit", "Kit / method", "text"), ("kit_lot", "Kit lot", "text")]
PURITY = [("purity_pct", "Purity estimate", "number", "%"), ("purity_method", "Purity method", "choice", None, "flow|cytology|not assessed")]

# ---- all tubes
_a("all", "*", "qc_result", "QC result", "choice", None, "pass|fail|borderline|not assessed")
_a("all", "*", "qc_notes", "QC notes", "text")

# ---- fractions
_many("fraction", ["BLK"], [("container_type", "Container / tube type", "choice", None, "EDTA|heparin|Streck|ACD|plain|bag|other|NA"),
                            ("time_collected", "Time collected", "text"), ("time_received", "Time received", "text"),
                            ("transport_temp", "Transport temperature", "choice", None, "ambient|4C|ice|NA"),
                            ("appearance", "Appearance", "choice", None, "clear|bloody|turbid|NA"),
                            ("hemolysis_grade", "Hemolysis grade", "choice", None, "none|mild|moderate|severe|NA")])
_many("fraction", ["PLA"], SPIN + [("time_to_spin_min", "Time from draw to spin", "number", "min"), ("hemolysis_grade", "Hemolysis grade", "choice", None, "none|mild|moderate|severe|NA")])
_many("fraction", ["SER"], [("clot_time_min", "Clot time", "number", "min")] + SPIN + [("hemolysis_grade", "Hemolysis grade", "choice", None, "none|mild|moderate|severe|NA")])
_many("fraction", ["BFC"], SPIN + [("rbc_lysis", "RBC lysis done", "choice", None, YN)])
_many("fraction", ["PFS"], SPIN + [("filtered", "Filtered (pore size)", "text"), ("appearance", "Appearance", "choice", None, "clear|bloody|turbid|NA")])
_many("fraction", ["PBM", "PFM"], [("isolation_method", "Isolation method", "choice", None, "Ficoll|SepMate|Lymphoprep|other"), ("rbc_lysis", "RBC lysis done", "choice", None, YN)] + CELLS)
_many("fraction", ["TUM"], [("enrichment_method", "Enrichment method", "choice", None, "CD45 depletion|EpCAM positive selection|FACS|MACS|none|other")] + KIT + [("markers", "Markers used", "text")] + PURITY + CELLS)
_many("fraction", ["IMM"], [("enrichment_method", "Enrichment method", "choice", None, "CD45 positive selection|buffy coat|FACS|other")] + KIT + PURITY + CELLS)
_many("fraction", ["TTC"], [("selection_method", "Selection method", "choice", None, "pan-T negative|CD3 positive|FACS|other")] + KIT + [("purity_pct", "Purity (% CD3+)", "number", "%")] + CELLS)
_many("fraction", ["CD8", "CD4"], [("selection_mode", "Selection mode", "choice", None, "positive|negative|FACS")] + KIT + [("purity_pct", "Purity by flow", "number", "%"), ("flow_file", "Flow panel / FCS reference", "text")] + CELLS)

# ---- materials
_many("material", ["CPU"], [("cryo_medium", "Cryoprotectant medium", "text"), ("cells_per_vial", "Cells per vial", "number", "cells"),
                            ("viability_pct", "Viability at freeze", "number", "%"),
                            ("freeze_method", "Freezing method", "choice", None, "Mr Frosty|controlled rate|other"),
                            ("storage_phase", "Storage phase", "choice", None, "LN2 vapor|LN2 liquid|-80C")])
_many("material", ["SCS"], [("dissociation_method", "Dissociation method", "text"), ("viability_pct", "Viability", "number", "%"),
                            ("concentration_cells_ul", "Concentration", "number", "cells/µL"), ("dead_cell_removal", "Dead-cell removal", "choice", None, YN),
                            ("hashtag", "Hashtag / multiplex antibody", "text"), ("buffer", "Buffer", "text"), ("target_cells", "Target cells to load", "number", "cells")])
_many("material", ["CPL"], [("cell_count", "Cell count", "number", "cells"), ("wash_buffer", "Wash buffer", "text"),
                            ("pellet_state", "Pellet state", "choice", None, "dry|in buffer"), ("intended_use", "Intended use", "choice", None, "DNA|RNA|DNA+RNA|IP|other")])
_many("material", ["CUL"], [("medium", "Medium and supplements", "text"), ("stimulation", "Stimulation", "text"), ("passage", "Passage number", "number"),
                            ("days_in_culture", "Days in culture", "number", "d"), ("seeding_density", "Seeding density", "text"),
                            ("cell_count", "Cell count", "number", "cells"), ("viability_pct", "Viability", "number", "%"),
                            ("expansion_fold", "Expansion fold", "number", "x"), ("mycoplasma", "Mycoplasma test", "choice", None, "negative|positive|not tested")])
_many("material", ["CPC"], [("cell_count", "Cell count", "number", "cells"), ("passage", "Passage number", "number"), ("harvest_date", "Harvest date", "date"),
                            ("viability_pct", "Viability at harvest", "number", "%"), ("wash_buffer", "Wash buffer", "text")])
NA_COMMON = [("extraction_kit", "Extraction kit / method", "text"), ("input_amount", "Input (cells or mg)", "text"),
             ("concentration_ng_ul", "Concentration", "number", "ng/µL"), ("concentration_method", "Concentration method", "choice", None, "Qubit|NanoDrop|TapeStation|other"),
             ("a260_280", "A260/280", "number"), ("a260_230", "A260/230", "number"), ("volume_ul", "Volume", "number", "µL"), ("elution_buffer", "Elution buffer", "text")]
_many("material", ["DNA"], NA_COMMON + [("din", "DIN", "number")])
_many("material", ["HMD"], NA_COMMON + [("din", "DIN", "number"), ("n50_kb", "Femto Pulse / size N50", "number", "kb"), ("shearing", "Shearing (method, target size)", "text")])
_many("material", ["RNA", "HMR"], NA_COMMON + [("rin", "RIN / RQN", "number"), ("dv200", "DV200", "number", "%"), ("dnase_treated", "DNase treated", "choice", None, YN)])
_many("material", ["CFD"], [("plasma_input_ml", "Plasma input", "number", "mL"), ("extraction_kit", "Extraction kit", "text"),
                            ("concentration_ng_ul", "Concentration", "number", "ng/µL"), ("concentration_method", "Concentration method", "choice", None, "Qubit|TapeStation|other"),
                            ("total_yield_ng", "Total yield", "number", "ng"), ("cfdna_peak_bp", "cfDNA peak", "number", "bp"),
                            ("hmw_contamination_pct", "High-MW contamination", "number", "%"), ("volume_ul", "Volume", "number", "µL"), ("elution_buffer", "Elution buffer", "text")])
_many("material", ["LIB"], [("assay", "Assay", "choice", None, "WGS|WES|RSQ|ONT|SCR|TCR|IPX|other", 1), ("prep_kit", "Library prep kit and version", "text"),
                            ("capture_kit", "Capture kit / panel and version", "text"), ("input_amount", "Input (ng or cells)", "text"),
                            ("pcr_cycles", "PCR cycles", "number"), ("index_ids", "Index / barcode IDs", "text"), ("umi", "UMI", "choice", None, YN),
                            ("rna_selection", "RNA selection", "choice", None, "polyA|rRNA depletion|NA"), ("stranded", "Stranded", "choice", None, "yes|no|NA"),
                            ("mean_fragment_bp", "Mean fragment size", "number", "bp"), ("concentration_nm", "Concentration", "number", "nM"),
                            ("qc_trace", "QC trace reference", "text"), ("submission_id", "Submission / order ID", "text"), ("pooled_with", "Pooled with (library IDs)", "text")])
_many("material", ["PEP"], [("hla_class", "HLA class", "choice", None, "I|II|I+II", 1), ("ip_antibody", "IP antibody", "choice", None, "W6/32|L243|other"), ("antibody_lot", "Antibody lot", "text"),
                            ("input_cells", "Input cell number", "number", "cells"), ("bead_type", "Bead type", "text"), ("lysis_buffer", "Lysis buffer", "text"),
                            ("elution", "Elution", "text"), ("cleanup", "Cleanup", "choice", None, "C18|SCX|C18+SCX|other"), ("offline_fractions", "Offline fraction count", "number"),
                            ("resuspension_ul", "Resuspension volume", "number", "µL"), ("target_instrument", "Target instrument", "text")])
_many("material", ["SNF"], [("tissue_mass_mg", "Tissue mass", "number", "mg"), ("ischemia_time_min", "Ischemia time", "number", "min"),
                            ("freeze_method", "Freezing method", "choice", None, "LN2|isopentane|other"), ("tumor_pct", "% tumor (pathology)", "number", "%"),
                            ("necrosis_pct", "% necrosis", "number", "%"), ("he_slide", "H&E slide reference", "text")])
_many("material", ["OCT"], [("tissue_mass_mg", "Tissue mass", "number", "mg"), ("block_id", "Block ID", "text"), ("sections_cut", "Sections cut", "number"),
                            ("tumor_pct", "% tumor", "number", "%"), ("he_slide", "H&E slide reference", "text")])
_many("material", ["FFP"], [("block_id", "Pathology accession / block ID", "text"), ("fixation_time_h", "Fixation time", "number", "h"), ("block_age", "Block age", "text"),
                            ("sections", "Sections (count × thickness)", "text"), ("tumor_pct", "% tumor", "number", "%"),
                            ("macrodissected", "Macro-dissected", "choice", None, YN), ("he_slide", "H&E slide reference", "text")])


def seed(conn):
    order = {}
    for scope, code, key, label, type_, unit, choices, required in ATTRS:
        n = order.get((scope, code), 0) + 1
        order[(scope, code)] = n
        conn.execute(
            "INSERT OR IGNORE INTO attribute_definition(scope, code, key, label, type, unit, choices, required, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?,?)", (scope, code, key, label, type_, unit, choices, required, n))
