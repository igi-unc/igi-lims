"""Per-fraction / per-material metadata fields. Edit later under Admin > Fields.

No free-text fields: every value is a number, a date/time, a fixed choice, or an entry from an
admin-extendable list (a code_list category, see seed.py LISTS). Reference fields (slides, traces,
flow files) are attachments instead.
"""

# (scope, code, key, label, type, unit, choices, required)
#   type 'choice': choices = fixed 'a|b|c'
#   type 'list'  : choices = code_list category name (extend on the Codes page)
ATTRS = []


def _a(scope, code, key, label, type="list", unit=None, choices=None, required=0):
    ATTRS.append((scope, code, key, label, type, unit, choices, required))


def _many(scope, codes, fields):
    for c in codes:
        for f in fields:
            _a(scope, c, *f)


YN = "yes|no"
HEMO = ("hemolysis_grade", "Hemolysis grade", "choice", None, "none|mild|moderate|severe|NA")
CELLS = [("cell_count", "Cell count", "number", "cells"), ("viability_pct", "Viability", "number", "%"),
         ("count_method", "Counting method", "choice", None, "trypan blue|AO/PI|Countess|hemocytometer|flow|NA")]
SPIN = [("spin_protocol", "Spin protocol", "list", None, "spin_protocol")]
KIT = [("kit", "Kit / method", "list", None, "kit"), ("kit_lot", "Kit lot", "list", None, "kit_lot")]
PURITY = [("purity_pct", "Purity estimate", "number", "%"), ("purity_method", "Purity method", "choice", None, "flow|cytology|not assessed")]

# ---- all tubes
_a("all", "*", "qc_result", "QC result", "choice", None, "pass|fail|borderline|not assessed")

# ---- fractions
_many("fraction", ["PLA"], SPIN + [("time_to_spin_min", "Time from draw to spin", "number", "min"), HEMO])
_many("fraction", ["SER"], [("clot_time_min", "Clot time", "number", "min")] + SPIN + [HEMO])
_many("fraction", ["BFC"], SPIN + [("rbc_lysis", "RBC lysis done", "choice", None, YN)])
_many("fraction", ["PFS"], SPIN + [("filtered", "Filter", "list", None, "filter"), ("appearance", "Appearance", "choice", None, "clear|bloody|turbid|NA")])
_many("fraction", ["PBM", "PFM"], [("isolation_method", "Isolation method", "list", None, "isolation_method"), ("rbc_lysis", "RBC lysis done", "choice", None, YN)] + CELLS)
_many("fraction", ["TUM"], [("enrichment_method", "Enrichment method", "list", None, "enrichment_method")] + KIT + [("markers", "Marker panel", "list", None, "marker_panel")] + PURITY + CELLS)
_many("fraction", ["NAC"], [("adherence_time_h", "Adherence time", "number", "h")] + CELLS)
_many("fraction", ["IMM"], [("enrichment_method", "Enrichment method", "list", None, "enrichment_method")] + KIT + PURITY + CELLS)
_many("fraction", ["TTC"], [("selection_method", "Selection method", "list", None, "selection_method")] + KIT + [("purity_pct", "Purity (% CD3+)", "number", "%")] + CELLS)
_many("fraction", ["CD8", "CD4"], [("selection_mode", "Selection mode", "choice", None, "positive|negative|FACS")] + KIT + [("purity_pct", "Purity by flow", "number", "%")] + CELLS)

# ---- materials
_many("material", ["CPU"], [("cryo_medium", "Cryoprotectant medium", "list", None, "cryo_medium"), ("cells_per_vial", "Cells per vial", "number", "cells"),
                            ("viability_pct", "Viability at freeze", "number", "%"),
                            ("freeze_method", "Freezing method", "list", None, "freeze_method"),
                            ("storage_phase", "Storage phase", "choice", None, "LN2 vapor|LN2 liquid|-80C")])
_many("material", ["SCS"], [("dissociation_method", "Dissociation method", "list", None, "dissociation_method"), ("viability_pct", "Viability", "number", "%"),
                            ("concentration_cells_ul", "Concentration", "number", "cells/µL"), ("dead_cell_removal", "Dead-cell removal", "choice", None, YN),
                            ("hashtag", "Hashtag / multiplex antibody", "list", None, "hashtag"), ("buffer", "Buffer", "list", None, "buffer"),
                            ("target_cells", "Target cells to load", "number", "cells")])
_many("material", ["FRZ"], [("volume_ml", "Volume per tube", "number", "mL"), ("freeze_temp", "Stored at", "choice", None, "-80C|-20C|LN2")])
_many("material", ["CUL"], [("medium", "Culture medium", "list", None, "culture_medium"), ("supplements", "Supplements", "list", None, "supplement"),
                            ("stimulation", "Stimulation", "list", None, "stimulation"), ("passage", "Passage number", "number"),
                            ("days_in_culture", "Days in culture", "number", "d"), ("seeding_density", "Seeding density", "number", "cells/mL"),
                            ("cell_count", "Cell count", "number", "cells"), ("viability_pct", "Viability", "number", "%"),
                            ("expansion_fold", "Expansion fold", "number", "x"), ("mycoplasma", "Mycoplasma test", "choice", None, "negative|positive|not tested")])
NA_COMMON = [("extraction_kit", "Extraction kit / method", "list", None, "extraction_kit"), ("kit_lot", "Kit lot", "list", None, "kit_lot"),
             ("input_cells", "Input cells", "number", "cells"), ("input_mass_mg", "Input tissue", "number", "mg"),
             ("concentration_ng_ul", "Concentration", "number", "ng/µL"), ("concentration_method", "Concentration method", "choice", None, "Qubit|NanoDrop|TapeStation|NA"),
             ("a260_280", "A260/280", "number"), ("a260_230", "A260/230", "number"), ("volume_ul", "Volume", "number", "µL"),
             ("elution_buffer", "Elution buffer", "list", None, "buffer")]
_many("material", ["DNA"], NA_COMMON + [("din", "DIN", "number")])
_many("material", ["HMD"], NA_COMMON + [("din", "DIN", "number"), ("n50_kb", "Size N50", "number", "kb"), ("shearing", "Shearing", "list", None, "shearing"), ("shear_target_kb", "Shear target size", "number", "kb")])
_many("material", ["RNA", "HMR"], NA_COMMON + [("rin", "RIN / RQN", "number"), ("dv200", "DV200", "number", "%"), ("dnase_treated", "DNase treated", "choice", None, YN)])
_many("material", ["CFD"], [("plasma_input_ml", "Plasma input", "number", "mL"), ("extraction_kit", "Extraction kit", "list", None, "extraction_kit"), ("kit_lot", "Kit lot", "list", None, "kit_lot"),
                            ("concentration_ng_ul", "Concentration", "number", "ng/µL"), ("concentration_method", "Concentration method", "choice", None, "Qubit|TapeStation|NA"),
                            ("total_yield_ng", "Total yield", "number", "ng"), ("cfdna_peak_bp", "cfDNA peak", "number", "bp"),
                            ("hmw_contamination_pct", "High-MW contamination", "number", "%"), ("volume_ul", "Volume", "number", "µL"),
                            ("elution_buffer", "Elution buffer", "list", None, "buffer")])
_many("material", ["PEP"], [("hla_class", "HLA class", "choice", None, "I|II|I+II", 1), ("ip_antibody", "IP antibody", "list", None, "ip_antibody"), ("antibody_lot", "Antibody lot", "list", None, "antibody_lot"),
                            ("input_cells", "Input cell number", "number", "cells"), ("bead_type", "Bead type", "list", None, "bead_type"), ("lysis_buffer", "Lysis buffer", "list", None, "buffer"),
                            ("elution", "Elution", "list", None, "elution"), ("cleanup", "Cleanup", "list", None, "cleanup"), ("offline_fractions", "Offline fraction count", "number"),
                            ("resuspension_ul", "Resuspension volume", "number", "µL"), ("target_instrument", "Target instrument", "list", None, "instrument")])
_many("material", ["SNF"], [("cell_count", "Cell count", "number", "cells"), ("wash_buffer", "Wash buffer", "list", None, "buffer"),
                            ("pellet_state", "Pellet state", "choice", None, "dry|in buffer"),
                            ("intended_use", "Intended use", "choice", None, "DNA|RNA|DNA+RNA|IP|NA"),
                            ("freeze_method", "Freezing method", "list", None, "freeze_method")])
_many("material", ["OCT"], [("tissue_mass_mg", "Tissue mass", "number", "mg"), ("block_id", "Block ID", "list", None, "block_id"), ("sections_cut", "Sections cut", "number"),
                            ("tumor_pct", "% tumor", "number", "%")])
_many("material", ["FFP"], [("block_id", "Pathology accession / block ID", "list", None, "block_id"), ("fixation_time_h", "Fixation time", "number", "h"), ("block_age_years", "Block age", "number", "years"),
                            ("sections_count", "Sections", "number"), ("section_thickness_um", "Section thickness", "number", "µm"), ("tumor_pct", "% tumor", "number", "%"),
                            ("macrodissected", "Macro-dissected", "choice", None, YN)])


def seed(conn):
    order, keep = {}, set()
    for scope, code, key, label, type_, unit, choices, required in ATTRS:
        n = order.get((scope, code), 0) + 1
        order[(scope, code)] = n
        keep.add((scope, code, key))
        conn.execute(
            "INSERT INTO attribute_definition(scope, code, key, label, type, unit, choices, required, sort_order, active) "
            "VALUES (?,?,?,?,?,?,?,?,?,1) ON CONFLICT(scope, code, key) DO UPDATE SET label=excluded.label, type=excluded.type, "
            "unit=excluded.unit, choices=excluded.choices, required=excluded.required, sort_order=excluded.sort_order, active=1",
            (scope, code, key, label, type_, unit, choices, required, n))
    # retire seed-era free-text fields that are no longer in the seed
    for r in conn.execute("SELECT id, scope, code, key FROM attribute_definition WHERE type='text' AND active=1").fetchall():
        if (r["scope"], r["code"], r["key"]) not in keep:
            conn.execute("UPDATE attribute_definition SET active=0 WHERE id=?", (r["id"],))
