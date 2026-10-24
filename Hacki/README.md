# HCM Lite (Streamlit + Python)

Human Capital Management app: employees, attendance, leaves, payslips, announcements,
reports and a rule-based Smart Helper. Starts **empty** - no dummy data.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
First screen = setup (company + Admin). Then log in, add employees in **Employees**,
and log in as an employee (different browser/incognito) to check in and apply for leave.

## Files
- `app.py`   - Streamlit UI (all pages)
- `logic.py` - storage, auth, attendance, leave, payroll, Smart Helper
- `data/`    - JSON files created at runtime (hcm_company, hcm_users, hcm_attendance,
               hcm_leaves, hcm_session, hcm_announcements)

## Business rules
- Late: check-in **after** start + grace (09:15:00 is not late, 09:15:01 is).
- Completed shift < 5 h = Half Day. Precedence: Half Day > Late > Present.
- Absent: working day, after the day ended (office end time), no record, no approved leave.
- Annual + Casual leave use the yearly quota; Sick + Unpaid do not.
- Payslip: per-day = salary / working days; deduction = per-day x (absent + 0.5 x half-days).
- Employees are deactivated, never deleted, so history stays correct.
- Settings changes affect future check-ins; stored attendance statuses are not rewritten.

## Limitations
JSON files + simple password hashing are for learning/hackathon use, not production
security. Data lives on the machine running Streamlit (no multi-server sync).
To deploy: Streamlit Community Cloud (note: its disk is temporary, data can reset).
