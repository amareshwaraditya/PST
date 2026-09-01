"""PST - Price Setting Tool for Spare Parts.

Streamlit multipage application.
Run with:  streamlit run pst/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `pst` is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import psycopg2
import streamlit as st

from pst import db
from pst.import_export import parse_upload, import_rows, to_csv_bytes

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="PST - Price Setting Tool",
    page_icon=":material/calculate:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ensure the database & seed data exist on every run.
try:
    db.init_db()
    db.seed_modalities()
except psycopg2.OperationalError:
    st.error(
        "The database connection is temporarily unavailable. "
        "Check that this network allows outbound PostgreSQL traffic to the Supabase pooler, "
        "then refresh the page."
    )
    st.stop()


# ===================================================================
# Helper: reusable data-table + CRUD form pattern
# ===================================================================

def _lookup_map(items: list[dict], id_key: str = "id", label_key: str = "name") -> dict[int, str]:
    """Build {id: label} from a list of dicts."""
    return {item[id_key]: item[label_key] for item in items}


def _id_from_label(label: str, lookup: dict[int, str]) -> int | None:
    """Reverse-lookup id from a label string in a {id: label} map."""
    for k, v in lookup.items():
        if v == label:
            return k
    return None


# ===================================================================
# PAGE: Home / Dashboard
# ===================================================================

def page_home() -> None:
    """Dashboard / landing page showing system status and table counts."""
    st.title("Price Setting Tool")
    st.caption("Spare Parts Pricing Engine for Philips Healthcare")

    st.divider()

    # ---- Table counts ----
    counts = db.table_counts()

    st.subheader("Master Data Overview")
    cols = st.columns(len(counts))
    display_names = {
        "modalities": "Modalities",
        "families": "Families",
        "sub_families": "Sub-Families",
        "profit_centers": "Profit Centers",
        "characteristics": "Characteristics",
        "product_hierarchies": "Product Hierarchies",
        "keywords": "Keywords",
    }
    for col, (table, count) in zip(cols, counts.items()):
        col.metric(label=display_names.get(table, table), value=count)

    st.divider()

    # ---- Phase status ----
    st.subheader("Implementation Phases")
    phases = [
        ("Phase 1: Foundation", True, "Streamlit app + SQLite database"),
        ("Phase 2: Master Data", True, "Families, Sub-Families, Profit Centers, Characteristics, Hierarchies, Keywords"),
        ("Phase 3: Materials", False, "Spare parts upload, view, filter, edit"),
        ("Phase 4: Determination", False, "Auto sub-family assignment (6-step priority)"),
        ("Phase 5: Equipment Equivalent", False, "First pricing model (ported from JS)"),
        ("Phase 6: Country Settings", False, "Multi-country price calculation (WRP -> CTP -> CLP)"),
        ("Phase 7: Remaining Models", False, "Cost Plus, Value Based, Manual WRP"),
    ]
    for name, done, desc in phases:
        icon = ":material/check_circle:" if done else ":material/radio_button_unchecked:"
        st.markdown(f"{icon} **{name}** &mdash; {desc}")


# ===================================================================
# PAGE: Families & Sub-Families
# ===================================================================

def page_families() -> None:
    st.title("Families & Sub-Families")

    tab_fam, tab_sf = st.tabs(["Families", "Sub-Families"])

    # ------------------------------------------------------------------
    # TAB: Families
    # ------------------------------------------------------------------
    with tab_fam:
        families = db.list_families()

        # ---- Add / Edit form ----
        with st.expander("Add / Edit Family", icon=":material/add:"):
            edit_fam_id = None
            if families:
                fam_options = ["-- New --"] + [f"{f['code']} - {f['name']}" for f in families]
                sel = st.selectbox("Select to edit (or New)", fam_options, key="fam_sel")
                if sel != "-- New --":
                    idx = fam_options.index(sel) - 1
                    edit_fam_id = families[idx]["id"]

            existing = db.get_family(edit_fam_id) if edit_fam_id else None

            with st.form("family_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                fam_code = c1.text_input("Code", value=existing["code"] if existing else "")
                fam_name = c2.text_input("Name", value=existing["name"] if existing else "")
                fam_desc = st.text_input("Description", value=existing.get("description", "") if existing else "")

                submitted = st.form_submit_button("Save Family")
                if submitted:
                    if not fam_code or not fam_name:
                        st.error("Code and Name are required.")
                    else:
                        try:
                            db.upsert_family(fam_code.strip(), fam_name.strip(),
                                             fam_desc.strip(), family_id=edit_fam_id)
                            st.success(f"Family '{fam_name}' saved.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Error: {exc}")

        # ---- CSV Import ----
        with st.expander("Import from CSV / Excel", icon=":material/upload:"):
            up_fam = st.file_uploader("Upload Families file", type=["csv", "xlsx"],
                                      key="fam_upload")
            if up_fam:
                df, err = parse_upload(up_fam, required_columns=["code", "name"])
                if err:
                    st.error(err)
                elif df is not None:
                    st.dataframe(df.head(10))
                    if st.button("Import Families", key="fam_import_btn"):
                        ins, skip, errs = import_rows(
                            df, db.upsert_family,
                            lambda r: {"code": r["code"], "name": r["name"],
                                       "description": r.get("description", "")},
                        )
                        st.success(f"Imported {ins}, skipped {skip}.")
                        if errs:
                            st.warning("\n".join(errs[:5]))
                        st.rerun()

        # ---- Data table ----
        if families:
            st.subheader(f"Families ({len(families)})")
            display_df = pd.DataFrame(families)[["id", "code", "name", "description"]]
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            # ---- Delete ----
            with st.expander("Delete a Family", icon=":material/delete:"):
                del_opts = [f"{f['code']} - {f['name']}" for f in families]
                del_sel = st.selectbox("Select family to delete", del_opts, key="fam_del_sel")
                if st.button("Delete", key="fam_del_btn", type="primary"):
                    idx = del_opts.index(del_sel)
                    ok = db.delete_family(families[idx]["id"])
                    if ok:
                        st.success("Deleted.")
                        st.rerun()
                    else:
                        st.error("Cannot delete: family has sub-families. Remove them first.")
        else:
            st.info("No families yet. Add one above or import from CSV.")

    # ------------------------------------------------------------------
    # TAB: Sub-Families
    # ------------------------------------------------------------------
    with tab_sf:
        families = db.list_families()
        modalities = db.list_modalities()
        sub_families = db.list_sub_families()

        if not families:
            st.warning("Create at least one Family before adding Sub-Families.")
            return

        # ---- Filter by Family ----
        fam_filter_opts = ["All"] + [f"{f['code']} - {f['name']}" for f in families]
        fam_filter = st.selectbox("Filter by Family", fam_filter_opts, key="sf_filter")
        filtered_sf = sub_families
        if fam_filter != "All":
            idx = fam_filter_opts.index(fam_filter) - 1
            filtered_sf = [sf for sf in sub_families if sf["family_id"] == families[idx]["id"]]

        # ---- Add / Edit form ----
        with st.expander("Add / Edit Sub-Family", icon=":material/add:"):
            edit_sf_id = None
            if filtered_sf:
                sf_options = ["-- New --"] + [f"{sf['code']} - {sf['name']}" for sf in filtered_sf]
                sel = st.selectbox("Select to edit (or New)", sf_options, key="sf_sel")
                if sel != "-- New --":
                    idx = sf_options.index(sel) - 1
                    edit_sf_id = filtered_sf[idx]["id"]

            existing_sf = db.get_sub_family(edit_sf_id) if edit_sf_id else None
            existing_mod_ids = db.get_sub_family_modality_ids(edit_sf_id) if edit_sf_id else []

            with st.form("sf_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                sf_code = c1.text_input("Code", value=existing_sf["code"] if existing_sf else "")
                sf_name = c2.text_input("Name", value=existing_sf["name"] if existing_sf else "")

                c3, c4 = st.columns(2)
                fam_names = [f"{f['code']} - {f['name']}" for f in families]
                default_fam_idx = 0
                if existing_sf:
                    for i, f in enumerate(families):
                        if f["id"] == existing_sf["family_id"]:
                            default_fam_idx = i
                            break
                sf_family = c3.selectbox("Family", fam_names, index=default_fam_idx, key="sf_fam")

                # Multiselect for modalities (many-to-many)
                mod_options = [f"{m['code']} - {m['name']}" for m in modalities]
                default_mods = []
                if existing_mod_ids:
                    for m in modalities:
                        if m["id"] in existing_mod_ids:
                            default_mods.append(f"{m['code']} - {m['name']}")
                sf_mods = c4.multiselect("Modalities", mod_options, default=default_mods, key="sf_mods")

                c5, c6 = st.columns(2)
                calc_types = list(db.CALCULATION_TYPE_LABELS.values())
                calc_keys = list(db.CALCULATION_TYPE_LABELS.keys())
                default_calc_idx = 0
                if existing_sf:
                    default_calc_idx = calc_keys.index(existing_sf["calculation_type"]) if existing_sf["calculation_type"] in calc_keys else 0
                sf_calc = c5.selectbox("Calculation Type", calc_types, index=default_calc_idx, key="sf_calc")

                sf_type = c6.selectbox("Sub-Family Type", db.SUB_FAMILY_TYPES,
                                       index=db.SUB_FAMILY_TYPES.index(existing_sf["sub_family_type"]) if existing_sf else 0,
                                       key="sf_type")

                sf_desc = st.text_input("Description", value=existing_sf.get("description", "") if existing_sf else "")

                submitted = st.form_submit_button("Save Sub-Family")
                if submitted:
                    if not sf_code or not sf_name:
                        st.error("Code and Name are required.")
                    else:
                        try:
                            fam_idx = fam_names.index(sf_family)
                            fam_id_val = families[fam_idx]["id"]
                            calc_key = calc_keys[calc_types.index(sf_calc)]

                            new_sf_id = db.upsert_sub_family(
                                code=sf_code.strip(), name=sf_name.strip(),
                                family_id=fam_id_val,
                                calculation_type=calc_key,
                                sub_family_type=sf_type,
                                description=sf_desc.strip(),
                                sf_id=edit_sf_id,
                            )
                            # Save modality assignments
                            selected_mod_ids = []
                            for label in sf_mods:
                                idx = mod_options.index(label)
                                selected_mod_ids.append(modalities[idx]["id"])
                            db.set_sub_family_modalities(new_sf_id, selected_mod_ids)

                            st.success(f"Sub-Family '{sf_name}' saved.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Error: {exc}")

        # ---- Data table ----
        if filtered_sf:
            st.subheader(f"Sub-Families ({len(filtered_sf)})")
            disp_cols = ["id", "code", "name", "family_name", "modality_codes",
                         "calculation_type", "sub_family_type"]
            disp_df = pd.DataFrame(filtered_sf)
            show_cols = [c for c in disp_cols if c in disp_df.columns]
            st.dataframe(disp_df[show_cols], use_container_width=True, hide_index=True)

            # ---- Delete ----
            with st.expander("Delete a Sub-Family", icon=":material/delete:"):
                del_opts = [f"{sf['code']} - {sf['name']}" for sf in filtered_sf]
                del_sel = st.selectbox("Select sub-family to delete", del_opts, key="sf_del_sel")
                if st.button("Delete", key="sf_del_btn", type="primary"):
                    idx = del_opts.index(del_sel)
                    ok = db.delete_sub_family(filtered_sf[idx]["id"])
                    if ok:
                        st.success("Deleted.")
                        st.rerun()
                    else:
                        st.error("Cannot delete: sub-family is referenced by other records.")
        else:
            st.info("No sub-families found. Add one above.")

        # ---- CSV Export ----
        if sub_families:
            csv = to_csv_bytes(sub_families,
                               columns=["code", "name", "family_name", "modality_codes",
                                        "calculation_type", "sub_family_type", "description"])
            st.download_button("Export Sub-Families CSV", csv,
                               file_name="sub_families.csv", mime="text/csv")


# ===================================================================
# PAGE: Profit Centers
# ===================================================================

def page_profit_centers() -> None:
    st.title("Profit Centers")

    modalities = db.list_modalities()
    sub_families = db.list_sub_families()
    profit_centers = db.list_profit_centers()

    mod_lookup = _lookup_map(modalities, label_key="code")
    sf_lookup = _lookup_map(sub_families)

    # ---- Add / Edit form ----
    with st.expander("Add / Edit Profit Center", icon=":material/add:"):
        edit_pc_id = None
        if profit_centers:
            pc_options = ["-- New --"] + [f"{pc['profit_center']} - {pc.get('description','')}" for pc in profit_centers]
            sel = st.selectbox("Select to edit (or New)", pc_options, key="pc_sel")
            if sel != "-- New --":
                idx = pc_options.index(sel) - 1
                edit_pc_id = profit_centers[idx]["id"]

        existing_pc = None
        if edit_pc_id:
            for pc in profit_centers:
                if pc["id"] == edit_pc_id:
                    existing_pc = pc
                    break

        with st.form("pc_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            pc_code = c1.text_input("Profit Center Code",
                                    value=existing_pc["profit_center"] if existing_pc else "")
            pc_desc = c2.text_input("Description",
                                    value=existing_pc.get("description", "") if existing_pc else "")

            c3, c4 = st.columns(2)
            mod_names = ["(none)"] + [f"{m['code']} - {m['name']}" for m in modalities]
            default_mod_idx = 0
            if existing_pc and existing_pc.get("modality_id"):
                for i, m in enumerate(modalities):
                    if m["id"] == existing_pc["modality_id"]:
                        default_mod_idx = i + 1
                        break
            pc_mod = c3.selectbox("Modality", mod_names, index=default_mod_idx, key="pc_mod")

            sf_names = ["(none)"] + [f"{sf['code']} - {sf['name']}" for sf in sub_families]
            default_sf_idx = 0
            if existing_pc and existing_pc.get("default_sub_family_id"):
                for i, sf in enumerate(sub_families):
                    if sf["id"] == existing_pc["default_sub_family_id"]:
                        default_sf_idx = i + 1
                        break
            pc_sf = c4.selectbox("Default Sub-Family", sf_names, index=default_sf_idx, key="pc_sf")

            submitted = st.form_submit_button("Save Profit Center")
            if submitted:
                if not pc_code:
                    st.error("Profit Center code is required.")
                else:
                    try:
                        mod_id = None
                        if pc_mod != "(none)":
                            mod_id = modalities[mod_names.index(pc_mod) - 1]["id"]
                        sf_id = None
                        if pc_sf != "(none)":
                            sf_id = sub_families[sf_names.index(pc_sf) - 1]["id"]
                        db.upsert_profit_center(
                            profit_center=pc_code.strip(),
                            description=pc_desc.strip(),
                            modality_id=mod_id,
                            default_sub_family_id=sf_id,
                            pc_id=edit_pc_id,
                        )
                        st.success(f"Profit Center '{pc_code}' saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error: {exc}")

    # ---- CSV Import ----
    with st.expander("Import from CSV / Excel", icon=":material/upload:"):
        up_pc = st.file_uploader("Upload Profit Centers file", type=["csv", "xlsx"],
                                 key="pc_upload")
        if up_pc:
            df, err = parse_upload(up_pc, required_columns=["profit_center"])
            if err:
                st.error(err)
            elif df is not None:
                st.dataframe(df.head(10))
                if st.button("Import Profit Centers", key="pc_import_btn"):
                    ins, skip, errs = import_rows(
                        df, db.upsert_profit_center,
                        lambda r: {"profit_center": r["profit_center"],
                                   "description": r.get("description", "")},
                    )
                    st.success(f"Imported {ins}, skipped {skip}.")
                    if errs:
                        st.warning("\n".join(errs[:5]))
                    st.rerun()

    # ---- Data table ----
    if profit_centers:
        st.subheader(f"Profit Centers ({len(profit_centers)})")
        disp_cols = ["id", "profit_center", "description", "modality_code", "sub_family_name"]
        disp_df = pd.DataFrame(profit_centers)
        show_cols = [c for c in disp_cols if c in disp_df.columns]
        st.dataframe(disp_df[show_cols], use_container_width=True, hide_index=True)

        # ---- Delete ----
        with st.expander("Delete a Profit Center", icon=":material/delete:"):
            del_opts = [f"{pc['profit_center']} - {pc.get('description','')}" for pc in profit_centers]
            del_sel = st.selectbox("Select to delete", del_opts, key="pc_del_sel")
            if st.button("Delete", key="pc_del_btn", type="primary"):
                idx = del_opts.index(del_sel)
                ok = db.delete_profit_center(profit_centers[idx]["id"])
                if ok:
                    st.success("Deleted.")
                    st.rerun()
                else:
                    st.error("Delete failed.")

        # ---- Export ----
        csv = to_csv_bytes(profit_centers,
                           columns=["profit_center", "description", "modality_code", "sub_family_name"])
        st.download_button("Export Profit Centers CSV", csv,
                           file_name="profit_centers.csv", mime="text/csv")
    else:
        st.info("No profit centers yet. Add one above or import from CSV.")


# ===================================================================
# PAGE: Characteristics
# ===================================================================

def page_characteristics() -> None:
    st.title("Characteristics")

    sub_families = db.list_sub_families()
    characteristics = db.list_characteristics()

    # ---- Add / Edit form ----
    with st.expander("Add / Edit Characteristic", icon=":material/add:"):
        edit_char_id = None
        if characteristics:
            char_options = ["-- New --"] + [f"{c['characteristic_code']} - {c.get('description','')}" for c in characteristics]
            sel = st.selectbox("Select to edit (or New)", char_options, key="char_sel")
            if sel != "-- New --":
                idx = char_options.index(sel) - 1
                edit_char_id = characteristics[idx]["id"]

        existing_char = None
        if edit_char_id:
            for c in characteristics:
                if c["id"] == edit_char_id:
                    existing_char = c
                    break

        with st.form("char_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            char_code = c1.text_input("Characteristic Code",
                                      value=existing_char["characteristic_code"] if existing_char else "")
            char_desc = c2.text_input("Description",
                                      value=existing_char.get("description", "") if existing_char else "")

            c3, c4 = st.columns(2)
            char_cat = c3.text_input("Category",
                                     value=existing_char.get("category", "") if existing_char else "")

            sf_names = ["(none)"] + [f"{sf['code']} - {sf['name']}" for sf in sub_families]
            default_sf_idx = 0
            if existing_char and existing_char.get("sub_family_id"):
                for i, sf in enumerate(sub_families):
                    if sf["id"] == existing_char["sub_family_id"]:
                        default_sf_idx = i + 1
                        break
            char_sf = c4.selectbox("Sub-Family", sf_names, index=default_sf_idx, key="char_sf")

            submitted = st.form_submit_button("Save Characteristic")
            if submitted:
                if not char_code:
                    st.error("Characteristic code is required.")
                else:
                    try:
                        sf_id = None
                        if char_sf != "(none)":
                            sf_id = sub_families[sf_names.index(char_sf) - 1]["id"]
                        db.upsert_characteristic(
                            characteristic_code=char_code.strip(),
                            description=char_desc.strip(),
                            category=char_cat.strip(),
                            sub_family_id=sf_id,
                            char_id=edit_char_id,
                        )
                        st.success(f"Characteristic '{char_code}' saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error: {exc}")

    # ---- CSV Import ----
    with st.expander("Import from CSV / Excel", icon=":material/upload:"):
        up_char = st.file_uploader("Upload Characteristics file", type=["csv", "xlsx"],
                                   key="char_upload")
        if up_char:
            df, err = parse_upload(up_char, required_columns=["characteristic_code"])
            if err:
                st.error(err)
            elif df is not None:
                st.dataframe(df.head(10))
                if st.button("Import Characteristics", key="char_import_btn"):
                    ins, skip, errs = import_rows(
                        df, db.upsert_characteristic,
                        lambda r: {"characteristic_code": r["characteristic_code"],
                                   "description": r.get("description", ""),
                                   "category": r.get("category", "")},
                    )
                    st.success(f"Imported {ins}, skipped {skip}.")
                    if errs:
                        st.warning("\n".join(errs[:5]))
                    st.rerun()

    # ---- Data table ----
    if characteristics:
        st.subheader(f"Characteristics ({len(characteristics)})")
        disp_cols = ["id", "characteristic_code", "description", "category", "sub_family_name"]
        disp_df = pd.DataFrame(characteristics)
        show_cols = [c for c in disp_cols if c in disp_df.columns]
        st.dataframe(disp_df[show_cols], use_container_width=True, hide_index=True)

        # ---- Delete ----
        with st.expander("Delete a Characteristic", icon=":material/delete:"):
            del_opts = [f"{c['characteristic_code']} - {c.get('description','')}" for c in characteristics]
            del_sel = st.selectbox("Select to delete", del_opts, key="char_del_sel")
            if st.button("Delete", key="char_del_btn", type="primary"):
                idx = del_opts.index(del_sel)
                ok = db.delete_characteristic(characteristics[idx]["id"])
                if ok:
                    st.success("Deleted.")
                    st.rerun()
                else:
                    st.error("Delete failed.")

        # ---- Export ----
        csv = to_csv_bytes(characteristics,
                           columns=["characteristic_code", "description", "category", "sub_family_name"])
        st.download_button("Export Characteristics CSV", csv,
                           file_name="characteristics.csv", mime="text/csv")
    else:
        st.info("No characteristics yet. Add one above or import from CSV.")


# ===================================================================
# PAGE: Product Hierarchies
# ===================================================================

def page_product_hierarchies() -> None:
    st.title("Product Hierarchies")

    sub_families = db.list_sub_families()
    hierarchies = db.list_product_hierarchies()

    if not sub_families:
        st.warning("Create at least one Sub-Family before adding Product Hierarchies.")
        return

    # ---- Add / Edit form ----
    with st.expander("Add / Edit Product Hierarchy", icon=":material/add:"):
        edit_ph_id = None
        if hierarchies:
            ph_options = ["-- New --"] + [f"{h['hierarchy_code']} - {h.get('hierarchy_description','')}" for h in hierarchies]
            sel = st.selectbox("Select to edit (or New)", ph_options, key="ph_sel")
            if sel != "-- New --":
                idx = ph_options.index(sel) - 1
                edit_ph_id = hierarchies[idx]["id"]

        existing_ph = None
        if edit_ph_id:
            for h in hierarchies:
                if h["id"] == edit_ph_id:
                    existing_ph = h
                    break

        with st.form("ph_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            ph_code = c1.text_input("Hierarchy Code (4 digits)",
                                    value=existing_ph["hierarchy_code"] if existing_ph else "",
                                    max_chars=4)
            ph_desc = c2.text_input("Description",
                                    value=existing_ph.get("hierarchy_description", "") if existing_ph else "")

            sf_names = [f"{sf['code']} - {sf['name']}" for sf in sub_families]
            default_sf_idx = 0
            if existing_ph and existing_ph.get("sub_family_id"):
                for i, sf in enumerate(sub_families):
                    if sf["id"] == existing_ph["sub_family_id"]:
                        default_sf_idx = i
                        break
            ph_sf = st.selectbox("Sub-Family", sf_names, index=default_sf_idx, key="ph_sf")

            submitted = st.form_submit_button("Save Product Hierarchy")
            if submitted:
                if not ph_code:
                    st.error("Hierarchy code is required.")
                else:
                    try:
                        sf_id = sub_families[sf_names.index(ph_sf)]["id"]
                        db.upsert_product_hierarchy(
                            hierarchy_code=ph_code.strip(),
                            hierarchy_description=ph_desc.strip(),
                            sub_family_id=sf_id,
                            ph_id=edit_ph_id,
                        )
                        st.success(f"Product Hierarchy '{ph_code}' saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error: {exc}")

    # ---- CSV Import ----
    with st.expander("Import from CSV / Excel", icon=":material/upload:"):
        st.caption("CSV must have columns: `hierarchy_code`, `hierarchy_description`, `sub_family_code`")
        up_ph = st.file_uploader("Upload Product Hierarchies file", type=["csv", "xlsx"],
                                 key="ph_upload")
        if up_ph:
            df, err = parse_upload(up_ph, required_columns=["hierarchy_code", "sub_family_code"])
            if err:
                st.error(err)
            elif df is not None:
                st.dataframe(df.head(10))
                if st.button("Import Product Hierarchies", key="ph_import_btn"):
                    # Build sub-family code → id map
                    sf_code_map = {sf["code"]: sf["id"] for sf in sub_families}
                    ins, skip, errs = 0, 0, []
                    for idx, row in df.iterrows():
                        r = row.to_dict()
                        sf_code = r.get("sub_family_code", "")
                        if sf_code not in sf_code_map:
                            skip += 1
                            errs.append(f"Row {idx+2}: sub_family_code '{sf_code}' not found")
                            continue
                        try:
                            db.upsert_product_hierarchy(
                                hierarchy_code=r["hierarchy_code"],
                                hierarchy_description=r.get("hierarchy_description", ""),
                                sub_family_id=sf_code_map[sf_code],
                            )
                            ins += 1
                        except Exception as exc:
                            skip += 1
                            errs.append(f"Row {idx+2}: {exc}")
                    st.success(f"Imported {ins}, skipped {skip}.")
                    if errs:
                        st.warning("\n".join(errs[:5]))
                    st.rerun()

    # ---- Data table ----
    if hierarchies:
        st.subheader(f"Product Hierarchies ({len(hierarchies)})")
        disp_cols = ["id", "hierarchy_code", "hierarchy_description", "sub_family_name"]
        disp_df = pd.DataFrame(hierarchies)
        show_cols = [c for c in disp_cols if c in disp_df.columns]
        st.dataframe(disp_df[show_cols], use_container_width=True, hide_index=True)

        # ---- Delete ----
        with st.expander("Delete a Product Hierarchy", icon=":material/delete:"):
            del_opts = [f"{h['hierarchy_code']} - {h.get('hierarchy_description','')}" for h in hierarchies]
            del_sel = st.selectbox("Select to delete", del_opts, key="ph_del_sel")
            if st.button("Delete", key="ph_del_btn", type="primary"):
                idx = del_opts.index(del_sel)
                ok = db.delete_product_hierarchy(hierarchies[idx]["id"])
                if ok:
                    st.success("Deleted.")
                    st.rerun()
                else:
                    st.error("Delete failed.")

        # ---- Export ----
        csv = to_csv_bytes(hierarchies,
                           columns=["hierarchy_code", "hierarchy_description", "sub_family_name"])
        st.download_button("Export Product Hierarchies CSV", csv,
                           file_name="product_hierarchies.csv", mime="text/csv")
    else:
        st.info("No product hierarchies yet. Add one above or import from CSV.")


# ===================================================================
# PAGE: Keywords
# ===================================================================

def page_keywords() -> None:
    st.title("Keywords")

    sub_families = db.list_sub_families()
    keywords = db.list_keywords()

    if not sub_families:
        st.warning("Create at least one Sub-Family before adding Keywords.")
        return

    # ---- Add / Edit form ----
    with st.expander("Add / Edit Keyword", icon=":material/add:"):
        edit_kw_id = None
        if keywords:
            kw_options = ["-- New --"] + [f"{k['keyword']} (pri={k['priority']})" for k in keywords]
            sel = st.selectbox("Select to edit (or New)", kw_options, key="kw_sel")
            if sel != "-- New --":
                idx = kw_options.index(sel) - 1
                edit_kw_id = keywords[idx]["id"]

        existing_kw = None
        if edit_kw_id:
            for k in keywords:
                if k["id"] == edit_kw_id:
                    existing_kw = k
                    break

        with st.form("kw_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            kw_text = c1.text_input("Keyword",
                                    value=existing_kw["keyword"] if existing_kw else "")
            kw_pri = c2.number_input("Priority", min_value=0, max_value=9999,
                                     value=existing_kw["priority"] if existing_kw else 0)

            sf_names = [f"{sf['code']} - {sf['name']}" for sf in sub_families]
            default_sf_idx = 0
            if existing_kw and existing_kw.get("sub_family_id"):
                for i, sf in enumerate(sub_families):
                    if sf["id"] == existing_kw["sub_family_id"]:
                        default_sf_idx = i
                        break
            kw_sf = st.selectbox("Sub-Family", sf_names, index=default_sf_idx, key="kw_sf")

            submitted = st.form_submit_button("Save Keyword")
            if submitted:
                if not kw_text:
                    st.error("Keyword text is required.")
                else:
                    try:
                        sf_id = sub_families[sf_names.index(kw_sf)]["id"]
                        db.upsert_keyword(
                            keyword=kw_text.strip(),
                            sub_family_id=sf_id,
                            priority=int(kw_pri),
                            kw_id=edit_kw_id,
                        )
                        st.success(f"Keyword '{kw_text}' saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error: {exc}")

    # ---- CSV Import ----
    with st.expander("Import from CSV / Excel", icon=":material/upload:"):
        st.caption("CSV must have columns: `keyword`, `sub_family_code`, optionally `priority`")
        up_kw = st.file_uploader("Upload Keywords file", type=["csv", "xlsx"],
                                 key="kw_upload")
        if up_kw:
            df, err = parse_upload(up_kw, required_columns=["keyword", "sub_family_code"])
            if err:
                st.error(err)
            elif df is not None:
                st.dataframe(df.head(10))
                if st.button("Import Keywords", key="kw_import_btn"):
                    sf_code_map = {sf["code"]: sf["id"] for sf in sub_families}
                    ins, skip, errs = 0, 0, []
                    for idx, row in df.iterrows():
                        r = row.to_dict()
                        sf_code = r.get("sub_family_code", "")
                        if sf_code not in sf_code_map:
                            skip += 1
                            errs.append(f"Row {idx+2}: sub_family_code '{sf_code}' not found")
                            continue
                        try:
                            pri = int(r.get("priority", 0) or 0)
                            db.upsert_keyword(
                                keyword=r["keyword"],
                                sub_family_id=sf_code_map[sf_code],
                                priority=pri,
                            )
                            ins += 1
                        except Exception as exc:
                            skip += 1
                            errs.append(f"Row {idx+2}: {exc}")
                    st.success(f"Imported {ins}, skipped {skip}.")
                    if errs:
                        st.warning("\n".join(errs[:5]))
                    st.rerun()

    # ---- Data table ----
    if keywords:
        st.subheader(f"Keywords ({len(keywords)})")
        disp_cols = ["id", "keyword", "sub_family_name", "priority"]
        disp_df = pd.DataFrame(keywords)
        show_cols = [c for c in disp_cols if c in disp_df.columns]
        st.dataframe(disp_df[show_cols], use_container_width=True, hide_index=True)

        # ---- Delete ----
        with st.expander("Delete a Keyword", icon=":material/delete:"):
            del_opts = [f"{k['keyword']} (pri={k['priority']})" for k in keywords]
            del_sel = st.selectbox("Select to delete", del_opts, key="kw_del_sel")
            if st.button("Delete", key="kw_del_btn", type="primary"):
                idx = del_opts.index(del_sel)
                ok = db.delete_keyword(keywords[idx]["id"])
                if ok:
                    st.success("Deleted.")
                    st.rerun()
                else:
                    st.error("Delete failed.")

        # ---- Export ----
        csv = to_csv_bytes(keywords,
                           columns=["keyword", "sub_family_name", "priority"])
        st.download_button("Export Keywords CSV", csv,
                           file_name="keywords.csv", mime="text/csv")
    else:
        st.info("No keywords yet. Add one above or import from CSV.")


# ===================================================================
# Placeholder pages for future phases
# ===================================================================

def page_materials() -> None:
    """Placeholder for materials management (Phase 3)."""
    st.title("Materials")
    st.info(
        "This page will allow uploading, viewing, filtering and editing "
        "spare parts materials. Coming in **Phase 3**."
    )


def page_determination() -> None:
    """Placeholder for sub-family determination (Phase 4)."""
    st.title("Sub-Family Determination")
    st.info(
        "This page will run the 6-step priority-based sub-family "
        "assignment engine. Coming in **Phase 4**."
    )
    st.markdown(
        """
        **Priority chain:**
        1. Product Hierarchy match (first 4 digits)
        2. Predecessor match (ZMMPS)
        3. Material number direct match (11NC/12NC)
        4. Characteristic code match
        5. Profit center match
        6. Keyword match
        7. Default: "Undivided" sub-family
        """
    )


def page_pricing() -> None:
    """Placeholder for price calculation (Phase 5-7)."""
    st.title("Price Calculation")
    st.info(
        "This page will calculate World Reference Prices using the 4 "
        "pricing models. Coming in **Phase 5**."
    )
    st.markdown(
        """
        **Calculation types:**
        - Equipment Equivalent
        - Cost Price Plus
        - Value Based
        - Manual WRP
        """
    )


def page_country_settings() -> None:
    """Placeholder for country settings and country prices (Phase 6)."""
    st.title("Country Settings")
    st.info(
        "This page will manage per-country pricing configuration and "
        "calculate Country Target / List Prices. Coming in **Phase 6**."
    )


# ===================================================================
# PAGE: Logs (Audit Trail)
# ===================================================================

def page_logs() -> None:
    """Audit trail showing all data change activity."""
    st.title("Logs")

    # ---- Controls ----
    limit = st.selectbox("Show last", [25, 50, 100, 250], index=0, key="log_limit")

    audit = db.recent_audit(limit=limit)

    if audit:
        st.caption(f"Showing {len(audit)} most recent entries")
        log_data = []
        for entry in audit:
            log_data.append({
                "Timestamp": entry["created_at"],
                "Action": entry["action"],
                "Table": entry["table_name"],
                "Record ID": entry["record_id"],
                "User": entry.get("user_name") or "",
            })
        st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)
    else:
        st.info("No activity recorded yet. Start by adding master data.")


# ===================================================================
# Navigation
# ===================================================================

pages = {
    "Dashboard": [
        st.Page(page_home, title="Home", icon=":material/dashboard:", default=True),
    ],
    "Master Data": [
        st.Page(page_families, title="Families & Sub-Families", icon=":material/category:"),
        st.Page(page_profit_centers, title="Profit Centers", icon=":material/account_balance:"),
        st.Page(page_characteristics, title="Characteristics", icon=":material/label:"),
        st.Page(page_product_hierarchies, title="Product Hierarchies", icon=":material/account_tree:"),
        st.Page(page_keywords, title="Keywords", icon=":material/search:"),
        st.Page(page_materials, title="Materials", icon=":material/inventory_2:"),
    ],
    "Pricing": [
        st.Page(page_determination, title="Determination", icon=":material/auto_fix_high:"),
        st.Page(page_pricing, title="Price Calculation", icon=":material/calculate:"),
        st.Page(page_country_settings, title="Country Settings", icon=":material/public:"),
    ],
    "Logs": [
        st.Page(page_logs, title="Activity Log", icon=":material/history:"),
    ],
}

nav = st.navigation(pages)
nav.run()
