from ..db import get_db


def codes(category, active_only=True):
    q = "SELECT code, meaning, active FROM code_list WHERE category=?"
    if active_only:
        q += " AND active=1"
    return get_db().execute(q + " ORDER BY sort_order, code", (category,)).fetchall()


def code_meaning_map():
    out = {}
    for r in get_db().execute("SELECT category, code, meaning FROM code_list"):
        out.setdefault(r["category"], {})[r["code"]] = r["meaning"]
    return out
