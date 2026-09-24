"""
Display names of registered target databases (T_TARGET_DATABASES).

A display name must not be used by another ACTIVE target (compared
case-insensitively, ignoring surrounding blanks). The registry has no
constraint on the column, so the rule lives here and is applied by the app
(CentralQueries.add_target_database / update_target_database, through
CentralQueries.display_name_conflict) and by the migration CLI, which reads the
registry on its own connection. No Streamlit or connector dependency, so the
CLI uses it without the app's runtime.
"""
from typing import Any, Optional

import pandas as pd

# The registry rows display_name_conflict checks a name against.
ACTIVE_DISPLAY_NAMES_SQL = """
                SELECT database_id, database_name, display_name
                FROM t_target_databases
                WHERE is_active = 'Y' AND display_name IS NOT NULL
            """
ACTIVE_DISPLAY_NAMES_COLUMNS = ('DATABASE_ID', 'DATABASE_NAME', 'DISPLAY_NAME')


def cell_text(value: Any) -> str:
    """A registry cell as stripped text; '' for None / NaN."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    return str(value).strip()


def display_name_conflict(display_name: Optional[str], registry: pd.DataFrame,
                          exclude_database_id: Optional[int] = None) -> Optional[str]:
    """Why display_name can't be used for a new or edited target, or None.

    registry: the rows of ACTIVE_DISPLAY_NAMES_SQL (column names in any case).
    The target being edited, exclude_database_id, is skipped.
    """
    name = cell_text(display_name)
    if not name:
        return None
    for rec in registry.to_dict('records'):
        rec = {str(k).lower(): v for k, v in rec.items()}
        other = cell_text(rec.get('display_name'))
        if not other or other.casefold() != name.casefold():
            continue
        try:
            other_id = int(rec.get('database_id'))
        except (TypeError, ValueError):
            other_id = None
        if exclude_database_id is not None and other_id == int(exclude_database_id):
            continue
        db_name = cell_text(rec.get('database_name'))
        return (f"The display name '{name}' is already used by target '{other}' "
                f"({db_name + ', ' if db_name else ''}ID {other_id}). "
                f"Choose a different display name.")
    return None
