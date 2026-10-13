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

# Admin-extendable lists used by tube fields, custody events and metadata (no free text anywhere but Notes).
LISTS = {
    "sop": [("NA", "No SOP recorded")],
    "freezer": [("NA", "Not applicable")],
    "rack": [("NA", "Not applicable")],
    "box": [("NA", "Not applicable")],
    "position": [("NA", "Not applicable")] + [(f"{r}{c}", f"Row {r}, column {c}") for r in "ABCDEFGHIJ" for c in range(1, 11)],
    "party": [("PIRL", "PIRL lab"), ("HTSF", "UNC High-Throughput Sequencing Facility"), ("CCPD", "UNC CCPD biobank"), ("LN2", "LN2 storage"), ("-80", "-80 °C freezer")],
    "custody_purpose": [("EXTRACT", "DNA/RNA extraction"), ("SEQ", "Sequencing submission"), ("STORE", "Storage"), ("IP", "Immunopeptidomics"),
                        ("CULTURE", "Culture / expansion"), ("SORT", "Sorting / enrichment"), ("RETURN", "Returned"), ("SHIP", "Shipped externally")],
    "container_type": [("EDTA", "EDTA tube"), ("HEP", "Heparin tube"), ("STRECK", "Streck cfDNA tube"), ("ACD", "ACD tube"), ("PLAIN", "Plain / serum tube"), ("BAG", "Drainage bag"), ("NA", "Not applicable")],
    "spin_protocol": [("NA", "Not recorded")],
    "filter": [("NONE", "Not filtered"), ("0.22", "0.22 µm"), ("0.45", "0.45 µm"), ("70", "70 µm"), ("100", "100 µm")],
    "isolation_method": [("FICOLL", "Ficoll"), ("SEPMATE", "SepMate"), ("LYMPHOPREP", "Lymphoprep"), ("NA", "Not applicable")],
    "enrichment_method": [("CD45DEP", "CD45 depletion"), ("CD45POS", "CD45 positive selection"), ("EPCAM", "EpCAM positive selection"), ("FACS", "FACS"), ("MACS", "MACS"), ("BFC", "Buffy coat"), ("NONE", "None")],
    "selection_method": [("PANT_NEG", "Pan-T negative selection"), ("CD3_POS", "CD3 positive selection"), ("FACS", "FACS")],
    "kit": [("NA", "Not applicable")],
    "kit_lot": [("NA", "Not recorded")],
    "marker_panel": [("NA", "Not applicable"), ("CD45", "CD45"), ("EPCAM", "EpCAM"), ("CD3_4_8", "CD3 / CD4 / CD8")],
    "cryo_medium": [("FBS_DMSO", "90% FBS / 10% DMSO"), ("CS10", "CryoStor CS10"), ("NA", "Not applicable")],
    "freeze_method": [("MRFROSTY", "Mr Frosty"), ("CRF", "Controlled-rate freezer"), ("LN2", "LN2 snap freeze"), ("ISOPENTANE", "Isopentane"), ("NA", "Not applicable")],
    "dissociation_method": [("GENTLEMACS", "gentleMACS"), ("MILTENYI_TDK", "Miltenyi Tumor Dissociation Kit"), ("MECH", "Mechanical"), ("NA", "Not applicable")],
    "hashtag": [("NONE", "None"), ("TSA", "TotalSeq-A"), ("TSB", "TotalSeq-B"), ("TSC", "TotalSeq-C")],
    "buffer": [("PBS", "PBS"), ("TE", "TE"), ("EB", "Elution buffer (EB)"), ("H2O", "Nuclease-free water"), ("TFA01", "0.1% TFA"), ("NA", "Not applicable")],
    "culture_medium": [("RPMI10", "RPMI + 10% FBS"), ("AIMV", "AIM-V"), ("XVIVO15", "X-VIVO 15"), ("NA", "Not applicable")],
    "supplement": [("NONE", "None"), ("IL2", "IL-2"), ("IL7_15", "IL-7 + IL-15"), ("IL2_7_15", "IL-2 + IL-7 + IL-15")],
    "stimulation": [("NONE", "None"), ("CD3CD28", "anti-CD3/CD28 beads"), ("FEEDER", "Irradiated feeders")],
    "extraction_kit": [("DNEASY", "Qiagen DNeasy Blood & Tissue"), ("ALLPREP", "Qiagen AllPrep DNA/RNA"), ("NANOBIND", "Circulomics Nanobind"), ("MAGATTRACT", "Qiagen MagAttract HMW"),
                       ("CCFDNA", "QIAamp ccfDNA"), ("RNEASY", "Qiagen RNeasy"), ("TRIZOL", "TRIzol"), ("NA", "Not applicable")],
    "shearing": [("NONE", "None"), ("GTUBE", "Covaris g-TUBE"), ("MEGARUPTOR", "Megaruptor")],
    "library_prep_kit": [("LSK114", "ONT Ligation Sequencing Kit V14 (SQK-LSK114)"), ("ILMN_DNA", "Illumina DNA Prep"), ("KAPA_HYPER", "KAPA HyperPrep"),
                         ("10X_5P_V2", "10x 5' v2"), ("10X_3P_V31", "10x 3' v3.1"), ("SMARTER", "Takara SMARTer"), ("NA", "Not applicable")],
    "capture_kit": [("NONE", "No capture"), ("XGEN_V2", "IDT xGen Exome v2"), ("TWIST_2", "Twist Exome 2.0"), ("SS_XTHS2", "Agilent SureSelect XT HS2")],
    "index": [("NA", "Not recorded")],
    "submission": [("NA", "Not submitted")],
    "ip_antibody": [("W632", "W6/32 (pan class I)"), ("L243", "L243 (HLA-DR)"), ("NA", "Not applicable")],
    "antibody_lot": [("NA", "Not recorded")],
    "bead_type": [("PROTA", "Protein A"), ("PROTG", "Protein G"), ("CNBR", "CNBr-Sepharose"), ("NA", "Not applicable")],
    "elution": [("TFA01", "0.1% TFA"), ("AA10", "10% acetic acid"), ("NA", "Not applicable")],
    "cleanup": [("C18", "C18"), ("SCX", "SCX"), ("C18_SCX", "C18 + SCX"), ("NA", "Not applicable")],
    "instrument": [("NA", "Not decided")],
    "block_id": [("NA", "Not recorded")],
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
    for category, items in list(CODES.items()) + list(LISTS.items()):
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
