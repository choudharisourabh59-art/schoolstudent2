"""School Information System - Streamlit app (PostgreSQL-backed, role-based)."""
import hashlib, hmac, secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from sqlalchemy import bindparam, create_engine, text

st.set_page_config(page_title="School Information System", layout="wide")

TZ = ZoneInfo("Asia/Kolkata")
IDLE_MINUTES = 30
GRADE_SCALE = [(90, "A+"), (80, "A"), (70, "B"), (60, "C"), (50, "D"), (40, "E"), (0, "F")]
ROLES = ["admin", "principal", "teacher", "accountant", "parent", "student"]
SCHOOL_WIDE = ("admin", "principal", "accountant")
PAGES = {
    "admin": ["Dashboard", "Students", "Users", "Attendance", "Grades", "Fees", "Report card", "Audit log"],
    "principal": ["Dashboard", "Students", "Report card", "Audit log"],
    "teacher": ["Attendance", "Grades", "Report card"],
    "accountant": ["Fees"],
    "parent": ["Report card", "Attendance", "Fees"],
    "student": ["Report card", "Attendance", "Fees"],
}
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
       pw_hash TEXT NOT NULL, role TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
       failed INT NOT NULL DEFAULT 0, locked_until TIMESTAMPTZ)""",
    """CREATE TABLE IF NOT EXISTS students(id SERIAL PRIMARY KEY, admission_no TEXT UNIQUE NOT NULL,
       name TEXT NOT NULL, class_name TEXT NOT NULL,
       user_id INT REFERENCES users(id) ON DELETE SET NULL,
       parent_user_id INT REFERENCES users(id) ON DELETE SET NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_students_class ON students(class_name)",
    """CREATE TABLE IF NOT EXISTS teacher_classes(user_id INT REFERENCES users(id) ON DELETE CASCADE,
       class_name TEXT, PRIMARY KEY(user_id, class_name))""",
    """CREATE TABLE IF NOT EXISTS attendance(student_id INT REFERENCES students(id) ON DELETE CASCADE,
       day DATE NOT NULL, status CHAR(1) NOT NULL, marked_by TEXT, PRIMARY KEY(student_id, day))""",
    "CREATE INDEX IF NOT EXISTS ix_att_day ON attendance(day)",
    """CREATE TABLE IF NOT EXISTS grades(student_id INT REFERENCES students(id) ON DELETE CASCADE,
       subject TEXT, exam TEXT, marks NUMERIC(6,2) NOT NULL, max_marks NUMERIC(6,2) NOT NULL,
       weight NUMERIC(5,2) NOT NULL DEFAULT 1, PRIMARY KEY(student_id, subject, exam))""",
    """CREATE TABLE IF NOT EXISTS fees(id SERIAL PRIMARY KEY,
       student_id INT REFERENCES students(id) ON DELETE CASCADE, title TEXT NOT NULL,
       amount NUMERIC(12,2) NOT NULL, due_date DATE NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS payments(id SERIAL PRIMARY KEY,
       fee_id INT REFERENCES fees(id) ON DELETE RESTRICT, amount NUMERIC(12,2) NOT NULL,
       paid_on DATE NOT NULL, method TEXT, received_by TEXT)""",
    """CREATE TABLE IF NOT EXISTS audit(id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
       username TEXT, action TEXT, detail TEXT)""",
]


# ---------- database helpers ----------
@st.cache_resource
def engine():
    try:
        url = st.secrets["DATABASE_URL"]
    except Exception:
        st.error("DATABASE_URL is not set. Add it under App settings > Secrets (see secrets.toml.example).")
        st.stop()
    eng = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    with eng.begin() as c:
        for stmt in SCHEMA:
            c.execute(text(stmt))
    return eng


def _stmt(sql, params):
    s = text(sql)
    lists = [bindparam(k, expanding=True) for k, v in params.items() if isinstance(v, (list, tuple))]
    return s.bindparams(*lists) if lists else s


def q(sql, **p):
    with engine().connect() as c:
        return pd.read_sql(_stmt(sql, p), c, params=p)


def run(sql, **p):
    with engine().begin() as c:
        return c.execute(_stmt(sql, p), p).rowcount


def run_many(sql, rows):
    if rows:
        with engine().begin() as c:
            c.execute(text(sql), rows)


def today():
    return datetime.now(TZ).date()


def user():
    return st.session_state.get("user")


def audit(action, detail=""):
    u = user()
    run("INSERT INTO audit(username, action, detail) VALUES (:u, :a, :d)",
        u=u["username"] if u else None, a=action, d=detail[:500])


# ---------- passwords ----------
def hash_pw(pw):
    salt = secrets.token_hex(16)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 300_000).hex()}"


def check_pw(pw, stored):
    salt, h = stored.split("$")
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 300_000).hex(), h)


def pw_ok(pw):
    if len(pw) < 10:
        st.error("Password must be at least 10 characters.")
        return False
    return True


# ---------- access scoping (single source of truth) ----------
def my_students():
    u = user()
    base = "SELECT id, admission_no, name, class_name FROM students"
    if u["role"] in SCHOOL_WIDE:
        return q(base + " ORDER BY class_name, name")
    if u["role"] == "teacher":
        return q(base + " WHERE class_name IN (SELECT class_name FROM teacher_classes WHERE user_id=:i) "
                 "ORDER BY class_name, name", i=u["id"])
    if u["role"] == "parent":
        return q(base + " WHERE parent_user_id=:i ORDER BY name", i=u["id"])
    return q(base + " WHERE user_id=:i", i=u["id"])


def my_classes():
    u = user()
    if u["role"] == "admin":
        return q("SELECT DISTINCT class_name c FROM students ORDER BY 1")["c"].tolist()
    return q("SELECT class_name c FROM teacher_classes WHERE user_id=:i ORDER BY 1", i=u["id"])["c"].tolist()


def pick_student(label="Student"):
    df = my_students()
    if df.empty:
        st.info("No students available for your account.")
        return None
    opts = {f"{r.name} ({r.admission_no}, {r.class_name})": int(r.id) for r in df.itertuples()}
    return opts[st.selectbox(label, list(opts))]


def letter(p):
    for floor, name in GRADE_SCALE:
        if p >= floor:
            return name


# ---------- auth ----------
def first_run():
    st.title("First-time setup")
    st.info("Create the first administrator account.")
    with st.form("setup"):
        u = st.text_input("Admin username")
        p = st.text_input("Password (min 10 characters)", type="password")
        ok = st.form_submit_button("Create admin")
    if ok and u.strip() and pw_ok(p):
        run("INSERT INTO users(username, pw_hash, role) VALUES (:u, :h, 'admin')", u=u.strip(), h=hash_pw(p))
        st.success("Admin created. Reload the page to sign in.")


def login_view():
    st.title("School Information System")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in")
    if not ok:
        return
    r = q("SELECT *, (locked_until IS NOT NULL AND locked_until > now()) AS locked "
          "FROM users WHERE username=:u", u=u.strip())
    bad = "Invalid username or password."
    if r.empty:
        st.error(bad)
        return
    row = r.iloc[0]
    uid = int(row["id"])
    if row["locked"]:
        st.error("Too many failed attempts. Try again in 15 minutes.")
        return
    if not row["active"] or not check_pw(p, row["pw_hash"]):
        run("UPDATE users SET failed=failed+1, locked_until=CASE WHEN failed+1>=5 "
            "THEN now()+interval '15 minutes' ELSE locked_until END WHERE id=:i", i=uid)
        st.error(bad)
        return
    run("UPDATE users SET failed=0, locked_until=NULL WHERE id=:i", i=uid)
    st.session_state["user"] = {"id": uid, "username": row["username"], "role": row["role"]}
    st.session_state["last"] = datetime.now(TZ)
    audit("login")
    st.rerun()


# ---------- pages ----------
def page_dashboard():
    st.header("Dashboard")
    n = q("SELECT COUNT(*) n FROM students").iloc[0]["n"]
    att = q("SELECT COUNT(*) t, COUNT(*) FILTER (WHERE status IN ('P','L')) p FROM attendance "
            "WHERE day >= :d", d=today() - pd.Timedelta(days=30)).iloc[0]
    fee = q("SELECT COALESCE((SELECT SUM(amount) FROM fees),0) b, "
            "COALESCE((SELECT SUM(amount) FROM payments),0) c").iloc[0]
    b, c = float(fee["b"]), float(fee["c"])
    k = st.columns(4)
    k[0].metric("Students", int(n))
    k[1].metric("Attendance (30 days)", f"{att['p'] / att['t'] * 100:.1f}%" if att["t"] else "n/a")
    k[2].metric("Fees collected", f"{c:,.0f}")
    k[3].metric("Fees outstanding", f"{b - c:,.0f}")
    left, right = st.columns(2)
    left.subheader("Students per class")
    left.bar_chart(q("SELECT class_name, COUNT(*) n FROM students GROUP BY 1 ORDER BY 1").set_index("class_name"))
    right.subheader("Daily attendance % (30 days)")
    d = q("SELECT day, ROUND(100.0*COUNT(*) FILTER (WHERE status IN ('P','L'))/COUNT(*),1) pct "
          "FROM attendance WHERE day >= :d GROUP BY day ORDER BY day", d=today() - pd.Timedelta(days=30))
    if d.empty:
        right.info("No attendance recorded yet.")
    else:
        right.line_chart(d.set_index("day"))


def page_students():
    st.header("Students")
    st.dataframe(my_students().drop(columns="id"), use_container_width=True, hide_index=True)
    if user()["role"] != "admin":
        return
    with st.expander("Add a student"):
        with st.form("add_student", clear_on_submit=True):
            a, n, c = st.text_input("Admission no."), st.text_input("Full name"), st.text_input("Class (e.g. 5-A)")
            if st.form_submit_button("Add") and a.strip() and n.strip() and c.strip():
                done = run("INSERT INTO students(admission_no,name,class_name) VALUES (:a,:n,:c) "
                           "ON CONFLICT (admission_no) DO NOTHING", a=a.strip(), n=n.strip(), c=c.strip())
                if done:
                    audit("student_add", a.strip()); st.success("Added.")
                else:
                    st.error("That admission number already exists.")
    with st.expander("Import from CSV"):
        st.caption("Columns required: admission_no, name, class_name. Existing admission numbers are updated.")
        f = st.file_uploader("CSV file", type="csv")
        if f and st.button("Import"):
            df = pd.read_csv(f, dtype=str).fillna("")
            if not {"admission_no", "name", "class_name"} <= set(df.columns):
                st.error("Missing required columns.")
            else:
                df = df[["admission_no", "name", "class_name"]].apply(lambda s: s.str.strip())
                df = df[(df != "").all(axis=1)].drop_duplicates("admission_no")
                run_many("INSERT INTO students(admission_no,name,class_name) VALUES (:admission_no,:name,:class_name) "
                         "ON CONFLICT (admission_no) DO UPDATE SET name=EXCLUDED.name, class_name=EXCLUDED.class_name",
                         df.to_dict("records"))
                audit("student_import", f"{len(df)} rows"); st.success(f"Imported {len(df)} students.")


def page_users():
    st.header("Users")
    st.dataframe(q("SELECT username, role, active FROM users ORDER BY role, username"),
                 use_container_width=True, hide_index=True)
    with st.expander("Create user"):
        with st.form("new_user", clear_on_submit=True):
            u, p = st.text_input("Username"), st.text_input("Password (min 10)", type="password")
            role = st.selectbox("Role", ROLES)
            if st.form_submit_button("Create") and u.strip() and pw_ok(p):
                if run("INSERT INTO users(username,pw_hash,role) VALUES (:u,:h,:r) ON CONFLICT (username) DO NOTHING",
                       u=u.strip(), h=hash_pw(p), r=role):
                    audit("user_create", f"{u.strip()} ({role})"); st.success("Created.")
                else:
                    st.error("Username already taken.")
    users = q("SELECT id, username, role FROM users")
    with st.expander("Reset password / deactivate"):
        who = st.selectbox("User", users["username"].tolist())
        npw = st.text_input("New password", type="password")
        c1, c2 = st.columns(2)
        if c1.button("Set password") and pw_ok(npw):
            run("UPDATE users SET pw_hash=:h, failed=0, locked_until=NULL WHERE username=:u", h=hash_pw(npw), u=who)
            audit("password_reset", who); st.success("Updated.")
        if c2.button("Deactivate"):
            if who == user()["username"]:
                st.error("You cannot deactivate yourself.")
            else:
                run("UPDATE users SET active=FALSE WHERE username=:u", u=who); audit("user_deactivate", who)
                st.success("Deactivated.")
    with st.expander("Link accounts to students / assign teacher classes"):
        stu = q("SELECT id, name, admission_no FROM students ORDER BY name")
        smap = {f"{r.name} ({r.admission_no})": int(r.id) for r in stu.itertuples()}
        if smap:
            s = smap[st.selectbox("Student", list(smap))]
            for role, col in (("parent", "parent_user_id"), ("student", "user_id")):
                cand = users[users["role"] == role]
                if not cand.empty:
                    pick = st.selectbox(f"{role.title()} account", cand["username"].tolist(), key=col)
                    if st.button(f"Link {role}", key="b" + col):
                        uid = int(cand[cand["username"] == pick]["id"].iloc[0])
                        run(f"UPDATE students SET {col}=:u WHERE id=:s", u=uid, s=s)
                        audit("link", f"{role} {pick} -> student {s}"); st.success("Linked.")
        teachers = users[users["role"] == "teacher"]
        classes = q("SELECT DISTINCT class_name c FROM students ORDER BY 1")["c"].tolist()
        if not teachers.empty and classes:
            t = st.selectbox("Teacher", teachers["username"].tolist())
            tid = int(teachers[teachers["username"] == t]["id"].iloc[0])
            cur = q("SELECT class_name c FROM teacher_classes WHERE user_id=:i", i=tid)["c"].tolist()
            sel = st.multiselect("Classes", classes, default=[c for c in cur if c in classes])
            if st.button("Save classes"):
                run("DELETE FROM teacher_classes WHERE user_id=:i", i=tid)
                run_many("INSERT INTO teacher_classes(user_id,class_name) VALUES (:i,:c)",
                         [{"i": tid, "c": c} for c in sel])
                audit("teacher_classes", f"{t}: {sel}"); st.success("Saved.")


def page_attendance():
    st.header("Attendance")
    u = user()
    if u["role"] in ("parent", "student"):
        sid = pick_student()
        if sid:
            d = q("SELECT day, status FROM attendance WHERE student_id=:i ORDER BY day DESC", i=sid)
            if d.empty:
                st.info("No attendance recorded yet.")
            else:
                st.metric("Attendance", f"{d['status'].isin(['P', 'L']).mean() * 100:.1f}%")
                st.dataframe(d, use_container_width=True, hide_index=True)
        return
    classes = my_classes()
    if not classes:
        st.info("No classes assigned to you.")
        return
    cls = st.selectbox("Class", classes)
    day = st.date_input("Date", today(), max_value=today())
    df = q("SELECT s.id, s.admission_no, s.name, COALESCE(a.status,'P') status FROM students s "
           "LEFT JOIN attendance a ON a.student_id=s.id AND a.day=:d WHERE s.class_name=:c ORDER BY s.name",
           d=day, c=cls).set_index("id")
    edited = st.data_editor(df, hide_index=True, use_container_width=True, disabled=["admission_no", "name"],
                            column_config={"status": st.column_config.SelectboxColumn(
                                "Status (P/A/L/E)", options=["P", "A", "L", "E"], required=True)})
    if st.button("Save attendance"):
        run_many("INSERT INTO attendance(student_id,day,status,marked_by) VALUES (:i,:d,:s,:m) "
                 "ON CONFLICT (student_id,day) DO UPDATE SET status=EXCLUDED.status, marked_by=EXCLUDED.marked_by",
                 [{"i": int(i), "d": day, "s": r.status, "m": u["username"]} for i, r in edited.iterrows()])
        audit("attendance_save", f"{cls} {day}"); st.success("Saved.")


def page_grades():
    st.header("Enter grades")
    classes = my_classes()
    if not classes:
        st.info("No classes assigned to you.")
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    cls = c1.selectbox("Class", classes)
    subject, exam = c2.text_input("Subject").strip(), c3.text_input("Exam", "Unit 1").strip()
    mx = c4.number_input("Max marks", 1.0, 1000.0, 100.0)
    wt = c5.number_input("Weight", 0.1, 100.0, 1.0)
    if not subject or not exam:
        return
    df = q("SELECT s.id, s.admission_no, s.name, g.marks FROM students s LEFT JOIN grades g ON g.student_id=s.id "
           "AND g.subject=:s AND g.exam=:e WHERE s.class_name=:c ORDER BY s.name",
           s=subject, e=exam, c=cls).set_index("id")
    df["marks"] = df["marks"].astype(float)
    edited = st.data_editor(df, hide_index=True, use_container_width=True, disabled=["admission_no", "name"])
    if st.button("Save grades"):
        m = edited["marks"].dropna()
        if ((m < 0) | (m > mx)).any():
            st.error(f"Marks must be between 0 and {mx}.")
            return
        run_many("INSERT INTO grades(student_id,subject,exam,marks,max_marks,weight) VALUES (:i,:s,:e,:m,:x,:w) "
                 "ON CONFLICT (student_id,subject,exam) DO UPDATE SET marks=EXCLUDED.marks, "
                 "max_marks=EXCLUDED.max_marks, weight=EXCLUDED.weight",
                 [{"i": int(i), "s": subject, "e": exam, "m": float(v), "x": mx, "w": wt} for i, v in m.items()])
        audit("grades_save", f"{cls} {subject} {exam}"); st.success("Saved.")


def page_report():
    st.header("Report card")
    sid = pick_student()
    if not sid:
        return
    g = q("SELECT subject, exam, marks, max_marks, weight FROM grades WHERE student_id=:i", i=sid)
    if g.empty:
        st.info("No grades yet.")
        return
    g[["marks", "max_marks", "weight"]] = g[["marks", "max_marks", "weight"]].astype(float)
    g["earned"] = g["marks"] / g["max_marks"] * g["weight"]
    s = g.groupby("subject").agg(earned=("earned", "sum"), w=("weight", "sum")).reset_index()
    s["percentage"] = (s["earned"] / s["w"] * 100).round(2)
    s["grade"] = s["percentage"].map(letter)
    overall = s["percentage"].mean()
    st.metric("Overall", f"{overall:.2f}%  ({letter(overall)})")
    st.dataframe(s[["subject", "percentage", "grade"]], use_container_width=True, hide_index=True)
    st.bar_chart(s.set_index("subject")["percentage"])
    with st.expander("All exam marks"):
        st.dataframe(g.drop(columns="earned"), use_container_width=True, hide_index=True)


def page_fees():
    st.header("Fees")
    u = user()
    ids = my_students()["id"].astype(int).tolist()
    inv = q("SELECT f.id, s.name, f.title, f.amount, f.due_date, COALESCE(SUM(p.amount),0) paid, "
            "f.amount-COALESCE(SUM(p.amount),0) balance FROM fees f JOIN students s ON s.id=f.student_id "
            "LEFT JOIN payments p ON p.fee_id=f.id WHERE f.student_id IN :ids "
            "GROUP BY f.id, s.name ORDER BY f.due_date", ids=ids)
    st.dataframe(inv, use_container_width=True, hide_index=True)
    if u["role"] not in ("admin", "accountant"):
        return
    with st.expander("Create invoice"):
        sid = pick_student("Student for invoice")
        t, amt, due = st.text_input("Title (e.g. Term 1 fee)"), st.number_input("Amount", 1.0, 10_000_000.0, 1000.0), st.date_input("Due date")
        if sid and st.button("Create invoice") and t.strip():
            run("INSERT INTO fees(student_id,title,amount,due_date) VALUES (:s,:t,:a,:d)", s=sid, t=t.strip(), a=amt, d=due)
            audit("invoice_create", f"student {sid} {t} {amt}"); st.success("Created.")
    with st.expander("Record payment"):
        open_inv = inv[inv["balance"].astype(float) > 0]
        if open_inv.empty:
            st.info("No outstanding invoices.")
        else:
            lbl = {f"#{r.id} {r.name} - {r.title} (balance {float(r.balance):,.2f})": (int(r.id), float(r.balance))
                   for r in open_inv.itertuples()}
            fid, bal = lbl[st.selectbox("Invoice", list(lbl))]
            amt = st.number_input("Amount received", 0.0, 10_000_000.0, 0.0)
            method = st.selectbox("Method", ["cash", "upi", "card", "bank transfer", "cheque"])
            if st.button("Record payment"):
                if amt <= 0 or amt > bal:
                    st.error(f"Amount must be above 0 and at most {bal:,.2f}.")
                else:
                    run("INSERT INTO payments(fee_id,amount,paid_on,method,received_by) VALUES (:f,:a,:d,:m,:u)",
                        f=fid, a=amt, d=today(), m=method, u=u["username"])
                    audit("payment", f"invoice {fid} {amt}"); st.success("Recorded.")


def page_audit():
    st.header("Audit log (latest 500)")
    st.dataframe(q("SELECT ts, username, action, detail FROM audit ORDER BY id DESC LIMIT 500"),
                 use_container_width=True, hide_index=True)


PAGE_FN = {"Dashboard": page_dashboard, "Students": page_students, "Users": page_users,
           "Attendance": page_attendance, "Grades": page_grades, "Fees": page_fees,
           "Report card": page_report, "Audit log": page_audit}


def main():
    engine()
    if q("SELECT COUNT(*) n FROM users").iloc[0]["n"] == 0:
        return first_run()
    if not user():
        return login_view()
    if (datetime.now(TZ) - st.session_state["last"]).total_seconds() > IDLE_MINUTES * 60:
        st.session_state.clear()
        st.warning("Signed out after inactivity.")
        return login_view()
    st.session_state["last"] = datetime.now(TZ)
    u = user()
    st.sidebar.write(f"**{u['username']}** ({u['role']})")
    page = st.sidebar.radio("Menu", PAGES[u["role"]])
    if st.sidebar.button("Sign out"):
        audit("logout")
        st.session_state.clear()
        st.rerun()
    PAGE_FN[page]()


main()
