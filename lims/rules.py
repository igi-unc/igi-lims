"""Derivation rule checks. Each check returns a list of human-readable violations."""


def _allowed(conn, rule_type, from_code):
    return {r["to_code"] for r in conn.execute(
        "SELECT to_code FROM derivation_rule WHERE rule_type=? AND from_code=?", (rule_type, from_code))}


def _has_rules(conn, rule_type, from_code):
    return conn.execute(
        "SELECT 1 FROM derivation_rule WHERE rule_type=? AND from_code=? LIMIT 1", (rule_type, from_code)
    ).fetchone() is not None


def check_root(conn, comp):
    """comp: parsed components of a first-generation tube (made straight from a collection)."""
    v = []
    if comp["fraction"] not in _allowed(conn, "specimen_fraction", comp["specimen"]):
        v.append(f"Fraction {comp['fraction']} is not allowed for specimen {comp['specimen']}")
    if comp["material"] not in _allowed(conn, "root_material", "*"):
        v.append(f"Material {comp['material']} cannot be made directly from a received specimen")
    if _has_rules(conn, "material_fraction", comp["material"]) and \
            comp["fraction"] not in _allowed(conn, "material_fraction", comp["material"]):
        v.append(f"Material {comp['material']} requires fraction in {sorted(_allowed(conn, 'material_fraction', comp['material']))}")
    return v


def check_derivation(conn, parent, comp):
    """parent: sample row; comp: parsed components of the child."""
    v = []
    if parent["deleted_at"]:
        v.append("Parent record is deleted")
    if parent["status"] in ("Depleted", "Destroyed"):
        v.append(f"Parent status is {parent['status']}")
    for field, col in (("project", "project_code"), ("cohort", "cohort_code"), ("participant", "participant_id"),
                       ("unc_id", "unc_id"), ("received_date", "received_date"), ("specimen", "specimen_code")):
        if comp[field] != parent[col]:
            v.append(f"Child {field} ({comp[field]}) differs from parent ({parent[col]})")
    if comp["fraction"] not in _allowed(conn, "specimen_fraction", comp["specimen"]):
        v.append(f"Fraction {comp['fraction']} is not allowed for specimen {comp['specimen']}")
    if comp["fraction"] != parent["fraction_code"] and \
            comp["fraction"] not in _allowed(conn, "fraction_transition", parent["fraction_code"]):
        v.append(f"Fraction {parent['fraction_code']} cannot be refined to {comp['fraction']}")
    if comp["material"] not in _allowed(conn, "material_transition", parent["material_code"]):
        v.append(f"Material {parent['material_code']} cannot be processed into {comp['material']}")
    if _has_rules(conn, "material_fraction", comp["material"]) and \
            comp["fraction"] not in _allowed(conn, "material_fraction", comp["material"]):
        v.append(f"Material {comp['material']} requires fraction in {sorted(_allowed(conn, 'material_fraction', comp['material']))}")
    return v


def rule_types():
    return ["specimen_fraction", "fraction_transition", "material_transition", "material_fraction", "root_material"]
