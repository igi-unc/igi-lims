"""Initial controlled vocabularies and derivation rules. Edit via the admin UI after first load."""

CODES = {
    "cohort": [
        ("MP", "Malignant pleural effusion study"),
        ("AM", "Acute myeloid leukemia"),
        ("TN", "Triple-negative breast cancer"),
        ("NC", "NUT carcinoma"),
    ],
    "specimen": [
        ("PF", "Pleural fluid (MPE)"),
        ("PB", "Peripheral blood"),
        ("BM", "Bone marrow aspirate"),
        ("TU", "Tumor tissue (biopsy or resection)"),
        ("LN", "Lymph node"),
        ("NTC", "Normal T cell"),
        ("NRM", "Normal tissue"),
    ],
    "fraction": [
        ("BLK", "Unfractionated (whole fluid, whole blood, bulk cells)"),
        ("PLA", "Plasma"),
        ("SER", "Serum"),
        ("BFC", "Buffy coat"),
        ("PFS", "Pleural fluid supernatant"),
        ("PBM", "PBMC"),
        ("PFM", "PFMC (pleural fluid mononuclear cells)"),
        ("TUM", "Tumor cells, immune fraction depleted"),
        ("IMM", "Immune fraction (e.g. CD45+ enriched, buffy coat)"),
        ("TTC", "Total T cells"),
        ("CD8", "CD8+ T cells"),
        ("CD4", "CD4+ T cells"),
        ("NA",  "Not applicable"),
    ],
    "material": [
        ("NAT", "Native: as collected or as separated, no further processing"),
        ("CPU", "Cryopreserved"),
        ("SCS", "Single-cell suspension prepared for single-cell sequencing"),
        ("CPL", "Cell pellet"),
        ("CUL", "Expanded or cultured cells, viable"),
        ("CPC", "Cell pellet from cultured cells"),
        ("HMD", "High molecular weight DNA (long-read / ONT)"),
        ("HMR", "High molecular weight RNA (long-read / ONT)"),
        ("DNA", "Genomic DNA, standard extraction"),
        ("RNA", "Total RNA"),
        ("CFD", "Cell-free DNA (from plasma)"),
        ("LIB", "Sequencing library"),
        ("PEP", "Peptide eluate for immunopeptidomics"),
        ("SNF", "Snap-frozen tissue"),
        ("OCT", "OCT-embedded tissue"),
        ("FFP", "FFPE block or section"),
    ],
    "status": [
        ("Available", "In the freezer, usable"),
        ("In use", "Checked out for processing"),
        ("Depleted", "All material consumed; record retained"),
        ("Shipped", "Sent to an external party"),
        ("Destroyed", "Discarded"),
    ],
    "assay": [
        ("WGS", "Whole-genome sequencing"),
        ("WES", "Whole-exome sequencing"),
        ("RSQ", "Bulk RNA-seq"),
        ("ONT", "Oxford Nanopore long-read"),
        ("SCR", "Single-cell RNA-seq"),
        ("TCR", "TCR sequencing"),
        ("IPX", "Immunopeptidomics MS"),
    ],
    "biobank_source": [
        ("C", "UNC CCPD biobank"),
        ("H", "HemaTrack"),
        ("IH", "In-house: collected or generated at PIRL, no biobank"),
        ("NA", "Not applicable"),
    ],
    "site": [
        ("UNC", "University of North Carolina"),
    ],
    "unit": [
        ("mL", "millilitres"),
        ("uL", "microlitres"),
        ("cells", "cell count"),
        ("ng", "nanograms"),
        ("ug", "micrograms"),
        ("ng/uL", "concentration"),
        ("mg", "milligrams"),
        ("sections", "FFPE sections"),
        ("NA", "Not applicable"),
    ],
}

# (rule_type, from, to)
RULES = []

def _add(rule_type, frm, tos):
    for t in tos:
        RULES.append((rule_type, frm, t))

# Which fractions can exist for each specimen type.
_add("specimen_fraction", "PF",  ["BLK", "PFS", "PFM", "TUM", "IMM", "TTC", "CD8", "CD4"])
_add("specimen_fraction", "PB",  ["BLK", "PLA", "SER", "BFC", "PBM", "IMM", "TTC", "CD8", "CD4"])
_add("specimen_fraction", "BM",  ["BLK", "PLA", "TUM", "IMM", "TTC", "CD8", "CD4"])
_add("specimen_fraction", "TU",  ["BLK", "TUM", "IMM", "TTC", "CD8", "CD4"])
_add("specimen_fraction", "LN",  ["BLK", "TUM", "IMM", "TTC", "CD8", "CD4"])
_add("specimen_fraction", "NTC", ["BLK", "TTC", "CD8", "CD4"])
_add("specimen_fraction", "NRM", ["BLK", "NA"])

# Fraction refinement (same -> same is always allowed and not listed).
_add("fraction_transition", "BLK", ["PLA", "SER", "BFC", "PFS", "PBM", "PFM", "TUM", "IMM", "TTC", "CD8", "CD4", "NA"])
_add("fraction_transition", "PBM", ["IMM", "TTC", "CD8", "CD4"])
_add("fraction_transition", "PFM", ["TUM", "IMM", "TTC", "CD8", "CD4"])
_add("fraction_transition", "BFC", ["IMM", "TTC", "CD8", "CD4"])
_add("fraction_transition", "IMM", ["TTC", "CD8", "CD4"])
_add("fraction_transition", "TTC", ["CD8", "CD4"])

# Material processing steps (same -> same listed explicitly where re-aliquoting makes sense).
_add("material_transition", "NAT", ["NAT", "CPU", "SCS", "CPL", "CUL", "DNA", "RNA", "HMD", "HMR", "CFD", "SNF", "OCT", "FFP"])
_add("material_transition", "CPU", ["CPU", "SCS", "CPL", "CUL", "DNA", "RNA", "HMD", "HMR"])
_add("material_transition", "SCS", ["SCS", "CPL", "LIB"])
_add("material_transition", "CPL", ["CPL", "DNA", "RNA", "HMD", "HMR", "PEP"])
_add("material_transition", "CUL", ["CUL", "CPC", "SCS"])
_add("material_transition", "CPC", ["CPC", "PEP", "DNA", "RNA", "HMD", "HMR"])
_add("material_transition", "DNA", ["DNA", "LIB"])
_add("material_transition", "HMD", ["HMD", "LIB"])
_add("material_transition", "RNA", ["RNA", "LIB"])
_add("material_transition", "HMR", ["HMR", "LIB"])
_add("material_transition", "CFD", ["CFD", "LIB"])
_add("material_transition", "SNF", ["DNA", "RNA", "HMD", "HMR", "CPL"])
_add("material_transition", "OCT", ["DNA", "RNA"])
_add("material_transition", "FFP", ["FFP", "DNA", "RNA"])

# Materials that only make sense in particular fractions.
_add("material_fraction", "CFD", ["PLA"])
_add("material_fraction", "PEP", ["TUM", "BLK", "IMM"])

# What a root (as-collected) specimen may arrive as.
_add("root_material", "*", ["NAT", "CPU", "SNF", "OCT", "FFP"])


def seed(conn):
    for category, items in CODES.items():
        for i, (code, meaning) in enumerate(items):
            conn.execute(
                "INSERT OR IGNORE INTO code_list(category, code, meaning, sort_order) VALUES (?,?,?,?)",
                (category, code, meaning, i),
            )
    for rule_type, frm, to in RULES:
        conn.execute(
            "INSERT OR IGNORE INTO derivation_rule(rule_type, from_code, to_code) VALUES (?,?,?)",
            (rule_type, frm, to),
        )
