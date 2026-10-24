"""HCM Lite - Streamlit UI.  Run:  streamlit run app.py"""
import calendar
import html as _html
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

import logic as L

st.set_page_config(page_title="HCM Lite", page_icon="🏢", layout="wide")
st.markdown("""<style>
[data-testid="stSidebar"]{background:#0f1f3d}
[data-testid="stSidebar"] *{color:#e8eefc !important}
[data-testid="stMetric"]{background:#fff;border:1px solid #e3e8f0;border-radius:12px;
  padding:12px 16px;box-shadow:0 1px 3px rgba(15,31,61,.06)}
[data-testid="stMetricLabel"] p{color:#475569 !important}
[data-testid="stMetricValue"]{color:#0f1f3d !important}
.stButton>button,.stDownloadButton>button{border-radius:8px}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def flash(msg, kind="success"):
    st.session_state["_flash"] = (kind, msg)


def show_flash():
    f = st.session_state.pop("_flash", None)
    if f:
        getattr(st, f[0])(f[1])


def show_errors(errs):
    for field, msg in errs.items():
        st.error(f"**{field.replace('_', ' ').title()}:** {msg}")


def go(page):
    st.session_state["nav"] = page


def fmt_t(t):
    return datetime.strptime(t, "%H:%M:%S").strftime("%I:%M %p") if t else "—"


def money(x):
    return f"Rs. {x:,.0f}"


def current_user():
    uid = st.session_state.get("uid")
    if not uid:
        token = st.query_params.get("s")
        uid = L.session_user_id(token) if token else None
        if uid:
            st.session_state["uid"] = uid
    user = L.get_user(uid) if uid else None
    if user and user.get("active", True):
        return user
    st.session_state.pop("uid", None)
    return None


def logout():
    token = st.query_params.get("s")
    if token:
        L.delete_session(token)
    st.query_params.clear()
    for k in ("uid", "nav", "chat"):
        st.session_state.pop(k, None)


# ------------------------------------------------------------------ setup / login
def setup_page():
    st.title("🏢 Welcome to HCM Lite")
    st.subheader("First-time setup: create your company and Admin account")
    with st.form("setup"):
        f = {"company": st.text_input("Company name"),
             "name": st.text_input("Admin full name"),
             "email": st.text_input("Admin email"),
             "password": st.text_input("Password", type="password"),
             "confirm": st.text_input("Confirm password", type="password")}
        ok = st.form_submit_button("Create company & Admin", type="primary")
    if ok:
        errs = L.validate_setup(f)
        if errs:
            show_errors(errs)
        else:
            admin = L.create_setup(f)
            st.query_params["s"] = L.create_session(admin["id"])
            st.session_state["uid"] = admin["id"]
            st.rerun()


def login_page():
    st.title(f"🏢 {L.get_company().get('name', 'HCM Lite')}")
    st.subheader("Sign in")
    show_flash()
    with st.form("login"):
        email = st.text_input("Email")
        pw = st.text_input("Password", type="password")
        ok = st.form_submit_button("Login", type="primary")
    if ok:
        user, err = L.authenticate(email, pw)
        if err:
            st.error(err)
        else:
            st.query_params["s"] = L.create_session(user["id"])
            st.session_state["uid"] = user["id"]
            st.rerun()


# ------------------------------------------------------------------ shared widgets
def announcements_box(limit=3):
    st.subheader("📢 Announcements")
    items = sorted(L.get_announcements(), key=lambda a: a["created_at"], reverse=True)
    if not items:
        st.info("No announcements yet.")
    for a in items[:limit]:
        with st.expander(f"{a['title']} — {a['created_at'][:10]}"):
            st.write(a["message"])


def helper_box(user):
    st.subheader("🤖 Smart Helper")
    key = f"chat_{user['id']}"
    hist = st.session_state.setdefault(key, [])
    with st.form(f"helper_{user['id']}", clear_on_submit=True):
        q = st.text_input("Ask a question about your data",
                          placeholder="e.g. How many employees are present today?"
                          if user["role"] == "admin" else "e.g. How many leaves do I have left?")
        ask = st.form_submit_button("Ask")
    if ask and q.strip():
        ans = (L.get_admin_answer(q) if user["role"] == "admin"
               else L.get_employee_answer(q, user["id"]))
        hist.append((q, ans))
    for q, a in reversed(hist[-5:]):
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            st.write(a)


def status_rows(emps, d_from, d_to):
    now, company = datetime.now(), L.get_company()
    idx, leaves = L.attendance_index(), L.get_leaves()
    rows, d = [], d_from
    while d <= d_to:
        for e in emps:
            st_ = L.day_status(e, d, company, now, idx, leaves)
            if st_ is None:
                continue
            r = idx.get((e["id"], d.isoformat()), {})
            hrs = L.hours_worked(r.get("check_in"), r.get("check_out")) if r else 0
            rows.append({"Employee ID": e["id"], "Name": e["name"], "Department": e["department"],
                         "Date": d.isoformat(), "Check-in": fmt_t(r.get("check_in")),
                         "Check-out": fmt_t(r.get("check_out")),
                         "Hours": round(hrs, 2) if r.get("check_out") else None, "Status": st_})
        d += timedelta(days=1)
    return rows


# ------------------------------------------------------------------ payslip
def payslip_html(emp, p, company):
    esc = _html.escape
    month_name = f"{calendar.month_name[p['month']]} {p['year']}"
    leave_txt = ", ".join(f"{esc(k)}: {v}" for k, v in p["leave_by_type"].items()) or "None"
    notes = "".join(f"<p class='note'>⚠ {n}</p>" for n in p["notes"])
    rows = [("Monthly base salary", money(p["salary"])), ("Working days in month", p["working_days"]),
            ("Present days (on time)", p["present"]), ("Late days (counted present)", p["late"]),
            ("Half-day count", p["half_day"]), ("Absent days", p["absent"]),
            ("Approved leave days", f"{p['leave_days']} ({leave_txt})"),
            ("Per-day salary", money(p["per_day"])),
            ("Attendance deduction", f"- {money(p['deduction'])}")]
    body = "".join(f"<tr><td>{a}</td><td style='text-align:right'>{b}</td></tr>" for a, b in rows)
    return f"""<div style="font-family:Arial,sans-serif;max-width:720px;margin:auto;padding:24px;
border:1px solid #cbd5e1;border-radius:10px;color:#0f1f3d">
<style>td{{padding:8px;border-bottom:1px solid #e2e8f0}} .note{{color:#b45309;font-size:13px}}
@media print{{button{{display:none}}}}</style>
<h2 style="margin:0">{esc(company['name'])}</h2><p style="margin:2px 0 14px;color:#475569">Payslip — {month_name}</p>
<table width="100%"><tr><td><b>Employee</b></td><td>{esc(emp['name'])} ({esc(emp['id'])})</td></tr>
<tr><td><b>Department</b></td><td>{esc(emp['department'])}</td></tr>
<tr><td><b>Job title</b></td><td>{esc(emp['title'])}</td></tr></table><br>
<table width="100%">{body}
<tr><td><b>NET SALARY</b></td><td style="text-align:right;font-size:18px"><b>{money(p['net'])}</b></td></tr></table>
{notes}<p style="font-size:11px;color:#64748b">Deduction = per-day salary × (absent days + 0.5 × half-days).
Approved leave is excluded from absences.</p>
<button onclick="window.print()" style="padding:8px 16px;background:#1d4ed8;color:#fff;border:0;border-radius:6px;cursor:pointer">
🖨 Print / Save as PDF</button></div>"""


def payslip_page(user):
    st.header("🧾 Monthly Payslip")
    if user["role"] == "admin":
        emps = L.employees()
        if not emps:
            st.info("No employees yet. Add one first.")
            return
        emp = st.selectbox("Employee", emps, format_func=lambda e: f"{e['id']} — {e['name']}")
    else:
        emp = user
    today = date.today()
    c1, c2 = st.columns(2)
    month = c1.selectbox("Month", range(1, 13), index=today.month - 1,
                         format_func=lambda m: calendar.month_name[m])
    year = c2.selectbox("Year", range(today.year - 3, today.year + 2), index=3)
    p = L.calculate_payroll(emp, year, month)
    html = payslip_html(emp, p, L.get_company())
    st.iframe(html, height=720)
    st.download_button("⬇ Download payslip (HTML)", html,
                       file_name=f"payslip_{emp['id']}_{year}-{month:02d}.html", mime="text/html")


# ------------------------------------------------------------------ admin pages
def admin_dashboard(user):
    company = L.get_company()
    st.header("📊 Admin Dashboard")
    st.caption(f"{company['name']} • {date.today():%A, %d %B %Y}")
    s = L.get_today_attendance_summary()
    c = s["counts"]
    pending = sum(1 for l in L.get_leaves() if l["status"] == "Pending")
    r1 = st.columns(4)
    r1[0].metric("Active employees", s["total"])
    r1[1].metric("Present today", c["Present"])
    r1[2].metric("Late today", c["Late"])
    r1[3].metric("Half-day today", c["Half Day"])
    r2 = st.columns(3)
    r2[0].metric("Absent today", c["Absent"])
    r2[1].metric("On approved leave", c["On Leave"])
    r2[2].metric("Pending leave requests", pending)
    if s["working_day"] and not s["absent_counted"]:
        st.caption(f"Absences are counted after office hours end ({company['office_end']}).")

    st.subheader("Quick actions")
    q = st.columns(6)
    for col, (label, page) in zip(q, [("➕ Add employee", "Employees"), ("🗓 Attendance", "Attendance"),
                                      ("📝 Review leaves", "Leaves"), ("⚙ Settings", "Settings"),
                                      ("📢 Announce", "Announcements"), ("🧾 Payslips", "Payslips")]):
        col.button(label, on_click=go, args=(page,), key=f"qa_{page}")

    left, right = st.columns(2)
    with left:
        st.subheader("Today by department")
        depts = L.departments()
        data = {d: L.get_today_attendance_summary(d)["counts"] for d in depts}
        df = pd.DataFrame(data).T.drop(columns=["Not Checked In Yet"], errors="ignore") if data else None
        if df is None or df.values.sum() == 0:
            st.info("No attendance data for today yet.")
        else:
            st.bar_chart(df)
    with right:
        st.subheader("Last 7 days (checked-in employees)")
        att = L.get_attendance()
        days = [(date.today() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        trend = pd.Series({d[5:]: sum(1 for a in att if a["date"] == d) for d in days})
        if trend.sum() == 0:
            st.info("No attendance records in the last 7 days.")
        else:
            st.line_chart(trend)

    st.subheader("Recent activity")
    ev = []
    names = {u["id"]: u["name"] for u in L.get_users()}
    for a in L.get_attendance():
        ev.append((a["created_at"], f"{names.get(a['employee_id'], '?')} checked in ({a['date']})"))
    for l in L.get_leaves():
        ev.append((l["created_at"], f"{names.get(l['employee_id'], '?')} requested {l['type']} leave — {l['status']}"))
    for e in L.employees():
        ev.append((e["created_at"], f"Employee added: {e['name']}"))
    for a in L.get_announcements():
        ev.append((a["created_at"], f"Announcement: {a['title']}"))
    if not ev:
        st.info("No activity yet.")
    for t, msg in sorted(ev, reverse=True)[:8]:
        st.write(f"`{t[:16].replace('T', ' ')}` {msg}")
    st.divider()
    helper_box(user)
    announcements_box()


def employee_form(prefix, emp=None):
    """Shared add/edit form fields."""
    editing = emp is not None
    f = {"name": st.text_input("Full name", emp["name"] if editing else "", key=f"{prefix}n"),
         "email": st.text_input("Email", emp["email"] if editing else "", key=f"{prefix}e"),
         "password": st.text_input("New password (leave blank to keep)" if editing else "Password",
                                   type="password", key=f"{prefix}p"),
         "confirm": st.text_input("Confirm password", type="password", key=f"{prefix}c"),
         "department": st.text_input("Department", emp["department"] if editing else "", key=f"{prefix}d"),
         "title": st.text_input("Job title", emp["title"] if editing else "", key=f"{prefix}t"),
         "joining_date": st.date_input("Joining date", date.fromisoformat(emp["joining_date"])
                                       if editing else date.today(), key=f"{prefix}j"),
         "salary": st.number_input("Monthly salary (Rs.)", min_value=0.0, step=1000.0,
                                   value=float(emp["salary"]) if editing else 0.0, key=f"{prefix}s"),
         "phone": st.text_input("Phone (optional)", emp.get("phone", "") if editing else "", key=f"{prefix}ph")}
    return f


def employees_page(user):
    st.header("👥 Employees")
    show_flash()
    tab_list, tab_add = st.tabs(["Employee list", "Add employee"])
    with tab_add:
        with st.form("add_emp", clear_on_submit=False):
            f = employee_form("add")
            ok = st.form_submit_button("Create employee", type="primary")
        if ok:
            errs = L.validate_employee(f)
            if errs:
                show_errors(errs)
            else:
                e = L.create_employee(f)
                flash(f"Employee {e['name']} created with ID {e['id']}.")
                st.rerun()
        if L.departments():
            st.caption("Existing departments: " + ", ".join(L.departments()))
    with tab_list:
        emps = L.employees()
        if not emps:
            st.info("No employees yet. Use the 'Add employee' tab to create the first one.")
            return
        c1, c2, c3, c4 = st.columns(4)
        search = c1.text_input("Search name / email / ID").strip().lower()
        dept = c2.selectbox("Department", ["All"] + L.departments())
        stat = c3.selectbox("Status", ["All", "Active", "Inactive"])
        sort = c4.selectbox("Sort by", ["Name", "Employee ID", "Department", "Joining date", "Salary"])
        keymap = {"Name": "name", "Employee ID": "id", "Department": "department",
                  "Joining date": "joining_date", "Salary": "salary"}
        shown = [e for e in emps
                 if (not search or search in e["name"].lower() or search in e["email"].lower()
                     or search in e["id"].lower())
                 and (dept == "All" or e["department"] == dept)
                 and (stat == "All" or e.get("active", True) == (stat == "Active"))]
        shown.sort(key=lambda e: str(e[keymap[sort]]).lower() if sort != "Salary" else e["salary"])
        if not shown:
            st.info("No employees match your filters.")
            return
        st.dataframe(pd.DataFrame([{"ID": e["id"], "Name": e["name"], "Email": e["email"],
                                    "Department": e["department"], "Job title": e["title"],
                                    "Joined": e["joining_date"], "Salary": money(e["salary"]),
                                    "Status": "Active" if e.get("active", True) else "Inactive"}
                                   for e in shown]), hide_index=True)
        sel = st.selectbox("Select an employee to view / edit", shown,
                           format_func=lambda e: f"{e['id']} — {e['name']}")
        t1, t2, t3 = st.tabs(["Details", "Edit", "Activate / Deactivate"])
        with t1:
            st.write(f"**{sel['name']}** ({sel['id']})  \n{sel['title']} • {sel['department']}  \n"
                     f"📧 {sel['email']}  \n📞 {sel.get('phone') or '—'}  \n"
                     f"Joined {sel['joining_date']} • Salary {money(sel['salary'])}  \n"
                     f"Leave balance: {L.calculate_employee_leave_balance(sel['id'])['remaining']} day(s)")
        with t2:
            with st.form(f"edit_{sel['id']}"):
                f = employee_form(f"ed{sel['id']}", sel)
                ok = st.form_submit_button("Save changes", type="primary")
            if ok:
                errs = L.validate_employee(f, editing_id=sel["id"])
                if errs:
                    show_errors(errs)
                else:
                    L.update_employee(sel["id"], f)
                    flash("Employee updated.")
                    st.rerun()
        with t3:
            active = sel.get("active", True)
            st.write("Deactivating blocks login and removes the employee from today's totals, but keeps "
                     "all attendance, leave and payroll history. (Employees are never hard-deleted.)")
            sure = st.checkbox("I confirm", key=f"conf_{sel['id']}")
            if st.button("Deactivate" if active else "Reactivate", disabled=not sure, key=f"tg_{sel['id']}"):
                L.set_employee_active(sel["id"], not active)
                flash("Employee status updated.")
                st.rerun()


def attendance_admin_page(user):
    st.header("🗓 Attendance")
    emps = L.employees()
    if not emps:
        st.info("No employees yet.")
        return
    c1, c2, c3, c4 = st.columns(4)
    rng = c1.date_input("Date range", (date.today() - timedelta(days=6), date.today()))
    dept = c2.selectbox("Department", ["All"] + L.departments())
    search = c3.text_input("Search employee").strip().lower()
    stat = c4.selectbox("Status", ["All", "Present", "Late", "Half Day", "Absent", "On Leave"])
    if not isinstance(rng, tuple) or len(rng) != 2:
        st.info("Select both a start and an end date.")
        return
    if (rng[1] - rng[0]).days > 92:
        st.warning("Please choose a range of 93 days or less.")
        return
    pool = [e for e in emps if (dept == "All" or e["department"] == dept)
            and (not search or search in e["name"].lower() or search in e["id"].lower())]
    rows = [r for r in status_rows(pool, rng[0], rng[1]) if stat == "All" or r["Status"] == stat]
    if not rows:
        st.info("No attendance rows for these filters (weekends, future days and pre-joining days are skipped).")
        return
    df = pd.DataFrame(rows).sort_values(["Date", "Name"], ascending=[False, True])
    st.dataframe(df, hide_index=True)
    st.download_button("⬇ Export CSV", df.to_csv(index=False), "attendance.csv", "text/csv")


def leaves_admin_page(user):
    st.header("📝 Leave Requests")
    show_flash()
    users = {u["id"]: u for u in L.get_users()}
    leaves = sorted(L.get_leaves(), key=lambda l: l["created_at"], reverse=True)
    if not leaves:
        st.info("No leave requests yet.")
        return
    flt = st.selectbox("Status", ["All", "Pending", "Approved", "Rejected"])
    for l in [x for x in leaves if flt == "All" or x["status"] == flt]:
        e = users.get(l["employee_id"], {})
        icon = {"Pending": "🟡", "Approved": "🟢", "Rejected": "🔴"}[l["status"]]
        with st.expander(f"{icon} {e.get('name', '?')} • {l['type']} • {l['start']} → {l['end']} "
                         f"({l['days']} working days) • {l['status']}"):
            st.write(f"**Department:** {e.get('department', '—')}  \n**Reason:** {l['reason']}")
            if l["status"] != "Pending":
                st.write(f"**Decision comment:** {l['comment'] or '—'}")
                continue
            with st.form(f"dec_{l['id']}"):
                cm = st.text_input("Decision comment (required for rejection)")
                a, r = st.columns(2)
                ap = a.form_submit_button("✅ Approve")
                rj = r.form_submit_button("❌ Reject")
            if ap or rj:
                ok, msg = L.decide_leave(l["id"], "Approved" if ap else "Rejected", cm, user["id"])
                if ok:
                    flash(msg)
                    st.rerun()
                else:
                    st.error(msg)


def announcements_page(user):
    st.header("📢 Announcements")
    show_flash()
    admin = user["role"] == "admin"
    if admin:
        with st.form("new_ann", clear_on_submit=True):
            t = st.text_input("Title")
            m = st.text_area("Message")
            ok = st.form_submit_button("Publish announcement", type="primary")
        if ok:
            if not t.strip() or not m.strip():
                st.error("Both title and message are required.")
            else:
                rows = L.get_announcements()
                rows.append({"id": L.generate_id("ANN"), "title": t.strip(), "message": m.strip(),
                             "created_at": L.now_iso()})
                L.save_announcements(rows)
                flash("Announcement published.")
                st.rerun()
    items = sorted(L.get_announcements(), key=lambda a: a["created_at"], reverse=True)
    if not items:
        st.info("No announcements yet.")
    for a in items:
        with st.expander(f"{a['title']} — {a['created_at'][:10]}"):
            st.write(a["message"])
            if admin:
                with st.form(f"ea_{a['id']}"):
                    nt = st.text_input("Title", a["title"])
                    nm = st.text_area("Message", a["message"])
                    sv = st.form_submit_button("Save changes")
                if sv:
                    if not nt.strip() or not nm.strip():
                        st.error("Title and message are required.")
                    else:
                        rows = L.get_announcements()
                        for r in rows:
                            if r["id"] == a["id"]:
                                r["title"], r["message"] = nt.strip(), nm.strip()
                        L.save_announcements(rows)
                        flash("Announcement updated.")
                        st.rerun()
                sure = st.checkbox("Confirm delete", key=f"dc_{a['id']}")
                if st.button("🗑 Delete", disabled=not sure, key=f"dl_{a['id']}"):
                    L.save_announcements([r for r in L.get_announcements() if r["id"] != a["id"]])
                    flash("Announcement deleted.")
                    st.rerun()


def reports_page(user):
    st.header("📑 Monthly Attendance Report")
    emps = L.employees()
    if not emps:
        st.info("No employees yet.")
        return
    today = date.today()
    c1, c2 = st.columns(2)
    month = c1.selectbox("Month", range(1, 13), index=today.month - 1,
                         format_func=lambda m: calendar.month_name[m])
    year = c2.selectbox("Year", range(today.year - 3, today.year + 2), index=3)
    rows = []
    for e in emps:
        p = L.calculate_payroll(e, year, month)
        rows.append({"ID": e["id"], "Name": e["name"], "Department": e["department"],
                     "Working days": p["working_days"], "Present": p["present"], "Late": p["late"],
                     "Half day": p["half_day"], "Absent": p["absent"], "On leave": p["leave_days"],
                     "Salary": p["salary"], "Deduction": p["deduction"], "Net": p["net"]})
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True)
    st.download_button("⬇ Export CSV", df.to_csv(index=False), f"report_{year}-{month:02d}.csv", "text/csv")
    st.caption("Use your browser's Print (Ctrl+P) to print this report.")


def settings_page(user):
    st.header("⚙ Company Settings")
    show_flash()
    c = L.get_company()
    with st.form("settings"):
        name = st.text_input("Company name", c["name"])
        a, b = st.columns(2)
        start = a.time_input("Office start time", time.fromisoformat(c["office_start"]))
        end = b.time_input("Office end time", time.fromisoformat(c["office_end"]))
        g, q = st.columns(2)
        grace = g.number_input("Grace period (minutes)", min_value=0, value=int(c["grace_minutes"]))
        quota = q.number_input("Annual leave quota (days)", min_value=0, value=int(c["leave_quota"]))
        days = st.multiselect("Working days", range(7), default=c["working_days"],
                              format_func=lambda i: L.DAY_NAMES[i])
        ce = st.text_input("Contact email (optional)", c["contact_email"])
        cp = st.text_input("Contact phone (optional)", c["contact_phone"])
        ad = st.text_input("Address (optional)", c["address"])
        ok = st.form_submit_button("Save settings", type="primary")
    if ok:
        new = {**c, "name": name, "office_start": start.strftime("%H:%M"), "office_end": end.strftime("%H:%M"),
               "grace_minutes": int(grace), "leave_quota": int(quota), "working_days": sorted(days),
               "contact_email": ce, "contact_phone": cp, "address": ad}
        errs = L.validate_settings(new)
        if errs:
            show_errors(errs)
        else:
            L.save_company(new)
            flash("Settings saved. They apply to future calculations; existing records are unchanged.")
            st.rerun()
    with st.expander("⚠ Danger zone — reset all data"):
        st.write("This permanently deletes the company, all users, attendance, leaves and announcements.")
        if st.text_input("Type RESET to confirm") == "RESET" and st.button("Erase everything"):
            L.reset_application_data()
            logout()
            st.rerun()


# ------------------------------------------------------------------ employee pages
def employee_dashboard(user):
    now = datetime.now()
    st.header(f"👋 Welcome, {user['name']}")
    st.caption(f"{user['title']} • {user['department']} • {now:%A, %d %B %Y}")
    show_flash()
    rec = L.get_record(user["id"], now.date().isoformat())
    bal = L.calculate_employee_leave_balance(user["id"])
    pending = sum(1 for l in L.get_leaves() if l["employee_id"] == user["id"] and l["status"] == "Pending")
    c = st.columns(5)
    c[0].metric("Today", (rec or {}).get("status", "Not checked in"))
    c[1].metric("Check-in", fmt_t(rec["check_in"]) if rec else "—")
    c[2].metric("Check-out", fmt_t(rec.get("check_out")) if rec else "—")
    hrs = L.hours_worked(rec["check_in"], rec.get("check_out")) if rec else 0
    c[3].metric("Hours today", f"{hrs:.2f}" if rec and rec.get("check_out") else "—")
    c[4].metric("Leave balance", f"{bal['remaining']} / {bal['quota']}")
    b1, b2, b3, b4, b5 = st.columns(5)
    if b1.button("✅ Check in", disabled=bool(rec), type="primary"):
        ok, msg = L.check_in(user["id"])
        flash(msg, "success" if ok else "error")
        st.rerun()
    if b2.button("🚪 Check out", disabled=not rec or bool(rec.get("check_out"))):
        ok, msg = L.check_out(user["id"])
        flash(msg, "success" if ok else "error")
        st.rerun()
    b3.button("📝 Apply for leave", on_click=go, args=("My Leaves",))
    b4.button("🗓 View attendance", on_click=go, args=("My Attendance",))
    b5.button("🧾 View payslip", on_click=go, args=("Payslip",))
    st.metric("Pending leave requests", pending)
    st.subheader("Recent attendance")
    rows = status_rows([user], date.today() - timedelta(days=13), date.today())
    if rows:
        st.dataframe(pd.DataFrame(rows).drop(columns=["Employee ID", "Name", "Department"])
                     .sort_values("Date", ascending=False).head(7), hide_index=True)
    else:
        st.info("No attendance to show yet.")
    announcements_box()
    helper_box(user)


def my_attendance_page(user):
    st.header("🗓 My Attendance (last 30 days)")
    rows = status_rows([user], date.today() - timedelta(days=29), date.today())
    if not rows:
        st.info("No attendance records yet.")
        return
    df = pd.DataFrame(rows).drop(columns=["Employee ID", "Name", "Department"])
    st.dataframe(df.sort_values("Date", ascending=False), hide_index=True)


def my_leaves_page(user):
    st.header("📝 My Leaves")
    show_flash()
    bal = L.calculate_employee_leave_balance(user["id"])
    c = st.columns(4)
    c[0].metric("Yearly quota", bal["quota"])
    c[1].metric("Used (approved)", bal["used"])
    c[2].metric("Pending", bal["pending"])
    c[3].metric("Remaining", bal["remaining"])
    st.caption("Annual and Casual leave use the yearly quota. Sick and Unpaid leave do not.")
    with st.form("apply_leave", clear_on_submit=True):
        t = st.selectbox("Leave type", L.LEAVE_TYPES)
        a, b = st.columns(2)
        s = a.date_input("Start date", date.today())
        e = b.date_input("End date", date.today())
        reason = st.text_area("Reason")
        ok = st.form_submit_button("Submit request", type="primary")
    if ok:
        errs, rec = L.submit_leave(user["id"], t, s, e, reason)
        if errs:
            for m in errs:
                st.error(m)
        else:
            flash(f"Leave request submitted ({rec['days']} working day(s)).")
            st.rerun()
    st.subheader("History")
    mine = sorted([l for l in L.get_leaves() if l["employee_id"] == user["id"]],
                  key=lambda l: l["created_at"], reverse=True)
    if not mine:
        st.info("You have not requested any leave yet.")
    else:
        st.dataframe(pd.DataFrame([{"Requested": l["created_at"][:10], "Type": l["type"],
                                    "From": l["start"], "To": l["end"], "Days": l["days"],
                                    "Status": l["status"], "Comment": l["comment"]} for l in mine]),
                     hide_index=True)


# ------------------------------------------------------------------ router
def main():
    if not L.is_setup_done():
        return setup_page()
    user = current_user()
    if not user:
        return login_page()
    admin = user["role"] == "admin"
    pages = ({"Dashboard": admin_dashboard, "Employees": employees_page, "Attendance": attendance_admin_page,
              "Leaves": leaves_admin_page, "Announcements": announcements_page, "Payslips": payslip_page,
              "Reports": reports_page, "Settings": settings_page} if admin else
             {"Dashboard": employee_dashboard, "My Attendance": my_attendance_page, "My Leaves": my_leaves_page,
              "Payslip": payslip_page, "Announcements": announcements_page})
    with st.sidebar:
        st.markdown(f"### 🏢 {L.get_company()['name']}")
        st.caption(f"{user['name']} ({user['role'].title()})")
        if st.session_state.get("nav") not in pages:
            st.session_state["nav"] = "Dashboard"
        st.radio("Menu", list(pages), key="nav", label_visibility="collapsed")
        if st.button("Logout"):
            logout()
            st.rerun()
    pages[st.session_state["nav"]](user)


main()
