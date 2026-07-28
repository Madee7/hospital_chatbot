"""
Hospital Admin Dashboard (Streamlit).

Run from repo root:
  streamlit run dashboard/streamlit_app.py

Optional .env:
  ADMIN_DASHBOARD_PASSWORD=changeme
"""

from __future__ import annotations

import csv
import io
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import importlib

from app.core.config import CLINIC_DISPLAY_NAME, DEFAULT_CLINIC_ID, DEFAULT_TENANT_ID
from app.db.database import SessionLocal
from app.services import admin_dashboard_service as admin
from app.services import dashboard_service as dash
from app.services import handover_service
from app.services.booking_service import BookingError
from app.services.reminder_service import process_due_reminders

# Streamlit keeps imported modules in memory across reruns; reload so dashboard picks up service edits.
admin = importlib.reload(admin)
dash = importlib.reload(dash)
handover_service = importlib.reload(handover_service)

from ui_i18n import SCREENS, t as _tr


def _ui(key: str, **kwargs) -> str:
    return _tr(key, st.session_state.get("ui_lang", "en"), **kwargs)


ADMIN_PASSWORD = os.getenv("ADMIN_DASHBOARD_PASSWORD", "admin123")


def _form_nonce(prefix: str) -> int:
    key = f"{prefix}_form_nonce"
    if key not in st.session_state:
        st.session_state[key] = 0
    return int(st.session_state[key])


def _apply_edit_reset(prefix: str, edit_key: str, value: int = 0) -> None:
    """Reset a selectbox session key BEFORE the widget is created."""
    if st.session_state.pop(f"{prefix}_reset_edit", False):
        st.session_state[edit_key] = value


def _after_save(prefix: str, msg: str, *, reset_edit: bool = True) -> None:
    """Clear form + optional edit selector, show flash on next run."""
    st.session_state[f"{prefix}_form_nonce"] = _form_nonce(prefix) + 1
    if reset_edit:
        st.session_state[f"{prefix}_reset_edit"] = True
    st.session_state[f"{prefix}_save_msg"] = msg
    st.rerun()


def _show_flash(prefix: str) -> None:
    msg = st.session_state.pop(f"{prefix}_save_msg", None)
    if msg:
        st.success(msg)

st.set_page_config(
    page_title=f"{CLINIC_DISPLAY_NAME} Admin",
    page_icon="🏥",
    layout="wide",
)


_CLOCK_COLUMNS = {
    "start_time",
    "end_time",
    "slot_start",
    "slot_end",
    "start_datetime",
    "end_datetime",
    "sent_at",
    "scheduled_at",
    "hold_expires_at",
    "created_at",
    "updated_at",
    "timestamp",
}


def _ui_lang() -> str:
    return st.session_state.get("ui_lang", "en")


def _fmt_clock_value(value) -> str:
    from app.core.time_format import format_datetime_12h, format_time_12h

    lang = _ui_lang()
    if isinstance(value, time):
        return format_time_12h(value, lang)
    if isinstance(value, datetime):
        return format_datetime_12h(value, lang)
    if isinstance(value, str) and value:
        # ISO / "YYYY-MM-DD HH:MM" coming from services
        if "T" in value or (len(value) >= 16 and value[10] in " T"):
            return format_datetime_12h(value, lang)
        if len(value) <= 8 and ":" in value:
            return format_datetime_12h(value, lang)
    return value


def _display_rows(rows: list[dict]) -> list[dict]:
    """Copy rows with clock fields rendered in 12-hour format."""
    out: list[dict] = []
    for row in rows:
        copy = dict(row)
        for key, val in list(copy.items()):
            if key in _CLOCK_COLUMNS or isinstance(val, (datetime, time)):
                copy[key] = _fmt_clock_value(val)
        out.append(copy)
    return out


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(_display_rows(rows)) if rows else pd.DataFrame()


def _time_select(
    label: str,
    *,
    default: time,
    step_minutes: int = 15,
    include_end_of_day: bool = False,
    key: str | None = None,
) -> time:
    """Selectbox with 12-hour labels (Streamlit time_input follows 24h browser locale)."""
    from app.core.time_format import format_time_12h, iter_clock_times, nearest_clock_time

    choices = iter_clock_times(step_minutes=step_minutes, include_end_of_day=include_end_of_day)
    default = nearest_clock_time(default, choices)
    return st.selectbox(
        label,
        options=choices,
        index=choices.index(default),
        format_func=lambda t: format_time_12h(t, _ui_lang()),
        key=key,
    )


def _clock_label(value) -> str:
    return str(_fmt_clock_value(value))


def _csv_download(rows: list[dict], filename: str) -> None:
    if not rows:
        st.caption("No rows to export.")
        return
    display = _display_rows(rows)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(display[0].keys()))
    writer.writeheader()
    for row in display:
        writer.writerow(row)
    st.download_button(
        "Export CSV",
        data=buf.getvalue().encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
    )


def _db():
    return SessionLocal()


def require_login() -> bool:
    if "ui_lang" not in st.session_state:
        st.session_state["ui_lang"] = "en"
    st.sidebar.selectbox(
        _ui("lang"),
        options=["en", "ar"],
        format_func=lambda c: _ui("ui_lang_en") if c == "en" else _ui("ui_lang_ar"),
        key="ui_lang",
    )
    if st.session_state.get("auth"):
        return True
    st.title(_ui("login_title"))
    email = st.text_input(_ui("email"), value="admin@clinic.local")
    password = st.text_input(_ui("password"), type="password")
    if st.button(_ui("login"), type="primary"):
        db = _db()
        try:
            user = admin.authenticate_admin(db, email=email, password=password, expected_password=ADMIN_PASSWORD)
        finally:
            db.close()
        if not user:
            st.error("Invalid credentials.")
            return False
        st.session_state["auth"] = user
        st.rerun()
    return False


def page_kpis(db, clinic_id: int) -> None:
    st.subheader(_ui("dashboard_kpis"))
    days = st.slider(_ui("period_days"), 7, 90, 30)
    k = admin.compute_kpis(db, clinic_id=clinic_id, days=days)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(_ui("conversations_m"), k["total_conversations"])
    c2.metric(_ui("booking_attempts"), k["booking_attempts"])
    c3.metric(_ui("confirmed"), k["confirmed_bookings"])
    c4.metric(_ui("conversion"), f"{k['booking_conversion_rate'] * 100:.1f}%")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric(_ui("cancelled"), k["cancelled_appointments"])
    c6.metric(_ui("rescheduled"), k["rescheduled_appointments"])
    c7.metric(_ui("no_shows"), k["no_shows"])
    c8.metric(_ui("failed_intents"), k["failed_intents"])

    c9, c10, c11, c12 = st.columns(4)
    c9.metric(_ui("voice_notes"), k["voice_usage_count"])
    c10.metric(_ui("voice_minutes"), k["voice_usage_minutes"])
    c11.metric(_ui("handover_open"), k["handover_open"])
    c12.metric(_ui("est_cost"), f"${k['estimated_cost']:.4f}")

    c13, c14, _, _ = st.columns(4)
    c13.metric(_ui("voice_cost"), f"${k.get('voice_estimated_cost', 0.0):.4f}")
    c14.metric(_ui("voice_cost_avg"), f"${k.get('voice_cost_avg', 0.0):.4f}")

    left, right = st.columns(2)
    with left:
        st.markdown(f"**{_ui('top_doctors')}**")
        st.dataframe(_df(k["top_doctors"]), use_container_width=True, hide_index=True)
        st.markdown(f"**{_ui('reminders_by_status')}**")
        st.json(k["reminders"])
    with right:
        st.markdown(f"**{_ui('top_specialties')}**")
        st.dataframe(_df(k["top_specialties"]), use_container_width=True, hide_index=True)
        st.caption(_ui("handover_closed", n=k["handover_closed"]))


def page_clinic(db, clinic_id: int) -> None:
    st.subheader(_ui("clinic_setup"))
    clinic = admin.get_clinic(db, clinic_id)
    if not clinic:
        st.error("Clinic not found")
        return
    cfg = admin.get_config_map(db, clinic_id)
    _show_flash("clinic")

    lang_val = clinic.language_default.value if hasattr(clinic.language_default, "value") else clinic.language_default
    lang_options = ["ar", "ar-EG", "en"]
    lang_index = lang_options.index(lang_val) if lang_val in lang_options else 0
    nonce = _form_nonce("clinic")
    with st.form(f"clinic_form_{nonce}"):
        name = st.text_input("Clinic name", value=clinic.clinic_name or "")
        whatsapp = st.text_input("WhatsApp number", value=clinic.whatsapp_number or "")
        tz = st.text_input("Timezone", value=clinic.timezone or "Africa/Cairo")
        lang = st.selectbox("Default language", options=lang_options, index=lang_index)
        address = st.text_area("Location / address", value=clinic.address or "")
        maps_url = st.text_input(
            "Google Maps URL",
            value=cfg.get("clinic_maps_url", ""),
            help="Patients receive a shortened version of this link in booking messages.",
        )
        if maps_url.strip():
            from app.services.clinic_settings_service import shorten_google_maps_url

            st.caption(
                f"Short link sent to patients: {shorten_google_maps_url(maps_url)}"
            )
        logo = st.text_input("Logo URL (config)", value=cfg.get("clinic_logo_url", ""))
        hours = st.text_input(
            "Business hours (config)",
            value=cfg.get("business_hours", "Sun-Thu 9:00 AM-5:00 PM"),
        )
        status = st.selectbox(
            "Status",
            options=["active", "inactive"],
            index=0 if (clinic.status or "active") == "active" else 1,
        )
        if st.form_submit_button("Save clinic", type="primary"):
            admin.update_clinic(
                db,
                clinic_id,
                {
                    "clinic_name": name,
                    "whatsapp_number": whatsapp,
                    "timezone": tz,
                    "language_default": lang,
                    "address": address,
                    "status": status,
                },
            )
            admin.set_config(
                db,
                clinic_id=clinic_id,
                tenant_id=clinic.tenant_id,
                key="clinic_logo_url",
                value=logo,
            )
            admin.set_config(
                db,
                clinic_id=clinic_id,
                tenant_id=clinic.tenant_id,
                key="business_hours",
                value=hours,
            )
            admin.set_config(
                db,
                clinic_id=clinic_id,
                tenant_id=clinic.tenant_id,
                key="clinic_maps_url",
                value=maps_url.strip(),
            )
            _after_save("clinic", "Clinic saved.", reset_edit=False)

    st.markdown("### Clinic holidays (BR-012)")
    holidays = admin.list_clinic_holidays(db, clinic_id)
    st.dataframe(_df(holidays), use_container_width=True, hide_index=True)
    with st.form("clinic_holiday_form"):
        h_start = st.date_input("Holiday start date")
        h_end = st.date_input("Holiday end date")
        h_reason = st.text_input("Reason", value="Clinic closed")
        if st.form_submit_button("Add holiday / closure"):
            try:
                start_dt = datetime.combine(h_start, time.min)
                end_dt = datetime.combine(h_end, time.max)
                result = admin.add_clinic_holiday(
                    db,
                    clinic_id=clinic_id,
                    start_datetime=start_dt,
                    end_datetime=end_dt,
                    reason=h_reason,
                )
                st.success(
                    f"Holiday saved (id={result['holiday_id']}), "
                    f"blocked {result['slots_blocked']} open slots."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if holidays:
        hid = st.selectbox(
            "Deactivate holiday",
            options=[0] + [h["holiday_id"] for h in holidays if h.get("active_flag")],
            format_func=lambda i: "(none)" if i == 0 else f"#{i}",
        )
        if hid and st.button("Deactivate selected holiday"):
            admin.deactivate_clinic_holiday(db, clinic_id=clinic_id, holiday_id=hid)
            st.success("Holiday deactivated.")
            st.rerun()


def page_departments(db, clinic_id: int) -> None:
    st.subheader(_ui("departments_title"))
    rows = admin.list_departments(db, clinic_id)
    st.dataframe(_df(rows), use_container_width=True, hide_index=True)
    _show_flash("dept")

    st.markdown("### Add / edit")
    _apply_edit_reset("dept", "dept_edit_id")
    edit_id = st.selectbox(
        "Edit existing (optional)",
        options=[0] + [r["department_id"] for r in rows],
        format_func=lambda i: "(new)" if i == 0 else f"#{i}",
        key="dept_edit_id",
    )
    current = next((r for r in rows if r["department_id"] == edit_id), None)
    nonce = _form_nonce("dept")
    with st.form(f"dept_form_{nonce}"):
        name_en = st.text_input("Name (EN)", value=(current or {}).get("name_en") or "")
        name_ar = st.text_input("Name (AR)", value=(current or {}).get("name_ar") or "")
        desc = st.text_area("Description", value=(current or {}).get("description") or "")
        active = st.checkbox("Active", value=(current or {}).get("active_flag", True))
        if st.form_submit_button("Save department"):
            admin.upsert_department(
                db,
                clinic_id=clinic_id,
                name_en=name_en,
                name_ar=name_ar,
                description=desc,
                active_flag=active,
                department_id=edit_id or None,
            )
            _after_save("dept", "Department saved. Form cleared for next entry.")


def page_doctors(db, clinic_id: int) -> None:
    st.subheader(_ui("doctors"))
    clinic = admin.get_clinic(db, clinic_id)
    docs = admin.list_doctors(db, clinic_id)
    depts = admin.list_departments(db, clinic_id)
    st.dataframe(_df(docs), use_container_width=True, hide_index=True)
    _show_flash("doctor")

    if not depts:
        st.warning("Create a department first (Departments screen), then add doctors.")
        return

    _apply_edit_reset("doctor", "doctor_edit_id")

    edit_id = st.selectbox(
        "Edit doctor",
        options=[0] + [d["doctor_id"] for d in docs],
        format_func=lambda i: "(new)"
        if i == 0
        else next(
            (
                f"#{i} — {x['name_ar'] or x['name_en'] or 'Doctor'}"
                for x in docs
                if x["doctor_id"] == i
            ),
            f"#{i}",
        ),
        key="doctor_edit_id",
    )
    current = next((d for d in docs if d["doctor_id"] == edit_id), None)
    dept_ids = [d["department_id"] for d in depts]
    default_dept = (current or {}).get("department_id")
    dept_index = dept_ids.index(default_dept) if default_dept in dept_ids else 0
    form_nonce = _form_nonce("doctor")
    with st.form(f"doctor_form_{form_nonce}"):
        name_ar = st.text_input("Name AR", value=(current or {}).get("name_ar") or "")
        name_en = st.text_input("Name EN", value=(current or {}).get("name_en") or "")
        title = st.text_input("Title", value=(current or {}).get("title") or "")
        specialization = st.text_input(
            "Specialization", value=(current or {}).get("specialization") or ""
        )
        bio = st.text_area("Bio (AR)", value=(current or {}).get("bio") or "")
        bio_en = st.text_area("Bio (EN)", value=(current or {}).get("bio_en") or "")
        photo_url = st.text_input("Photo URL", value=(current or {}).get("photo_url") or "")
        dept = st.selectbox(
            "Department (required)",
            options=dept_ids,
            format_func=lambda i: next(
                (f"{x['name_ar'] or x['name_en']} (#{i})" for x in depts if x["department_id"] == i),
                str(i),
            ),
            index=dept_index,
        )
        active = st.checkbox("Active", value=(current or {}).get("active_flag", True))
        save = st.form_submit_button("Save doctor")
        if save:
            try:
                admin.upsert_doctor(
                    db,
                    clinic_id=clinic_id,
                    tenant_id=clinic.tenant_id if clinic else DEFAULT_TENANT_ID,
                    name_en=name_en,
                    name_ar=name_ar,
                    title=title,
                    specialization=specialization,
                    bio=bio,
                    bio_en=bio_en or None,
                    photo_url=photo_url or None,
                    department_id=dept,
                    active_flag=active,
                    doctor_id=edit_id or None,
                )
                action = "added" if not edit_id else "updated"
                _after_save("doctor", f"Doctor {action}. Form cleared for next entry.")
            except ValueError as exc:
                st.error(str(exc))

    with st.expander("Reindex doctor IDs (close gaps)"):
        st.caption("مثال: بعد الحذف 1,2,3,4,8 → 1,2,3,4,5 مع تحديث الحجوزات المرتبطة.")
        if st.button("Reindex now"):
            try:
                mapping = admin.resequence_doctor_ids(db)
                db.commit()
                _after_save("doctor", f"Reindexed {len(mapping)} doctors.")
            except Exception as exc:
                db.rollback()
                st.error(str(exc))

    if edit_id:
        st.markdown("### Remove doctor")
        try:
            impact = admin.doctor_delete_impact(db, clinic_id, edit_id)
        except ValueError as exc:
            st.error(str(exc))
            return

        st.warning(
            f"Doctor #{edit_id}: linked data — "
            f"{impact['appointments']} appointments, "
            f"{impact['slots']} slots, "
            f"{impact['reminders']} reminders.\n\n"
            "الحذف النهائي سيمسح كل بيانات الحجز المرتبطة بهذا الدكتور. "
            "التعطيل يخفيه من البوت ويبقي الحجوزات."
        )
        confirm = st.checkbox(
            "Confirm: I understand permanent delete removes booking data",
            key=f"doctor_del_confirm_{edit_id}",
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Deactivate (recommended)", use_container_width=True):
                try:
                    admin.deactivate_doctor(db, clinic_id, edit_id)
                    _after_save("doctor", f"Doctor #{edit_id} deactivated.")
                except ValueError as exc:
                    st.error(str(exc))
        with c2:
            if st.button(
                "Permanently delete",
                type="primary",
                use_container_width=True,
                disabled=not confirm,
            ):
                try:
                    deleted = admin.delete_doctor(db, clinic_id, edit_id)
                    _after_save(
                        "doctor",
                        f"Doctor #{edit_id} deleted "
                        f"({deleted['appointments']} appointments removed).",
                    )
                except Exception as exc:
                    st.error(str(exc))


def page_working_hours(db, clinic_id: int) -> None:
    st.subheader(_ui("working_title"))
    docs = admin.list_doctors(db, clinic_id)
    if not docs:
        st.info("Add doctors first.")
        return
    _show_flash("wh")
    lang = _ui_lang()
    doctor_id = st.selectbox(
        "Doctor / الطبيب",
        options=[d["doctor_id"] for d in docs],
        format_func=lambda i: next(
            (f"{x['name_ar'] or x['name_en']} (#{i})" for x in docs if x["doctor_id"] == i),
            str(i),
        ),
        key="wh_doctor_id",
    )

    tab_hours, tab_leave = st.tabs(
        [
            "⏰ Working hours / ساعات العمل",
            "🏖️ Holidays & leave / أيام العطلة",
        ]
    )

    with tab_hours:
        st.caption(
            "حدّد أيام الأسبوع اللي الطبيب بيشتغل فيها (الإثنين…الأحد) ووقت البداية والنهاية. "
            "بعد الحفظ تتولَّد مواعيد واتساب تلقائياً."
            if lang.startswith("ar")
            else "Set weekly days and times the doctor works. Slots are generated for WhatsApp after save."
        )
        hours = admin.list_working_hours(db, doctor_id)
        display_hours = []
        for h in hours:
            row = dict(h)
            row["weekday_name"] = (
                row.get("weekday_name_ar") if lang.startswith("ar") else row.get("weekday_name")
            )
            display_hours.append(row)
        st.dataframe(_df(display_hours), use_container_width=True, hide_index=True)

        active_hours = [h for h in hours if h.get("active_flag")]
        if active_hours:
            rm = st.selectbox(
                "Deactivate a working day / إلغاء يوم شغل",
                options=[0] + [h["working_hours_id"] for h in active_hours],
                format_func=lambda i: "(none)"
                if i == 0
                else next(
                    (
                        f"#{h['working_hours_id']} · "
                        f"{admin.weekday_label(h['weekday'], lang)} · "
                        f"{_clock_label(h['start_time'])}–{_clock_label(h['end_time'])}"
                        for h in active_hours
                        if h["working_hours_id"] == i
                    ),
                    str(i),
                ),
                key="wh_deactivate_pick",
            )
            if rm and st.button("Deactivate selected day"):
                admin.deactivate_working_hours(
                    db, working_hours_id=int(rm), doctor_id=doctor_id
                )
                st.success("Working day deactivated.")
                st.rerun()

        wh_nonce = _form_nonce("wh")
        with st.form(f"wh_form_{wh_nonce}"):
            weekday = st.selectbox(
                "Weekday / يوم الأسبوع",
                options=list(range(7)),
                format_func=lambda i: admin.weekday_label(i, lang),
            )
            start = _time_select("Start / من", default=time(9, 0), key=f"wh_start_{wh_nonce}")
            end = _time_select("End / إلى", default=time(17, 0), key=f"wh_end_{wh_nonce}")
            slot_minutes = st.number_input(
                "Slot length (min) / مدة الموعد", min_value=10, max_value=120, value=30
            )
            max_bookings = st.number_input(
                "Max bookings / slot", min_value=1, max_value=10, value=1
            )
            active = st.checkbox("Active / مفعّل", value=True)
            if st.form_submit_button("Save working hours / حفظ ساعات العمل", type="primary"):
                try:
                    result = admin.upsert_working_hours(
                        db,
                        doctor_id=doctor_id,
                        weekday=weekday,
                        start_time=start,
                        end_time=end,
                        slot_minutes=int(slot_minutes),
                        max_bookings=int(max_bookings),
                        active_flag=active,
                    )
                    _after_save(
                        "wh",
                        f"Saved {admin.weekday_label(weekday, lang)} "
                        f"· new slots: {result.get('slots_created', 0)}",
                        reset_edit=False,
                    )
                except Exception as exc:
                    st.error(str(exc))

    with tab_leave:
        st.caption(
            "أيام عطلة/إجازة للطبيب بتواريخ محددة (تغلق المواعيد في الواتساب لهذا الطبيب فقط). "
            "عطلة العيادة كلها من شاشة Clinic setup."
            if lang.startswith("ar")
            else "Doctor leave on specific dates (hides that doctor's WhatsApp slots). "
            "Clinic-wide closures are under Clinic setup."
        )
        blocked = admin.list_unavailability(db, doctor_id)
        st.dataframe(_df(blocked), use_container_width=True, hide_index=True)

        active_blocks = [b for b in blocked if b.get("active_flag")]
        if active_blocks:
            bid = st.selectbox(
                "Remove a leave period / إلغاء عطلة",
                options=[0] + [b["unavailability_id"] for b in active_blocks],
                format_func=lambda i: "(none)"
                if i == 0
                else next(
                    (
                        f"#{b['unavailability_id']} · {_clock_label(b['start_datetime'])} → "
                        f"{_clock_label(b['end_datetime'])} · {b.get('reason') or '-'}"
                        for b in active_blocks
                        if b["unavailability_id"] == i
                    ),
                    str(i),
                ),
                key="unavail_deactivate_pick",
            )
            if bid and st.button("Remove leave / إزالة العطلة"):
                admin.deactivate_unavailability(db, unavailability_id=int(bid))
                st.success("Leave removed.")
                st.rerun()

        un_nonce = _form_nonce("unavail")
        with st.form(f"unavail_form_{un_nonce}"):
            d1 = st.date_input("From date / من تاريخ", value=date.today())
            d2 = st.date_input("To date / إلى تاريخ", value=date.today())
            st.caption("Leave times empty at defaults for a full-day holiday.")
            t1 = _time_select(
                "From time / من ساعة",
                default=time(0, 0),
                include_end_of_day=True,
                key=f"un_t1_{un_nonce}",
            )
            t2 = _time_select(
                "To time / إلى ساعة",
                default=time(23, 59),
                include_end_of_day=True,
                key=f"un_t2_{un_nonce}",
            )
            reason = st.text_input("Reason / السبب", value="Doctor leave")
            if st.form_submit_button("Add holiday / leave / إضافة عطلة", type="primary"):
                try:
                    result = admin.add_unavailability(
                        db,
                        doctor_id=doctor_id,
                        start_datetime=datetime.combine(d1, t1),
                        end_datetime=datetime.combine(d2, t2),
                        reason=reason,
                    )
                    st.session_state["unavail_form_nonce"] = un_nonce + 1
                    st.session_state["wh_save_msg"] = (
                        f"Leave saved · blocked slots: {result.get('slots_blocked', 0)}"
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def page_doctor_schedule(db, clinic_id: int) -> None:
    st.subheader(_ui("schedule_title"))
    docs = admin.list_doctors(db, clinic_id)
    if not docs:
        st.info("Add doctors first.")
        return
    doctor_id = st.selectbox(
        "Doctor / الطبيب",
        options=[d["doctor_id"] for d in docs],
        format_func=lambda i: next(
            (f"{x['name_ar'] or x['name_en']} (#{i})" for x in docs if x["doctor_id"] == i),
            str(i),
        ),
        key="schedule_doctor_id",
    )
    days = st.slider("Days ahead / الأيام القادمة", min_value=1, max_value=30, value=14)
    schedule = dash.list_doctor_schedule(
        db, clinic_id=clinic_id, doctor_id=doctor_id, days_ahead=int(days)
    )
    counts = schedule.get("counts") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Free / فاضي", counts.get("free", 0))
    c2.metric("Booked / محجوز", counts.get("booked", 0))
    c3.metric("Held / مؤقت", counts.get("held", 0))
    c4.metric("Blocked / مغلق", counts.get("blocked", 0))

    st.caption(
        "الموعد المؤكد (Booked) ما يظهر لحد تاني في الواتساب إلا بعد الإلغاء."
        if _ui_lang().startswith("ar")
        else "Confirmed (Booked) slots stay hidden from WhatsApp until cancelled."
    )

    tab_booked, tab_free, tab_held = st.tabs(
        ["Booked / محجوز", "Free / فاضي", "Held / مؤقت"]
    )
    with tab_booked:
        st.dataframe(_df(schedule.get("booked") or []), use_container_width=True, hide_index=True)
        _csv_download(schedule.get("booked") or [], f"booked_doctor_{doctor_id}.csv")
    with tab_free:
        st.dataframe(
            _df(schedule.get("free_slots") or []), use_container_width=True, hide_index=True
        )
        _csv_download(schedule.get("free_slots") or [], f"free_doctor_{doctor_id}.csv")
    with tab_held:
        st.dataframe(_df(schedule.get("held") or []), use_container_width=True, hide_index=True)


def page_appointments(db, clinic_id: int) -> None:
    st.subheader(_ui("appointments"))
    status_filter = st.selectbox(
        "Status filter",
        options=["(all)", "confirmed", "cancelled", "draft", "completed", "no_show", "rescheduled"],
    )
    status = None if status_filter == "(all)" else status_filter
    appts = dash.list_appointments(db, clinic_id=clinic_id, status=status, limit=300)
    st.dataframe(_df(appts), use_container_width=True, hide_index=True)
    _csv_download(appts, f"appointments_clinic_{clinic_id}.csv")

    actionable = [a for a in appts if a["status"] in {"confirmed", "rescheduled"}]
    if not actionable:
        return

    st.markdown("### Cancel")
    labels = {
        f"{a['appointment_ref']} | {a['patient_name']} | {_clock_label(a['slot_start'])}": a
        for a in actionable
    }
    pick = st.selectbox("Appointment", options=list(labels.keys()), key="appt_pick")
    if st.button("Cancel appointment", type="primary"):
        try:
            result = dash.dashboard_cancel_appointment(
                db, clinic_id=clinic_id, appointment_id=labels[pick]["appointment_id"]
            )
            st.success(f"Cancelled {result['appointment_ref']}")
            st.rerun()
        except BookingError as exc:
            st.error(str(exc))

    st.markdown("### Reschedule")
    appt = labels[pick]
    doctor_id = appt.get("doctor_id")
    if doctor_id:
        slots = admin.available_slots_for_doctor(db, doctor_id, clinic_id)
        slot_labels = {
            f"{s['date']} {_clock_label(s['slot_start'])} (#{s['slot_id']})": s["slot_id"]
            for s in slots[:40]
        }
        if slot_labels:
            new_slot = st.selectbox("New slot", options=list(slot_labels.keys()))
            if st.button("Confirm reschedule"):
                try:
                    result = admin.dashboard_reschedule(
                        db,
                        clinic_id=clinic_id,
                        appointment_id=appt["appointment_id"],
                        new_slot_id=slot_labels[new_slot],
                    )
                    st.success(
                        f"Rescheduled {result['appointment_ref']} → {_clock_label(result['slot_start'])}"
                    )
                    st.rerun()
                except BookingError as exc:
                    st.error(str(exc))
        else:
            st.caption("No alternate slots for this doctor.")
    else:
        st.caption("doctor_id missing on appointment row.")

    st.markdown("### Mark no-show (BR-010)")
    past_confirmed = []
    now = datetime.utcnow()
    for a in actionable:
        try:
            start = datetime.fromisoformat(str(a["slot_start"]).replace("Z", ""))
        except Exception:
            continue
        if start <= now:
            past_confirmed.append(a)
    if past_confirmed:
        ns_labels = {
            f"{a['appointment_ref']} | {a['patient_name']} | {_clock_label(a['slot_start'])}": a
            for a in past_confirmed
        }
        ns_pick = st.selectbox("Past appointment", options=list(ns_labels.keys()), key="noshow_pick")
        if st.button("Mark as no-show"):
            try:
                result = admin.dashboard_mark_no_show(
                    db,
                    clinic_id=clinic_id,
                    appointment_id=ns_labels[ns_pick]["appointment_id"],
                )
                st.success(f"Marked no-show: {result['appointment_ref']}")
                st.rerun()
            except BookingError as exc:
                st.error(str(exc))
    else:
        st.caption("No past confirmed appointments eligible for no-show.")

    st.markdown("### History")
    hist_opts = {
        f"{a['appointment_ref']} ({a['status']})": a["appointment_id"] for a in appts
    }
    if hist_opts:
        hid = st.selectbox("Appointment history", options=list(hist_opts.keys()), key="hist")
        st.dataframe(
            _df(dash.list_appointment_history(db, appointment_id=hist_opts[hid])),
            use_container_width=True,
            hide_index=True,
        )


def page_conversations(db, clinic_id: int) -> None:
    st.subheader(_ui("conversations"))
    convs = dash.list_conversations(db, clinic_id=clinic_id, limit=100)
    q = st.text_input("Search phone / intent")
    if q:
        ql = q.lower()
        convs = [
            c
            for c in convs
            if ql in str(c.get("phone") or "").lower()
            or ql in str(c.get("current_intent") or "").lower()
            or ql in str(c.get("state") or "").lower()
        ]
    st.dataframe(_df(convs), use_container_width=True, hide_index=True)
    if not convs:
        return
    options = {
        f"#{c['conversation_id']} {c['phone']} [{c['state']}] intent={c.get('current_intent')}": c[
            "conversation_id"
        ]
        for c in convs
    }
    pick = st.selectbox("Transcript", options=list(options.keys()))
    msgs = dash.list_messages(db, conversation_id=options[pick])
    st.dataframe(_df(msgs), use_container_width=True, hide_index=True)

    st.markdown("### Handover cases")
    hs = st.selectbox("Handover status", ["open", "in_progress", "closed", "(all)"])
    rows = handover_service.list_handovers(db, status=None if hs == "(all)" else hs)
    st.dataframe(_df(rows), use_container_width=True, hide_index=True)


def page_reminders(db, clinic_id: int) -> None:
    st.subheader(_ui("reminders"))
    rems = dash.list_reminders(db, clinic_id=clinic_id)
    st.dataframe(_df(rems), use_container_width=True, hide_index=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Process due"):
            st.write(process_due_reminders(db, force_all_pending=False))
            st.rerun()
    with c2:
        if st.button("Force all pending (demo)"):
            st.write(process_due_reminders(db, force_all_pending=True))
            st.rerun()
    with c3:
        if st.button("Retry failed"):
            sent = admin.retry_failed_reminders(db, clinic_id)
            st.success(f"Retried / sent: {sent}")
            st.rerun()


def page_settings(db, clinic_id: int) -> None:
    st.subheader(_ui("settings"))
    clinic = admin.get_clinic(db, clinic_id)
    if not clinic:
        st.error("Clinic not found")
        return
    cfg = admin.get_config_map(db, clinic_id)
    _show_flash("settings")
    defaults = {
        "reminder_hours_before": cfg.get("reminder_hours_before", "24,2"),
        "reminder_template": cfg.get("reminder_template", "appointment_reminder"),
        "escalation_whatsapp": cfg.get("escalation_whatsapp", ""),
        "fallback_wording": cfg.get(
            "fallback_wording",
            "لم أفهم طلبك. اكتب MENU أو اختر من القائمة.",
        ),
        "consent_text": cfg.get(
            "consent_text",
            "بالمتابعة، توافق على التواصل عبر واتساب لإدارة المواعيد.",
        ),
    }
    nonce = _form_nonce("settings")
    with st.form(f"settings_form_{nonce}"):
        rem_hours = st.text_input("Reminder hours before (comma)", value=defaults["reminder_hours_before"])
        rem_tpl = st.text_input("Reminder template name", value=defaults["reminder_template"])
        esc = st.text_input("Escalation WhatsApp number", value=defaults["escalation_whatsapp"])
        fallback = st.text_area("Fallback wording", value=defaults["fallback_wording"])
        consent = st.text_area("Consent text", value=defaults["consent_text"])
        if st.form_submit_button("Save settings", type="primary"):
            for key, value in {
                "reminder_hours_before": rem_hours,
                "reminder_template": rem_tpl,
                "escalation_whatsapp": esc,
                "fallback_wording": fallback,
                "consent_text": consent,
            }.items():
                admin.set_config(
                    db,
                    clinic_id=clinic_id,
                    tenant_id=clinic.tenant_id,
                    key=key,
                    value=value,
                )
            _after_save("settings", "Settings saved.", reset_edit=False)


def page_usage(db, clinic_id: int) -> None:
    st.subheader(_ui("usage"))
    days = st.slider("Period (days)", 7, 90, 30, key="usage_days")
    wa_stats = admin.whatsapp_message_stats(db, clinic_id, days=days)
    failed = admin.usage_failure_count(db, clinic_id, days=days)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("WhatsApp inbound", wa_stats["inbound"])
    c2.metric("WhatsApp outbound", wa_stats["outbound"])
    c3.metric("WhatsApp total", wa_stats["total"])
    c4.metric("Failed API calls", failed)

    summary = admin.usage_summary(db, clinic_id, days=days)
    st.markdown("**By provider / operation**")
    st.dataframe(_df(summary), use_container_width=True, hide_index=True)
    total = sum(r["cost_estimate"] for r in summary)
    st.metric("Estimated cost (period)", f"${total:.4f}")
    st.markdown("**Recent usage logs**")
    st.dataframe(_df(admin.list_usage(db, clinic_id)), use_container_width=True, hide_index=True)


def main() -> None:
    if not require_login():
        return

    user = st.session_state["auth"]
    st.sidebar.markdown(f"**{user.get('email')}** · `{user.get('role')}`")
    if st.sidebar.button(_ui("logout")):
        lang = st.session_state.get("ui_lang", "en")
        st.session_state.clear()
        st.session_state["ui_lang"] = lang
        st.rerun()

    clinics = []
    db = _db()
    try:
        clinics = admin.list_clinics(db)
    finally:
        db.close()

    clinic_options = {f"{c['clinic_name'] or 'Clinic'} (#{c['clinic_id']})": c["clinic_id"] for c in clinics}
    if not clinic_options:
        clinic_options = {f"Clinic #{DEFAULT_CLINIC_ID}": DEFAULT_CLINIC_ID}

    clinic_label = st.sidebar.selectbox(_ui("clinic"), options=list(clinic_options.keys()))
    clinic_id = clinic_options[clinic_label]

    screen_keys = [k for k, _ in SCREENS]
    page_key = st.sidebar.radio(
        _ui("screen"),
        options=screen_keys,
        format_func=lambda k: _ui(k),
    )
    if st.sidebar.button(_ui("refresh"), use_container_width=True):
        st.rerun()

    st.title(_ui("admin_title", name=CLINIC_DISPLAY_NAME))
    st.caption(_ui("clinic_caption", id=clinic_id, page=_ui(page_key)))

    db = _db()
    try:
        if page_key == "kpis":
            page_kpis(db, clinic_id)
        elif page_key == "clinic_setup":
            page_clinic(db, clinic_id)
        elif page_key == "departments":
            page_departments(db, clinic_id)
        elif page_key == "doctors":
            page_doctors(db, clinic_id)
        elif page_key == "working_hours":
            page_working_hours(db, clinic_id)
        elif page_key == "doctor_schedule":
            page_doctor_schedule(db, clinic_id)
        elif page_key == "appointments":
            page_appointments(db, clinic_id)
        elif page_key == "conversations":
            page_conversations(db, clinic_id)
        elif page_key == "reminders":
            page_reminders(db, clinic_id)
        elif page_key == "settings":
            page_settings(db, clinic_id)
        elif page_key == "usage":
            page_usage(db, clinic_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
