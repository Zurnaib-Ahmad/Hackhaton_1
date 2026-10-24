"""HCM Lite - business logic.

Storage (JSON files = Streamlit version of localStorage), authentication,
attendance, leave, payroll and the rule-based Smart Helper.
No UI code lives here, so everything can be unit-tested.
"""
import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("HCM_DATA_DIR", Path(__file__).resolve().parent / "data"))
KEYS = ("hcm_company", "hcm_users", "hcm_attendance", "hcm_leaves",
        "hcm_session", "hcm_announcements")
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LEAVE_TYPES = ["Casual", "Sick", "Annual", "Unpaid"]
QUOTA_TYPES = ("Annual", "Casual")  # only these deduct from the yearly quota
HALF_DAY_HOURS = 5
SESSION_DAYS = 7
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------
# Storage helpers (storage.js equivalent)
# --------------------------------------------------------------------------
def _path(key):
    return DATA_DIR / f"{key}.json"


def get_data(key, fallback):
    """Read JSON. Missing/corrupt file -> fallback (corrupt file is kept as .corrupt.json)."""
    p = _path(key)
    if not p.exists():
        return fallback
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if type(data) is not type(fallback):
            raise ValueError("wrong type")
        return data
    except (ValueError, OSError):
        try:
            p.replace(p.with_suffix(".corrupt.json"))
        except OSError:
            pass
        return fallback


def set_data(key, value):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(key).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path(key))  # atomic: no half-written files


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def generate_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def get_users():
    return get_data("hcm_users", [])


def save_users(users):
    set_data("hcm_users", users)


def get_attendance():
    return get_data("hcm_attendance", [])


def save_attendance(rows):
    set_data("hcm_attendance", rows)


def get_leaves():
    return get_data("hcm_leaves", [])


def save_leaves(rows):
    set_data("hcm_leaves", rows)


def get_announcements():
    return get_data("hcm_announcements", [])


def save_announcements(rows):
    set_data("hcm_announcements", rows)


def default_company(name=""):
    return {"name": name, "office_start": "09:00", "office_end": "18:00",
            "grace_minutes": 15, "leave_quota": 20, "working_days": [0, 1, 2, 3, 4],
            "contact_email": "", "contact_phone": "", "address": "",
            "created_at": now_iso()}


def get_company():
    c = get_data("hcm_company", {})
    return {**default_company(), **c} if c else {}


def save_company(c):
    set_data("hcm_company", c)


def reset_application_data():
    for k in KEYS:
        for p in (_path(k), _path(k).with_suffix(".corrupt.json")):
            if p.exists():
                p.unlink()


def is_setup_done():
    return bool(get_company().get("name")) and any(u.get("role") == "admin" for u in get_users())


# --------------------------------------------------------------------------
# Authentication (auth.js equivalent) - EDUCATIONAL, not production security
# --------------------------------------------------------------------------
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 120_000).hex()
    return salt, h


def verify_password(user, password):
    _, h = hash_password(password, user["salt"])
    return hmac.compare_digest(h, user["pw_hash"])


def email_taken(email, exclude_id=None):
    e = email.strip().lower()
    return any(u["email"].lower() == e and u["id"] != exclude_id for u in get_users())


def validate_setup(f):
    errs = {}
    if not f.get("company", "").strip():
        errs["company"] = "Company name is required."
    if not f.get("name", "").strip():
        errs["name"] = "Admin name is required."
    email = f.get("email", "").strip()
    if not email:
        errs["email"] = "Email is required."
    elif not EMAIL_RE.match(email):
        errs["email"] = "Enter a valid email like name@example.com."
    elif email_taken(email):
        errs["email"] = "This email is already registered."
    pw = f.get("password", "")
    if len(pw) < 6:
        errs["password"] = "Password must be at least 6 characters."
    if pw != f.get("confirm", ""):
        errs["confirm"] = "Passwords do not match."
    return errs


def create_setup(f):
    save_company(default_company(f["company"].strip()))
    salt, h = hash_password(f["password"])
    admin = {"id": "ADMIN-001", "role": "admin", "name": f["name"].strip(),
             "email": f["email"].strip().lower(), "salt": salt, "pw_hash": h,
             "active": True, "created_at": now_iso()}
    users = [u for u in get_users() if u.get("role") != "admin"] + [admin]
    save_users(users)
    return admin


def authenticate(email, password):
    """Returns (user, error)."""
    email = email.strip().lower()
    if not email or not password:
        return None, "Enter both email and password."
    user = next((u for u in get_users() if u["email"].lower() == email), None)
    if not user or not verify_password(user, password):
        return None, "Incorrect email or password. Please check and try again."
    if not user.get("active", True):
        return None, "This account is deactivated. Contact your HR admin."
    return user, None


def get_user(uid):
    return next((u for u in get_users() if u["id"] == uid), None)


def create_session(uid):
    sessions = get_data("hcm_session", {})
    cutoff = datetime.now() - timedelta(days=SESSION_DAYS)
    sessions = {t: s for t, s in sessions.items()
                if datetime.fromisoformat(s["created"]) > cutoff}
    token = secrets.token_urlsafe(24)
    sessions[token] = {"user_id": uid, "created": now_iso()}
    set_data("hcm_session", sessions)
    return token


def session_user_id(token):
    s = get_data("hcm_session", {}).get(token)
    if not s:
        return None
    if datetime.fromisoformat(s["created"]) < datetime.now() - timedelta(days=SESSION_DAYS):
        return None
    return s["user_id"]


def delete_session(token):
    sessions = get_data("hcm_session", {})
    if token in sessions:
        del sessions[token]
        set_data("hcm_session", sessions)


# --------------------------------------------------------------------------
# Employees
# --------------------------------------------------------------------------
def employees(include_inactive=True):
    return [u for u in get_users() if u.get("role") == "employee"
            and (include_inactive or u.get("active", True))]


def active_employees():
    return employees(include_inactive=False)


def departments():
    return sorted({e["department"] for e in employees() if e.get("department")})


def next_employee_id():
    nums = [int(u["id"].split("-")[1]) for u in employees()
            if re.fullmatch(r"EMP-\d+", u["id"])]
    return f"EMP-{(max(nums) + 1 if nums else 1):03d}"


def validate_employee(f, editing_id=None):
    errs = {}
    if not f.get("name", "").strip():
        errs["name"] = "Full name is required."
    email = f.get("email", "").strip()
    if not email:
        errs["email"] = "Email is required."
    elif not EMAIL_RE.match(email):
        errs["email"] = "Enter a valid email address."
    elif email_taken(email, editing_id):
        errs["email"] = "Another account already uses this email."
    pw, cpw = f.get("password", ""), f.get("confirm", "")
    if editing_id is None or pw or cpw:
        if len(pw) < 6:
            errs["password"] = "Password must be at least 6 characters."
        elif pw != cpw:
            errs["confirm"] = "Passwords do not match."
    if not f.get("department", "").strip():
        errs["department"] = "Department is required."
    if not f.get("title", "").strip():
        errs["title"] = "Job title is required."
    if not isinstance(f.get("joining_date"), date):
        errs["joining_date"] = "Select a valid joining date."
    try:
        if float(f.get("salary", 0)) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errs["salary"] = "Monthly salary must be greater than zero."
    return errs


def create_employee(f):
    salt, h = hash_password(f["password"])
    emp = {"id": next_employee_id(), "role": "employee", "name": f["name"].strip(),
           "email": f["email"].strip().lower(), "salt": salt, "pw_hash": h,
           "department": f["department"].strip(), "title": f["title"].strip(),
           "joining_date": f["joining_date"].isoformat(), "salary": float(f["salary"]),
           "phone": f.get("phone", "").strip(), "active": True, "created_at": now_iso()}
    users = get_users()
    users.append(emp)
    save_users(users)
    return emp


def update_employee(emp_id, f):
    users = get_users()
    for u in users:
        if u["id"] == emp_id:
            u.update({"name": f["name"].strip(), "email": f["email"].strip().lower(),
                      "department": f["department"].strip(), "title": f["title"].strip(),
                      "joining_date": f["joining_date"].isoformat(),
                      "salary": float(f["salary"]), "phone": f.get("phone", "").strip()})
            if f.get("password"):
                u["salt"], u["pw_hash"] = hash_password(f["password"])
            save_users(users)
            return True
    return False


def set_employee_active(emp_id, active):
    """Deactivate instead of delete, so attendance/leave/payroll history stays intact."""
    users = get_users()
    for u in users:
        if u["id"] == emp_id and u.get("role") == "employee":
            u["active"] = active
            save_users(users)
            return True
    return False


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def validate_settings(s):
    errs = {}
    if not s["name"].strip():
        errs["name"] = "Company name cannot be blank."
    if s["grace_minutes"] < 0:
        errs["grace_minutes"] = "Grace period cannot be negative."
    if s["leave_quota"] < 0:
        errs["leave_quota"] = "Leave quota cannot be negative."
    if not s["working_days"]:
        errs["working_days"] = "Select at least one working day."
    if s["office_end"] <= s["office_start"]:
        errs["office_end"] = "Office end time must be after the start time."
    return errs


# --------------------------------------------------------------------------
# Attendance
# --------------------------------------------------------------------------
def _secs(t):
    parts = [int(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def is_late(check_in, company):
    """Late only if check-in is AFTER start + grace (exactly 09:15:00 is not late)."""
    limit = _secs(company["office_start"]) + company["grace_minutes"] * 60
    return _secs(check_in) > limit


def hours_worked(check_in, check_out):
    if not check_in or not check_out:
        return 0.0
    return max(0.0, (_secs(check_out) - _secs(check_in)) / 3600)


def compute_status(check_in, check_out, company):
    """Precedence: Half Day (completed shift < 5h) > Late > Present."""
    if check_out and hours_worked(check_in, check_out) < HALF_DAY_HOURS:
        return "Half Day"
    return "Late" if is_late(check_in, company) else "Present"


def is_working_day(d, company):
    return d.weekday() in company["working_days"]


def day_has_ended(d, company, now):
    if d < now.date():
        return True
    return d == now.date() and now.strftime("%H:%M") >= company["office_end"]


def attendance_index():
    return {(r["employee_id"], r["date"]): r for r in get_attendance()}


def get_record(emp_id, ds):
    return attendance_index().get((emp_id, ds))


def get_employees_on_approved_leave(ds):
    ids = {l["employee_id"] for l in get_leaves()
           if l["status"] == "Approved" and l["start"] <= ds <= l["end"]}
    return [e for e in active_employees() if e["id"] in ids]


def day_status(emp, d, company, now, att_idx, leaves):
    """Status of one employee on one date, or None if the day does not count."""
    ds = d.isoformat()
    if not is_working_day(d, company) or ds < emp.get("joining_date", "0000-00-00"):
        return None
    rec = att_idx.get((emp["id"], ds))
    if rec:
        return rec.get("status") or compute_status(rec["check_in"], rec.get("check_out"), company)
    if any(l["employee_id"] == emp["id"] and l["status"] == "Approved"
           and l["start"] <= ds <= l["end"] for l in leaves):
        return "On Leave"
    return "Absent" if day_has_ended(d, company, now) else None


def check_in(emp_id, now=None):
    now = now or datetime.now()
    company, ds = get_company(), now.date().isoformat()
    if not is_working_day(now.date(), company):
        return False, "Today is not a working day. Admin can change working days in Settings."
    if get_record(emp_id, ds):
        return False, "You have already checked in today."
    if any(l["employee_id"] == emp_id and l["status"] == "Approved" and l["start"] <= ds <= l["end"]
           for l in get_leaves()):
        return False, "You are on approved leave today."
    t = now.strftime("%H:%M:%S")
    rows = get_attendance()
    rows.append({"id": generate_id("ATT"), "employee_id": emp_id, "date": ds,
                 "check_in": t, "check_out": None,
                 "status": compute_status(t, None, company), "created_at": now_iso()})
    save_attendance(rows)
    return True, f"Checked in at {now.strftime('%I:%M %p')}."


def check_out(emp_id, now=None):
    now = now or datetime.now()
    company, ds = get_company(), now.date().isoformat()
    rows = get_attendance()
    rec = next((r for r in rows if r["employee_id"] == emp_id and r["date"] == ds), None)
    if not rec:
        return False, "You must check in before checking out."
    if rec.get("check_out"):
        return False, "You have already checked out today."
    t = now.strftime("%H:%M:%S")
    if _secs(t) < _secs(rec["check_in"]):
        return False, "Check-out cannot be before check-in."
    rec["check_out"] = t
    rec["status"] = compute_status(rec["check_in"], t, company)
    save_attendance(rows)
    return True, f"Checked out. Worked {hours_worked(rec['check_in'], t):.2f} hours."


def get_today_attendance_summary(dept=None, now=None):
    now = now or datetime.now()
    company, today = get_company(), now.date()
    idx, leaves = attendance_index(), get_leaves()
    on_leave_ids = {e["id"] for e in get_employees_on_approved_leave(today.isoformat())}
    names = {k: [] for k in ("Present", "Late", "Half Day", "Absent", "On Leave", "Not Checked In Yet")}
    total = 0
    for e in active_employees():
        if dept and e["department"].lower() != dept.lower():
            continue
        total += 1
        st = day_status(e, today, company, now, idx, leaves)
        if st is None and e["id"] in on_leave_ids:
            st = "On Leave"
        if st is None and is_working_day(today, company) and today.isoformat() >= e["joining_date"]:
            st = "Not Checked In Yet"
        if st in names:
            names[st].append(e["name"])
    return {"total": total, "names": names, "counts": {k: len(v) for k, v in names.items()},
            "working_day": is_working_day(today, company),
            "absent_counted": is_working_day(today, company) and day_has_ended(today, company, now)}


def calculate_weekly_working_hours(emp_id, now=None):
    today = (now or datetime.now()).date()
    monday = today - timedelta(days=today.weekday())
    return sum(hours_worked(r["check_in"], r.get("check_out")) for r in get_attendance()
               if r["employee_id"] == emp_id and monday.isoformat() <= r["date"] <= today.isoformat())


# --------------------------------------------------------------------------
# Leave
# --------------------------------------------------------------------------
def count_working_days(start, end, company):
    n, d = 0, start
    while d <= end:
        n += is_working_day(d, company)
        d += timedelta(days=1)
    return n


def calculate_employee_leave_balance(emp_id, year=None):
    """Quota - approved Annual/Casual days. Pending shown separately, rejected ignored."""
    year, quota = year or date.today().year, get_company().get("leave_quota", 0)
    used = pending = 0
    taken_all = 0
    for l in get_leaves():
        if l["employee_id"] != emp_id or not l["start"].startswith(str(year)):
            continue
        if l["status"] == "Approved":
            taken_all += l["days"]
        if l["type"] in QUOTA_TYPES:
            if l["status"] == "Approved":
                used += l["days"]
            elif l["status"] == "Pending":
                pending += l["days"]
    return {"quota": quota, "used": used, "pending": pending, "remaining": quota - used,
            "available": quota - used - pending, "taken_all_types": taken_all}


def validate_leave(emp_id, ltype, start, end, reason, ignore_id=None):
    """Returns (errors, working_days)."""
    errs, company = [], get_company()
    if ltype not in LEAVE_TYPES:
        errs.append("Select a valid leave type.")
    if not reason.strip():
        errs.append("Reason is required.")
    if start > end:
        errs.append("Start date cannot be after the end date.")
        return errs, 0
    days = count_working_days(start, end, company)
    if days == 0:
        errs.append("The selected range has no working days (weekends/off-days are excluded).")
    s, e = start.isoformat(), end.isoformat()
    for l in get_leaves():
        if (l["employee_id"] == emp_id and l["id"] != ignore_id
                and l["status"] in ("Pending", "Approved") and l["start"] <= e and s <= l["end"]):
            errs.append(f"Overlaps with your {l['status'].lower()} leave "
                        f"({l['start']} to {l['end']}).")
            break
    if ltype in QUOTA_TYPES and days:
        if start.year != end.year:
            errs.append("Please split requests that cross a year boundary.")
        else:
            bal = calculate_employee_leave_balance(emp_id, start.year)
            if days > bal["available"]:
                errs.append(f"Only {bal['available']} quota day(s) available "
                            f"(after pending requests); you asked for {days}.")
    return errs, days


def submit_leave(emp_id, ltype, start, end, reason):
    errs, days = validate_leave(emp_id, ltype, start, end, reason)
    if errs:
        return errs, None
    rows = get_leaves()
    rec = {"id": generate_id("LV"), "employee_id": emp_id, "type": ltype,
           "start": start.isoformat(), "end": end.isoformat(), "days": days,
           "reason": reason.strip(), "status": "Pending", "comment": "",
           "created_at": now_iso(), "decided_at": None, "decided_by": None}
    rows.append(rec)
    save_leaves(rows)
    return [], rec


def decide_leave(leave_id, action, comment, admin_id):
    """action: 'Approved' or 'Rejected'. Returns (ok, message)."""
    rows = get_leaves()
    rec = next((l for l in rows if l["id"] == leave_id), None)
    if not rec:
        return False, "Leave request not found."
    if rec["status"] != "Pending":
        return False, f"This request is already {rec['status'].lower()}."
    if rec["employee_id"] == admin_id:
        return False, "You cannot decide your own request."
    if action == "Rejected" and not comment.strip():
        return False, "A comment is required when rejecting a request."
    if action == "Approved" and rec["type"] in QUOTA_TYPES:
        bal = calculate_employee_leave_balance(rec["employee_id"], int(rec["start"][:4]))
        if rec["days"] > bal["remaining"]:
            return False, f"Not enough quota left ({bal['remaining']} day(s))."
    rec.update({"status": action, "comment": comment.strip(),
                "decided_at": now_iso(), "decided_by": admin_id})
    save_leaves(rows)
    return True, f"Request {action.lower()}."


# --------------------------------------------------------------------------
# Payroll
# --------------------------------------------------------------------------
def calculate_payroll(emp, year, month, now=None):
    now = now or datetime.now()
    company, idx, leaves = get_company(), attendance_index(), get_leaves()
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    working = [d for d in days if is_working_day(d, company)]
    wd = len(working)
    salary = float(emp.get("salary", 0))
    per_day = salary / wd if wd else 0.0
    c = {"Present": 0, "Late": 0, "Half Day": 0, "Absent": 0, "On Leave": 0}
    pending_days = 0
    for d in working:
        st = day_status(emp, d, company, now, idx, leaves)
        if st in c:
            c[st] += 1
        elif d.isoformat() >= emp.get("joining_date", "0000-00-00"):
            pending_days += 1
    leave_by_type = {}
    for l in leaves:
        if l["employee_id"] == emp["id"] and l["status"] == "Approved":
            n = sum(1 for d in working if l["start"] <= d.isoformat() <= l["end"]
                    and not idx.get((emp["id"], d.isoformat())))
            if n:
                leave_by_type[l["type"]] = leave_by_type.get(l["type"], 0) + n
    deduction = round(per_day * (c["Absent"] + 0.5 * c["Half Day"]), 2)
    month_prefix = f"{year}-{month:02d}"
    has_records = any(k[0] == emp["id"] and k[1].startswith(month_prefix) for k in idx)
    notes = []
    if not has_records:
        notes.append("No attendance records exist for this month, so the figures only reflect "
                     "absences/leave from the calendar. Attendance data is incomplete.")
    if pending_days:
        notes.append(f"{pending_days} working day(s) have not ended yet and are not counted.")
    if wd == 0:
        notes.append("No working days are configured for this month.")
    return {"year": year, "month": month, "salary": salary, "working_days": wd,
            "per_day": round(per_day, 2), "present": c["Present"], "late": c["Late"],
            "half_day": c["Half Day"], "absent": c["Absent"], "leave_days": c["On Leave"],
            "leave_by_type": leave_by_type, "deduction": deduction,
            "net": round(salary - deduction, 2), "notes": notes}


# --------------------------------------------------------------------------
# Smart Helper (rule-based, uses real data only)
# --------------------------------------------------------------------------
HELP_ADMIN = ("I can answer: How many employees do we have? How many are present / late / absent "
              "today? Who is on leave today? How many leave requests are pending? Show attendance "
              "for a department. How many employees work in IT? What is the office start time?")
HELP_EMP = ("I can answer: How many leaves do I have left? Was I late today? What time did I check "
            "in? How many hours did I work this week? What is my department / salary? What is the "
            "status of my leave request? How many days of leave have I taken?")


def normalize_question(q):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", q.lower())).strip()


def _has(q, *words):
    return any(w in q for w in words)


def _names(lst):
    return ", ".join(lst) if lst else "nobody"


def _find_dept(q):
    for d in sorted(departments(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(d.lower()) + r"\b", q):
            return d
    return None


def get_admin_answer(question, now=None):
    q = normalize_question(question)
    company = get_company()
    dept = _find_dept(q)
    where = f" in {dept}" if dept else ""
    s = get_today_attendance_summary(dept, now)
    n, cnt = s["names"], s["counts"]
    if _has(q, "start time", "office time", "office start", "timing", "grace", "kitne baje"):
        return (f"Office starts at {company['office_start']} with a {company['grace_minutes']}-minute "
                f"grace period (late after check-in past that). Office ends at {company['office_end']}.")
    if _has(q, "pending") and _has(q, "leave", "request", "chutti"):
        p = sum(1 for l in get_leaves() if l["status"] == "Pending")
        return f"There are {p} pending leave request(s)."
    if _has(q, "leave", "chutti") and _has(q, "today", "aaj", "who", "kaun", "on leave"):
        return f"On approved leave today{where}: {_names(n['On Leave'])} ({cnt['On Leave']})."
    if _has(q, "late"):
        return f"Late today{where}: {_names(n['Late'])} ({cnt['Late']})."
    if _has(q, "absent", "gair haazir", "ghair hazir"):
        if not s["working_day"]:
            return "Today is not a working day, so nobody is counted absent."
        if not s["absent_counted"]:
            return (f"Absences are counted after office hours end ({company['office_end']}). "
                    f"Not checked in yet{where}: {_names(n['Not Checked In Yet'])}.")
        return f"Absent today{where}: {_names(n['Absent'])} ({cnt['Absent']})."
    if _has(q, "half day", "halfday"):
        return f"Half-day today{where}: {_names(n['Half Day'])} ({cnt['Half Day']})."
    if _has(q, "present", "haazir", "hazir", "attendance"):
        if not s["total"]:
            return f"There are no active employees{where} yet, so there is no attendance to show."
        return (f"Today's attendance{where} ({s['total']} employees): Present {cnt['Present']}, "
                f"Late {cnt['Late']}, Half Day {cnt['Half Day']}, Absent {cnt['Absent']}, "
                f"On Leave {cnt['On Leave']}, Not checked in yet {cnt['Not Checked In Yet']}.")
    if _has(q, "employee", "staff", "people", "work in", "kitne"):
        total = s["total"]
        return (f"There are {total} active employee(s){where}." if total or not dept
                else f"No active employees found{where}.")
    return "Sorry, I did not understand that. " + HELP_ADMIN


def get_employee_answer(question, employee_id, now=None):
    q = normalize_question(question)
    now = now or datetime.now()
    emp = get_user(employee_id)
    if not emp:
        return "I could not find your account."
    rec = get_record(employee_id, now.date().isoformat())
    if _has(q, "leave", "chutti"):
        mine = sorted([l for l in get_leaves() if l["employee_id"] == employee_id],
                      key=lambda l: l["created_at"], reverse=True)
        bal = calculate_employee_leave_balance(employee_id)
        if _has(q, "status", "request", "pending", "approved", "rejected"):
            if not mine:
                return "You have not submitted any leave requests."
            return "Your latest requests: " + "; ".join(
                f"{l['type']} {l['start']} to {l['end']} - {l['status']}"
                + (f" ({l['comment']})" if l["comment"] else "") for l in mine[:3]) + "."
        if _has(q, "taken", "used", "liye", "spent"):
            return (f"You have taken {bal['taken_all_types']} approved leave day(s) this year "
                    f"({bal['used']} from your annual quota of {bal['quota']}).")
        return (f"You have {bal['remaining']} quota day(s) left out of {bal['quota']} "
                f"({bal['pending']} more are tied up in pending requests).")
    if _has(q, "late"):
        if not rec:
            return "You have not checked in today, so there is no late status yet."
        return ("Yes, you were late today (checked in at "
                f"{rec['check_in']})." if is_late(rec["check_in"], get_company())
                else f"No, you were on time today (checked in at {rec['check_in']}).")
    if _has(q, "check in", "checkin", "checked in", "what time", "kab"):
        return (f"You checked in today at {rec['check_in']}." if rec
                else "You have not checked in today.")
    if _has(q, "hour", "worked", "work"):
        return f"You worked {calculate_weekly_working_hours(employee_id, now):.2f} completed hour(s) this week."
    if _has(q, "department", "dept"):
        return f"Your department is {emp['department']} ({emp['title']})."
    if _has(q, "salary", "pay", "tankhwah"):
        return f"Your monthly salary is Rs. {emp['salary']:,.0f}."
    return "Sorry, I did not understand that. " + HELP_EMP
