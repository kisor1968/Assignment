"""
Departmental Assessment & Grading Portal  (single-file edition)

Run locally :  streamlit run question.py
Streamlit Community Cloud: set "Main file path" to question.py and add requirements.txt (+ packages.txt).

Roles: students (no login) / teachers (department-scoped, password) / admin.
First run prints a one-time `admin` password in the server log - sign in, change it, then
create teacher accounts from the Admin Console.

NOTE: data is saved in ./data . On Streamlit Community Cloud this folder is wiped on every
restart - use a server with a persistent disk (or an external database) for real use.
"""
import streamlit as st

st.set_page_config(page_title="Departmental Assessment Portal", page_icon="🎓", layout="centered")

import hashlib
import hmac
import inspect
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import streamlit.components.v1 as components

ss = st.session_state


# ======================================================================
# CONFIG — Central settings. Edit DEPARTMENTS / INSTITUTION_NAME / GRADE_SCALE to suit your college.
# ======================================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PORTAL_DATA_DIR", BASE_DIR / "data"))
AUTH_DIR = DATA_DIR / "auth"

INSTITUTION_NAME = "Your College Name"

DEPARTMENTS = [
    "Physics", "Chemistry", "Mathematics", "Computer Science",
    "Botany", "Zoology", "Economics", "English",
]

QUESTION_TYPES = {
    "mcq": "Multiple Choice (MCQ)",
    "short": "Short Answer",
    "long": "Long Answer / Descriptive",
    "code": "Programming / Code",
}
DEFAULT_MARKS = {"mcq": 1.0, "short": 2.0, "long": 5.0, "code": 10.0}

DOC_EXTS = ["pdf", "png", "jpg", "jpeg"]      # descriptive answer scripts / output screenshots
CODE_EXTS = ["py", "txt"]                      # code files / editor output
MAX_UPLOAD_MB = 10

PASS_PERCENT = 40.0
GRADE_SCALE = [  # (minimum %, grade, description)
    (90, "O", "Outstanding"), (80, "A+", "Excellent"), (70, "A", "Very Good"),
    (60, "B+", "Good"), (50, "B", "Above Average"), (40, "C", "Pass"), (0, "F", "Fail"),
]

# Security
PBKDF2_ITERATIONS = 600_000
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 5
SESSION_TIMEOUT_MIN = 30
MIN_PASSWORD_LEN = 10


# ======================================================================
# GRADING — Question normalisation and mark / grade calculations (pure functions, no Streamlit).
# ======================================================================
def natural_key(value):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(value))]


def normalize_question(q):
    q = dict(q)
    q.setdefault("type", "mcq")
    q["number"] = str(q.get("number") or q.get("id"))
    q["identifier"] = str(q.get("identifier") or "")
    q["max_marks"] = float(q.get("max_marks") or DEFAULT_MARKS.get(q["type"], 1.0))
    q.setdefault("options", [])
    q.setdefault("answer", "")
    return q


def grade_for(percent):
    for lo, grade, desc in GRADE_SCALE:
        if percent >= lo:
            return grade, desc
    return "F", "Fail"


def totals(sub):
    paper = sub.get("paper", [])
    marks = sub.get("marks", {})
    max_total = sum(float(q["max_marks"]) for q in paper)
    got = 0.0
    for q in paper:
        got += min(float(marks.get(str(q["id"]), 0) or 0), float(q["max_marks"]))
    pct = got / max_total * 100 if max_total else 0.0
    grade, desc = grade_for(pct)
    return {
        "obtained": round(got, 2), "max": round(max_total, 2), "percent": round(pct, 2),
        "grade": grade, "grade_desc": desc, "passed": pct >= PASS_PERCENT,
    }


# ======================================================================
# STORAGE — JSON-file persistence, one folder per department. Atomic writes + a process-wide lock.
# ======================================================================
@st.cache_resource
def _get_lock():
    # one lock shared by all sessions, surviving Streamlit script reruns
    return threading.RLock()


_LOCK = _get_lock()


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def read_json(path, default):
    path = Path(path)
    with _LOCK:
        if not path.exists() or path.stat().st_size == 0:
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class DeptStore:
    """All questions, submissions, uploads and report cards of ONE department."""

    def __init__(self, dept):
        self.dept = dept
        self.slug = slugify(dept)
        self.dir = DATA_DIR / "departments" / self.slug
        self.uploads_dir = self.dir / "uploads"
        self.reports_dir = self.dir / "reports"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._q_path = self.dir / "questions.json"
        self._s_path = self.dir / "submissions.json"
        self._migrate_legacy()

    def _migrate_legacy(self):
        """Import the old single-department question.json into Physics (once)."""
        legacy = BASE_DIR / "question.json"
        if self.slug == "physics" and not self._q_path.exists() and legacy.exists():
            shutil.copy(legacy, self._q_path)

    # ---------------- questions ----------------
    def questions(self):
        raw = read_json(self._q_path, [])
        qs = [normalize_question(q) for q in raw]
        return sorted(qs, key=lambda q: natural_key(q["number"]))

    def save_questions(self, questions):
        write_json(self._q_path, questions)

    def number_exists(self, number, exclude_id=None):
        return any(
            q["number"].strip().lower() == str(number).strip().lower() and q["id"] != exclude_id
            for q in self.questions()
        )

    def free_number(self, preferred=None):
        taken = {q["number"].strip().lower() for q in self.questions()}
        if preferred and str(preferred).lower() not in taken:
            return str(preferred)
        n = 1
        while str(n) in taken:
            n += 1
        return str(n)

    def add_question(self, q):
        with _LOCK:
            qs = read_json(self._q_path, [])
            q = dict(q)
            q["id"] = max([x.get("id", 0) for x in qs], default=0) + 1
            qs.append(q)
            self.save_questions(qs)
            return q["id"]

    # ---------------- submissions ----------------
    def submissions(self):
        return read_json(self._s_path, [])

    def get_submission(self, sub_id):
        return next((s for s in self.submissions() if s["submission_id"] == sub_id), None)

    def add_submission(self, sub):
        with _LOCK:
            subs = self.submissions()
            seq = max([int(s["submission_id"].split("-")[-1]) for s in subs], default=0) + 1
            sub = dict(sub)
            sub["submission_id"] = f"{self.slug[:3].upper()}-{seq:04d}"
            subs.append(sub)
            write_json(self._s_path, subs)
            return sub["submission_id"]

    def update_submission(self, sub_id, updates):
        with _LOCK:
            subs = self.submissions()
            for s in subs:
                if s["submission_id"] == sub_id:
                    s.update(updates)
                    write_json(self._s_path, subs)
                    return s
        return None

    def delete_submission(self, sub_id):
        with _LOCK:
            subs = self.submissions()
            target = next((s for s in subs if s["submission_id"] == sub_id), None)
            if not target:
                return
            for ans in target.get("answers", {}).values():
                for f in ans.get("files", {}).values():
                    p = self.resolve_upload(f.get("path", ""))
                    if p and p.exists():
                        p.unlink()
            rp = self.reports_dir / f"{sub_id}.pdf"
            if rp.exists():
                rp.unlink()
            write_json(self._s_path, [s for s in subs if s["submission_id"] != sub_id])

    # ---------------- uploads ----------------
    def save_upload(self, sub_id, qid, slot, filename, data):
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[-80:]
        rel = f"uploads/{sub_id}_Q{qid}_{slot}_{secrets.token_hex(3)}_{safe}"
        (self.dir / rel).write_bytes(data)
        return rel

    def resolve_upload(self, rel):
        """Resolve a stored relative path, refusing anything outside the uploads folder."""
        if not rel:
            return None
        p = (self.dir / rel).resolve()
        try:
            p.relative_to(self.uploads_dir.resolve())
        except ValueError:
            return None
        return p

    def report_path(self, sub_id):
        return self.reports_dir / f"{sub_id}.pdf"


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================
# AUTH — Authentication, role-based access control (RBAC), lockouts and audit log.
# ======================================================================
_ACCOUNTS = AUTH_DIR / "accounts.json"
_LOCKS = AUTH_DIR / "lockouts.json"
_AUDIT = AUTH_DIR / "audit.log"
RESERVED_USERNAMES = {"admin", "administrator", "root"}


# ---------------------------------------------------------------- hashing
def hash_secret(secret, iterations=None):
    iterations = iterations or PBKDF2_ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, iterations)
    return {"salt": salt.hex(), "hash": digest.hex(), "iterations": iterations}


def verify_secret(secret, rec):
    digest = hashlib.pbkdf2_hmac(
        "sha256", secret.encode(), bytes.fromhex(rec["salt"]), int(rec["iterations"])
    )
    return hmac.compare_digest(digest.hex(), rec["hash"])


@st.cache_resource
def _dummy_record():
    return hash_secret("dummy-value-for-constant-time-checks")


def password_problem(pw):
    if len(pw) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        return "Password must contain both letters and digits."
    return None


# ---------------------------------------------------------------- audit & lockouts
def audit(event, user="-", detail=""):
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    with open(_AUDIT, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {event} | {user} | {detail}\n")


def read_audit(limit=60):
    if not _AUDIT.exists():
        return []
    return _AUDIT.read_text(encoding="utf-8").splitlines()[-limit:][::-1]


def lock_remaining(key):
    rec = read_json(_LOCKS, {}).get(key)
    if not rec:
        return 0
    return max(0, int(rec.get("locked_until", 0) - time.time()))


def register_failure(key):
    locks = read_json(_LOCKS, {})
    rec = locks.get(key, {"count": 0, "locked_until": 0})
    rec["count"] += 1
    if rec["count"] >= MAX_FAILED_LOGINS:
        rec["locked_until"] = time.time() + LOCKOUT_MINUTES * 60
        rec["count"] = 0
    locks[key] = rec
    write_json(_LOCKS, locks)


def clear_failures(key):
    locks = read_json(_LOCKS, {})
    if key in locks:
        del locks[key]
        write_json(_LOCKS, locks)


# ---------------------------------------------------------------- accounts
def _load():
    data = read_json(_ACCOUNTS, {})
    data.setdefault("teachers", {})
    return data


def ensure_admin_bootstrap():
    """First run: create the admin account with a random password printed to the SERVER console."""
    data = _load()
    if data.get("admin"):
        return
    temp = secrets.token_urlsafe(9)
    rec = hash_secret(temp)
    rec["must_change"] = True
    data["admin"] = rec
    write_json(_ACCOUNTS, data)
    audit("admin_bootstrap", "system", "admin account created")
    bar = "=" * 64
    print(f"\n{bar}\n  FIRST RUN - administrator account created\n"
          f"  Username : admin\n  Password : {temp}\n"
          f"  (shown only once - you must change it at first login)\n{bar}\n", flush=True)


def apply_admin_reset_secret():
    """Recovery: if ADMIN_RESET_PASSWORD is set in Streamlit Secrets, make it the admin password.

    The admin must change it at next login. It is applied once per secret value (so changing the
    password later is not overwritten); put a different value in Secrets to reset again.
    """
    if st.session_state.get("_admin_reset_checked"):
        return
    st.session_state["_admin_reset_checked"] = True
    try:
        pw = st.secrets.get("ADMIN_RESET_PASSWORD")
    except Exception:  # no secrets configured
        return
    if not pw:
        return
    pw = str(pw)
    data = _load()
    done = data.get("admin_reset_marker")
    if done and verify_secret(pw, done):
        return
    if password_problem(pw):
        st.error("ADMIN_RESET_PASSWORD in Secrets is too weak: " + password_problem(pw))
        return
    rec = hash_secret(pw)
    rec["must_change"] = True
    data["admin"] = rec
    data["admin_reset_marker"] = hash_secret(pw)
    write_json(_ACCOUNTS, data)
    locks = read_json(_LOCKS, {})
    write_json(_LOCKS, {k: v for k, v in locks.items() if not k.startswith("login:*:")})
    audit("admin_password_reset", "system", "via Streamlit Secrets")


def list_teachers(dept):
    return sorted(_load()["teachers"].get(slugify(dept), {}).keys())


def add_teacher(dept, username, password):
    username = username.strip().lower()
    if not username or username in RESERVED_USERNAMES:
        return "Choose a different username."
    problem = password_problem(password)
    if problem:
        return problem
    data = _load()
    dept_accounts = data["teachers"].setdefault(slugify(dept), {})
    if username in dept_accounts:
        return "That username already exists in this department."
    rec = hash_secret(password)
    rec.update({"must_change": True, "created": datetime.now().isoformat(timespec="seconds")})
    dept_accounts[username] = rec
    write_json(_ACCOUNTS, data)
    audit("teacher_created", "admin", f"{dept}/{username}")
    return None


def reset_teacher_password(dept, username, password):
    problem = password_problem(password)
    if problem:
        return problem
    data = _load()
    acct = data["teachers"].get(slugify(dept), {}).get(username)
    if not acct:
        return "Account not found."
    rec = hash_secret(password)
    rec.update({"must_change": True, "created": acct.get("created", "")})
    data["teachers"][slugify(dept)][username] = rec
    write_json(_ACCOUNTS, data)
    clear_failures(f"login:{slugify(dept)}:{username}")
    audit("teacher_password_reset", "admin", f"{dept}/{username}")
    return None


def delete_teacher(dept, username):
    data = _load()
    data["teachers"].get(slugify(dept), {}).pop(username, None)
    write_json(_ACCOUNTS, data)
    audit("teacher_deleted", "admin", f"{dept}/{username}")


# ---------------------------------------------------------------- session / RBAC
def current_user():
    """Return the logged-in user dict (enforcing idle timeout) or None for students."""
    user = st.session_state.get("auth")
    if not user:
        return None
    if time.time() - user["last_active"] > SESSION_TIMEOUT_MIN * 60:
        audit("session_timeout", user["username"])
        st.session_state.pop("auth", None)
        st.session_state["flash"] = "⏱️ Your session expired. Please sign in again."
        return None
    user["last_active"] = time.time()
    return user


def is_admin(user):
    return bool(user) and user["role"] == "admin" and not user.get("must_change")


def can_manage(user, dept):
    """True only for the department's own teacher (or the admin) - never for students."""
    if not user or user.get("must_change") or not dept:
        return False
    if user["role"] == "admin":
        return True
    return user["role"] == "teacher" and user["dept"] == slugify(dept)


def login(username, password, dept):
    """Returns (ok, message)."""
    uname = username.strip().lower()
    if not uname or not password:
        return False, "Enter both username and password."
    is_admin_login = uname == "admin"
    if not is_admin_login and not dept:
        return False, "Select your department on the Home page first."
    scope = "*" if is_admin_login else slugify(dept)
    key = f"login:{scope}:{uname}"
    wait = lock_remaining(key)
    if wait:
        return False, f"Too many failed attempts. Try again in {max(1, wait // 60 + 1)} minute(s)."

    data = _load()
    rec = data.get("admin") if is_admin_login else data["teachers"].get(scope, {}).get(uname)
    ok = verify_secret(password, rec or _dummy_record()) and rec is not None
    if not ok:
        register_failure(key)
        audit("login_failed", uname, scope)
        return False, "Invalid username or password."

    clear_failures(key)
    st.session_state["auth"] = {
        "role": "admin" if is_admin_login else "teacher",
        "username": uname,
        "dept": None if is_admin_login else scope,
        "must_change": bool(rec.get("must_change")),
        "last_active": time.time(),
    }
    audit("login_ok", uname, scope)
    return True, "Signed in."


def logout():
    user = st.session_state.pop("auth", None)
    if user:
        audit("logout", user["username"])


def change_password(user, old, new):
    problem = password_problem(new)
    if problem:
        return problem
    data = _load()
    if user["role"] == "admin":
        rec = data.get("admin")
    else:
        rec = data["teachers"].get(user["dept"], {}).get(user["username"])
    if not rec or not verify_secret(old, rec):
        return "Current password is incorrect."
    if old == new:
        return "New password must differ from the current one."
    new_rec = hash_secret(new)
    new_rec["created"] = rec.get("created", "")
    if user["role"] == "admin":
        data["admin"] = new_rec
    else:
        data["teachers"][user["dept"]][user["username"]] = new_rec
    write_json(_ACCOUNTS, data)
    st.session_state["auth"]["must_change"] = False
    audit("password_changed", user["username"])
    return None


# ======================================================================
# UI — Shared UI helpers: theme injection, hero banner, section banners, width kwargs.
# ======================================================================
# Streamlit renamed use_container_width -> width="stretch"; support both.
STRETCH = (
    {"width": "stretch"}
    if "width" in inspect.signature(st.button).parameters
    else {"use_container_width": True}
)


def apply_theme():
    # NEON_CSS already contains the cubes; EXTRA_CSS adds v2 widgets.
    st.markdown(NEON_CSS, unsafe_allow_html=True)
    st.markdown(EXTRA_CSS, unsafe_allow_html=True)


def render_hero(height=320):
    """Three.js banner. Uses st.iframe on new Streamlit, components.html on older versions."""
    html = "<style>html,body{margin:0;height:100%;background:transparent;overflow:hidden}</style>" + THREE_HERO
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height)


def banner(title, subtitle=""):
    st.markdown(
        f"""
        <div style="padding:18px 22px;border-radius:20px;margin-bottom:10px;
             background:linear-gradient(120deg,rgba(255,46,151,.35),rgba(123,47,247,.35),rgba(0,229,255,.3));
             border:1px solid rgba(255,255,255,.25);box-shadow:0 14px 40px rgba(123,47,247,.45);
             transform:perspective(900px) rotateX(4deg);">
          <div style="font-family:Orbitron,sans-serif;font-size:1.5rem;font-weight:800;color:#fff;
               text-shadow:0 0 18px #ff2e97;">{title}</div>
          <div style="color:#d6f6ff;margin-top:4px;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---- page names (used for navigation + RBAC) ----
P_HOME = "🏠 Home"
P_TAKE = "📝 Take Assessment"
P_CARD = "🎓 My Report Card"
P_LOGIN = "🔐 Faculty Login"
P_CREATOR = "✍️ Question Creator"
P_EVAL = "👨‍🏫 Evaluation"
P_ANALYTICS = "📊 Analytics"
P_ADMIN = "🛡️ Admin Console"
P_ACCOUNT = "⚙️ Account"

TEACHER_PAGES = {P_CREATOR, P_EVAL, P_ANALYTICS}   # teacher/admin only
ADMIN_PAGES = {P_ADMIN}                             # admin only


def goto(page):
    """Request navigation on the next run (safe to call after the sidebar radio exists)."""
    st.session_state["_goto"] = page


# ======================================================================
# REPORT — Official report-card PDF (ReportLab).
# ======================================================================
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/Nirmala.ttc",                      # Windows: Latin + Bengali/Devanagari
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _register_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("PortalSans", path, subfontIndex=0) if path.endswith(".ttc") else TTFont("PortalSans", path))
                return "PortalSans", True
            except Exception:
                continue
    return "Helvetica", False


def build_report_pdf(sub, dept):
    """Return the report card of a (finalised) submission as PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    font, unicode_ok = _register_font()

    def clean(text):
        text = str(text if text is not None else "")
        if not unicode_ok:
            text = text.encode("latin-1", "replace").decode("latin-1")
        return escape(text)

    navy, violet = colors.HexColor("#1b0a3d"), colors.HexColor("#7b2ff7")
    title = ParagraphStyle("t", fontName=font, fontSize=18, leading=22, textColor=navy, alignment=1)
    sub_t = ParagraphStyle("s", fontName=font, fontSize=11, leading=14, textColor=violet, alignment=1)
    body = ParagraphStyle("b", fontName=font, fontSize=9, leading=12)
    h2 = ParagraphStyle("h", fontName=font, fontSize=11, leading=14, textColor=navy, spaceBefore=8, spaceAfter=4)

    t = totals(sub)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Report Card {sub['submission_id']}")
    story = [
        Paragraph(clean(INSTITUTION_NAME), title),
        Paragraph(f"Department of {clean(dept)}", sub_t),
        Spacer(1, 3 * mm),
        Paragraph("<b>OFFICIAL REPORT CARD</b>", ParagraphStyle("c", parent=sub_t, fontSize=14, textColor=navy)),
        Spacer(1, 5 * mm),
    ]

    info = [
        ["Student Name", clean(sub["student_name"]), "Roll No.", clean(sub["roll_no"])],
        ["Submission ID", clean(sub["submission_id"]), "Report ID", f"RC-{clean(sub['submission_id'])}"],
        ["Submitted", clean(sub["timestamp"]), "Evaluated", clean(sub.get("evaluated_at", "-"))],
        ["Evaluator", clean(sub.get("evaluated_by", "-")), "Department", clean(dept)],
    ]
    it = Table([[Paragraph(f"<b>{a}</b>" if i % 2 == 0 else a, body) for i, a in enumerate(row)] for row in info],
               colWidths=[30 * mm, 55 * mm, 28 * mm, 55 * mm])
    it.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#b9a8e8")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#efe9ff")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#efe9ff")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [it, Paragraph("Marks Statement", h2)]

    rows = [["Q.No", "Question / Topic", "Type", "Max", "Awarded", "Faculty Remark"]]
    for q in sub["paper"]:
        qid = str(q["id"])
        topic = clean(q["question"][:110] + ("…" if len(q["question"]) > 110 else ""))
        if q.get("identifier"):
            topic = f"<b>{clean(q['identifier'])}</b><br/>{topic}"
        awarded = min(float(sub["marks"].get(qid, 0) or 0), float(q["max_marks"]))
        rows.append([
            Paragraph(clean(q["number"]), body), Paragraph(topic, body),
            Paragraph(clean(QUESTION_TYPES.get(q["type"], q["type"]).split(" ")[0]), body),
            f"{q['max_marks']:g}", f"{awarded:g}",
            Paragraph(clean(sub.get("remarks", {}).get(qid, "")), body),
        ])
    rows.append(["", Paragraph("<b>TOTAL</b>", body), "", f"{t['max']:g}", f"{t['obtained']:g}", ""])
    mt = Table(rows, colWidths=[12 * mm, 58 * mm, 25 * mm, 12 * mm, 17 * mm, 46 * mm], repeatRows=1)
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#b9a8e8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f7f3ff")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#efe9ff")),
        ("ALIGN", (3, 0), (4, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [mt, Spacer(1, 5 * mm)]

    res_col = colors.HexColor("#0a8f5a") if t["passed"] else colors.HexColor("#c0143c")
    summ = Table([[
        Paragraph(f"<b>Total</b><br/>{t['obtained']:g} / {t['max']:g}", body),
        Paragraph(f"<b>Percentage</b><br/>{t['percent']:.2f}%", body),
        Paragraph(f"<b>Grade</b><br/>{clean(t['grade'])} ({clean(t['grade_desc'])})", body),
        Paragraph(f"<b>Result</b><br/><font color='{res_col.hexval()}'><b>{'PASS' if t['passed'] else 'FAIL'}</b></font>", body),
    ]], colWidths=[43 * mm] * 4)
    summ.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, violet), ("INNERGRID", (0, 0), (-1, -1), .4, violet),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f3ff")),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summ)

    if sub.get("overall_feedback"):
        story += [Paragraph("Overall Feedback", h2), Paragraph(clean(sub["overall_feedback"]), body)]

    sig = Table([["", ""], ["Evaluator's Signature", "Head of Department"]], colWidths=[85 * mm, 85 * mm], rowHeights=[16 * mm, 6 * mm])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), .6, colors.black), ("LINEABOVE", (1, 1), (1, 1), .6, colors.black),
                             ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story += [Spacer(1, 12 * mm), sig, Spacer(1, 4 * mm),
              Paragraph("<i>This is a computer-generated report card issued after faculty evaluation was finalised.</i>",
                        ParagraphStyle("f", parent=body, fontSize=7, alignment=1, textColor=colors.grey))]
    doc.build(story)
    return buf.getvalue()


# ======================================================================
# THEME — Visual theme: neon CSS, floating 3D cubes and the Three.js hero banner.
# ======================================================================
NEON_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Poppins:wght@300;400;600&display=swap');

:root{
  --c1:#ff2e97; --c2:#7b2ff7; --c3:#00e5ff; --c4:#ffd400; --c5:#00ff9d;
}

/* ---------- Animated gradient backdrop ---------- */
.stApp{
  background: linear-gradient(135deg,#0b0420,#1a0638,#05172e,#2a0845,#031c2e);
  background-size: 400% 400%;
  animation: bgShift 22s ease infinite;
  font-family:'Poppins',sans-serif;
}
@keyframes bgShift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
[data-testid="stHeader"]{background:transparent;}
.block-container{position:relative;z-index:2;padding-top:1.5rem;}

/* ---------- Floating 3D cubes in background ---------- */
.scene3d{position:fixed;inset:0;perspective:900px;z-index:0;pointer-events:none;overflow:hidden;}
.cube{position:absolute;width:60px;height:60px;transform-style:preserve-3d;
      animation:spin 14s linear infinite, floaty 9s ease-in-out infinite;}
.cube div{position:absolute;width:60px;height:60px;border:2px solid;opacity:.55;
          box-shadow:0 0 18px currentColor, inset 0 0 18px currentColor;}
.cube div:nth-child(1){transform:translateZ(30px)}
.cube div:nth-child(2){transform:rotateY(90deg) translateZ(30px)}
.cube div:nth-child(3){transform:rotateY(180deg) translateZ(30px)}
.cube div:nth-child(4){transform:rotateY(-90deg) translateZ(30px)}
.cube div:nth-child(5){transform:rotateX(90deg) translateZ(30px)}
.cube div:nth-child(6){transform:rotateX(-90deg) translateZ(30px)}
.cube.a{left:6%;top:18%;color:var(--c1);animation-duration:12s,8s}
.cube.b{left:88%;top:12%;color:var(--c3);animation-duration:17s,10s;transform:scale(1.5)}
.cube.c{left:80%;top:68%;color:var(--c4);animation-duration:15s,7s}
.cube.d{left:10%;top:72%;color:var(--c5);animation-duration:20s,11s;transform:scale(1.8)}
.cube.e{left:50%;top:88%;color:var(--c2);animation-duration:13s,9s}
.cube div{border-color:currentColor;}
@keyframes spin{from{transform:rotateX(0) rotateY(0) rotateZ(0)}to{transform:rotateX(360deg) rotateY(720deg) rotateZ(360deg)}}
@keyframes floaty{0%,100%{margin-top:0}50%{margin-top:-50px}}

/* ---------- Typography ---------- */
h1,h2,h3,h4,h5{font-family:'Orbitron',sans-serif !important;letter-spacing:.5px;}
h1{
  background:linear-gradient(90deg,var(--c1),var(--c4),var(--c3),var(--c1));
  background-size:300% auto;-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;animation:shine 6s linear infinite;
  text-shadow:0 0 30px rgba(255,46,151,.35);
}
@keyframes shine{to{background-position:300% center}}
h2,h3{color:var(--c3) !important;text-shadow:0 0 14px rgba(0,229,255,.55);}
h4{color:#ffb3e1 !important;text-shadow:0 0 10px rgba(255,46,151,.5);}
p,li,label,span,.stMarkdown,[data-testid="stWidgetLabel"] p,[data-testid="stCaptionContainer"]{color:#e9e4ff;}
hr{border:none !important;height:2px !important;
   background:linear-gradient(90deg,transparent,var(--c1),var(--c3),var(--c4),transparent) !important;
   box-shadow:0 0 12px var(--c1);}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"]{gap:10px;background:rgba(255,255,255,.04);padding:8px;border-radius:16px;
  border:1px solid rgba(255,255,255,.12);backdrop-filter:blur(10px);}
.stTabs [data-baseweb="tab"]{border-radius:12px;padding:10px 18px;color:#cfc4ff;
  transition:all .3s;transform-style:preserve-3d;}
.stTabs [data-baseweb="tab"]:hover{transform:translateY(-4px) rotateX(12deg);color:#fff;
  background:rgba(123,47,247,.35);box-shadow:0 8px 20px rgba(123,47,247,.5);}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,var(--c1),var(--c2)) !important;
  color:#fff !important;box-shadow:0 0 22px rgba(255,46,151,.7);}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none;}

/* ---------- Inputs (glass) ---------- */
/* wrappers must be dark too, otherwise white text sits on a white box */
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"],
.stTextInput>div>div,.stTextArea>div>div,.stNumberInput>div>div{
  background:#1b0a3d !important;border-radius:12px !important;}
.stTextInput input,.stTextArea textarea,.stNumberInput input,
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea,[data-baseweb="base-input"] input,
[data-baseweb="select"] *{
  background:#1b0a3d !important;color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;
  caret-color:#00e5ff !important;}
.stTextInput input::placeholder,.stTextArea textarea::placeholder,.stNumberInput input::placeholder{
  color:#9d8fd1 !important;-webkit-text-fill-color:#9d8fd1 !important;opacity:1 !important;}
.stNumberInput button{background:#2a1260 !important;color:#fff !important;}
.stTextInput input,.stTextArea textarea,.stNumberInput input,[data-baseweb="select"]>div{
  background:#1b0a3d !important;color:#fff !important;
  border:1px solid rgba(0,229,255,.35) !important;border-radius:12px !important;
  backdrop-filter:blur(8px);transition:all .3s;}
.stTextInput input:focus,.stTextArea textarea:focus,.stNumberInput input:focus{
  border-color:var(--c1) !important;box-shadow:0 0 0 2px rgba(255,46,151,.45),0 0 25px rgba(255,46,151,.45) !important;
  transform:translateY(-2px);}
[data-baseweb="popover"] ul{background:#1a0638 !important;}
[data-baseweb="popover"] li{color:#fff !important;}
[data-testid="stFileUploader"] section{background:rgba(255,255,255,.05);border:2px dashed var(--c3);
  border-radius:16px;transition:all .3s;}
[data-testid="stFileUploader"] section:hover{border-color:var(--c1);box-shadow:0 0 25px rgba(255,46,151,.5);
  transform:perspective(600px) rotateX(3deg) scale(1.01);}
[data-testid="stFileUploader"] section *{color:#e9e4ff !important;}
/* Upload / Browse button inside the uploader */
[data-testid="stFileUploader"] button,
[data-testid="stFileUploaderDropzone"] button{
  background:linear-gradient(135deg,#ff2e97,#7b2ff7) !important;
  border:none !important;border-radius:12px !important;
  box-shadow:0 5px 0 #4a1a8f,0 8px 20px rgba(123,47,247,.5) !important;transition:all .25s;}
[data-testid="stFileUploader"] button *,
[data-testid="stFileUploaderDropzone"] button *{color:#ffffff !important;fill:#ffffff !important;
  -webkit-text-fill-color:#ffffff !important;font-weight:600;}
[data-testid="stFileUploader"] button:hover,
[data-testid="stFileUploaderDropzone"] button:hover{
  transform:translateY(-3px);box-shadow:0 8px 0 #4a1a8f,0 14px 26px rgba(255,46,151,.6) !important;}
/* uploaded file name rows + delete (x) button */
[data-testid="stFileUploaderFile"],[data-testid="stFileChip"]{
  background:rgba(27,10,61,.9) !important;border-radius:12px;border:1px solid rgba(0,229,255,.4);}
[data-testid="stFileUploaderFile"] *,[data-testid="stFileChip"] *{color:#ffffff !important;}
[data-testid="stFileUploaderDeleteBtn"] button{background:transparent !important;box-shadow:none !important;}

/* ---------- Radio options as 3D cards ---------- */
.stRadio [role="radiogroup"] label{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.15);
  border-radius:14px;padding:10px 16px;margin-bottom:8px;transition:all .25s;transform-style:preserve-3d;}
.stRadio [role="radiogroup"] label:hover{transform:perspective(600px) translateZ(14px) rotateY(-4deg) translateX(6px);
  background:linear-gradient(90deg,rgba(255,46,151,.3),rgba(0,229,255,.25));
  box-shadow:0 10px 25px rgba(0,229,255,.35);border-color:var(--c3);}

/* ---------- Buttons ---------- */
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{
  background:linear-gradient(135deg,var(--c1),var(--c2),var(--c3));background-size:250% 250%;
  color:#fff !important;font-weight:600;border:none;border-radius:14px;padding:.7rem 1rem;
  box-shadow:0 8px 0 #4a1a8f,0 14px 30px rgba(123,47,247,.55);
  transition:all .25s;animation:btnflow 5s ease infinite;}
@keyframes btnflow{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.stButton>button:hover,.stFormSubmitButton>button:hover,.stDownloadButton>button:hover{
  transform:translateY(-4px) scale(1.02);box-shadow:0 12px 0 #4a1a8f,0 22px 40px rgba(255,46,151,.6);color:#fff !important;}
.stButton>button:active,.stFormSubmitButton>button:active{transform:translateY(6px);box-shadow:0 2px 0 #4a1a8f,0 4px 12px rgba(0,0,0,.5);}
.stButton>button[kind="primary"]{background:linear-gradient(135deg,var(--c4),var(--c1),var(--c2));
  box-shadow:0 8px 0 #8a1450,0 14px 34px rgba(255,46,151,.65);animation:btnflow 4s ease infinite, pulse 2.2s infinite;}
@keyframes pulse{0%,100%{filter:brightness(1)}50%{filter:brightness(1.25)}}

/* ---------- Metrics as tilted 3D cards ---------- */
[data-testid="stMetric"]{background:linear-gradient(145deg,rgba(123,47,247,.35),rgba(0,229,255,.18));
  border:1px solid rgba(255,255,255,.25);border-radius:18px;padding:16px 18px;
  transform:perspective(800px) rotateX(6deg) rotateY(-6deg);transition:all .4s;
  box-shadow:0 18px 35px rgba(0,0,0,.5),0 0 25px rgba(123,47,247,.45);}
[data-testid="stMetric"]:hover{transform:perspective(800px) rotateX(0) rotateY(0) translateY(-8px) scale(1.04);
  box-shadow:0 26px 45px rgba(0,0,0,.55),0 0 40px rgba(0,229,255,.7);}
[data-testid="stMetricValue"]{color:var(--c4) !important;text-shadow:0 0 14px rgba(255,212,0,.7);
  font-family:'Orbitron',sans-serif;}
[data-testid="stMetricLabel"] *{color:#bfe9ff !important;}

/* ---------- Alerts ---------- */
[data-testid="stAlert"]{border-radius:16px;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.2);
  animation:slideIn .6s ease both;}
@keyframes slideIn{from{opacity:0;transform:translateX(-40px) rotateY(25deg)}to{opacity:1;transform:none}}
[data-testid="stAlert"] *{color:#fff !important;}
/* dark tinted alert boxes so white text is readable */
[data-testid="stAlert"],[data-testid="stAlert"]>div,[data-testid="stAlert"] [data-baseweb="notification"]{
  background:rgba(27,10,61,.92) !important;border:1px solid rgba(0,229,255,.55) !important;
  border-left:6px solid #00e5ff !important;box-shadow:0 0 20px rgba(0,229,255,.3);}
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]),
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"])>div{
  background:rgba(0,70,45,.9) !important;border-color:#00ff9d !important;box-shadow:0 0 20px rgba(0,255,157,.35);}
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]),
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"])>div{
  background:rgba(90,65,0,.9) !important;border-color:#ffd400 !important;box-shadow:0 0 20px rgba(255,212,0,.35);}
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]),
[data-testid="stAlert"]:has([data-testid="stAlertContentError"])>div{
  background:rgba(95,10,45,.92) !important;border-color:#ff2e97 !important;box-shadow:0 0 20px rgba(255,46,151,.4);}
[data-testid="stAlert"] ::selection{background:#ff2e97;color:#fff;}

/* ---------- Forms & expanders ---------- */
[data-testid="stForm"]{background:rgba(255,255,255,.04);border:1px solid rgba(255,46,151,.4);
  border-radius:20px;box-shadow:0 0 30px rgba(255,46,151,.25);}
</style>

<div class="scene3d">
  <div class="cube a"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube b"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube c"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube d"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube e"><div></div><div></div><div></div><div></div><div></div><div></div></div>
</div>
"""

EXTRA_CSS = """
<style>
/* ---------- v2 additions: sidebar, expanders, tables, code, progress ---------- */
[data-testid="stSidebar"]{background:linear-gradient(180deg,#14072e,#0a1030 60%,#1a0638);
  border-right:1px solid rgba(0,229,255,.35);box-shadow:0 0 30px rgba(123,47,247,.4);}
[data-testid="stSidebar"] *{color:#e9e4ff;}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] label{padding:8px 12px;margin-bottom:6px;}
[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover{transform:perspective(600px) translateZ(8px) translateX(5px);}
[data-testid="stExpander"]{background:rgba(255,255,255,.05);border:1px solid rgba(0,229,255,.3) !important;
  border-radius:16px;overflow:hidden;}
[data-testid="stExpander"] summary,[data-testid="stExpander"] summary *{color:#fff !important;}
pre,code{background:#120628 !important;color:#7dffcf !important;border-radius:10px;}
[data-testid="stCode"] pre{border:1px solid rgba(0,255,157,.35);}
[data-testid="stProgress"]>div>div{background:rgba(255,255,255,.12) !important;}
[data-testid="stProgress"] div[role="progressbar"]>div{background:linear-gradient(90deg,#ff2e97,#ffd400,#00ff9d) !important;}
[data-testid="stDataFrame"]{border:1px solid rgba(0,229,255,.4);border-radius:14px;overflow:hidden;
  box-shadow:0 0 22px rgba(0,229,255,.25);}
[data-testid="stCheckbox"] label span{color:#e9e4ff !important;}
.stSelectbox [data-baseweb="select"] *{color:#fff !important;}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:rgba(0,229,255,.35) !important;border-radius:16px;}
.pin-card{margin:14px 0;padding:22px;border-radius:20px;text-align:center;
  background:linear-gradient(135deg,rgba(255,212,0,.25),rgba(255,46,151,.3),rgba(123,47,247,.35));
  border:2px solid #ffd400;box-shadow:0 0 40px rgba(255,212,0,.5);
  transform:perspective(900px) rotateX(5deg);}
.pin-card .pin{font-family:Orbitron,sans-serif;font-size:2.6rem;letter-spacing:12px;color:#fff;
  text-shadow:0 0 22px #ffd400;}
.dept-card{padding:26px;border-radius:22px;margin:10px 0 18px;
  background:linear-gradient(135deg,rgba(255,46,151,.28),rgba(123,47,247,.32),rgba(0,229,255,.25));
  border:1px solid rgba(255,255,255,.3);box-shadow:0 18px 45px rgba(123,47,247,.5);
  transform:perspective(1000px) rotateX(3deg);}
.role-chip{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.8rem;font-weight:600;
  background:linear-gradient(90deg,#00ff9d,#00e5ff);color:#06122a !important;}
.role-chip.student{background:linear-gradient(90deg,#ffd400,#ff2e97);}
</style>
"""

THREE_HERO = """
<div id="wrap" style="width:100%;height:100%;position:relative;font-family:sans-serif;">
  <canvas id="c" style="width:100%;height:100%;display:block;"></canvas>
  <div style="position:absolute;left:0;right:0;bottom:8px;text-align:center;color:#fff;
       font-size:13px;letter-spacing:4px;text-shadow:0 0 12px #00e5ff;">
       MOVE YOUR MOUSE · EXPLORE THE BRIDGE
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const canvas=document.getElementById('c');
const renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(55,2,0.1,100);camera.position.z=7;

const knot=new THREE.Mesh(new THREE.TorusKnotGeometry(1.3,0.4,180,24),
  new THREE.MeshStandardMaterial({color:0xff2e97,metalness:.7,roughness:.2,emissive:0x330022}));
scene.add(knot);
const wire=new THREE.Mesh(new THREE.IcosahedronGeometry(2.6,1),
  new THREE.MeshBasicMaterial({color:0x00e5ff,wireframe:true,transparent:true,opacity:.35}));
scene.add(wire);
const ring=new THREE.Mesh(new THREE.TorusGeometry(3.4,0.03,16,120),
  new THREE.MeshBasicMaterial({color:0xffd400}));
ring.rotation.x=Math.PI/2.4;scene.add(ring);
const ring2=ring.clone();ring2.material=new THREE.MeshBasicMaterial({color:0x7b2ff7});
ring2.rotation.x=-Math.PI/3;ring2.rotation.y=.6;scene.add(ring2);

// orbiting colourful spheres
const orbs=[];const cols=[0x00ff9d,0xffd400,0x00e5ff,0xff2e97,0x7b2ff7];
cols.forEach((c,i)=>{
  const m=new THREE.Mesh(new THREE.SphereGeometry(.22,24,24),
    new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:.6}));
  m.userData={r:3+i*.25,s:.6+i*.15,o:i*1.3};scene.add(m);orbs.push(m);
});

// particles
const N=900,pos=new Float32Array(N*3),col=new Float32Array(N*3);
for(let i=0;i<N;i++){
  pos[i*3]=(Math.random()-.5)*26;pos[i*3+1]=(Math.random()-.5)*14;pos[i*3+2]=(Math.random()-.5)*14;
  const k=new THREE.Color().setHSL(Math.random(),1,.6);col.set([k.r,k.g,k.b],i*3);
}
const g=new THREE.BufferGeometry();
g.setAttribute('position',new THREE.BufferAttribute(pos,3));
g.setAttribute('color',new THREE.BufferAttribute(col,3));
const pts=new THREE.Points(g,new THREE.PointsMaterial({size:.07,vertexColors:true}));
scene.add(pts);

scene.add(new THREE.AmbientLight(0xffffff,.5));
const l1=new THREE.PointLight(0x00e5ff,2,30);l1.position.set(5,4,5);scene.add(l1);
const l2=new THREE.PointLight(0xff2e97,2,30);l2.position.set(-5,-3,4);scene.add(l2);

let mx=0,my=0;
window.addEventListener('mousemove',e=>{mx=(e.clientX/innerWidth-.5)*2;my=(e.clientY/innerHeight-.5)*2;});
function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);
  camera.aspect=w/h;camera.updateProjectionMatrix();}
window.addEventListener('resize',resize);resize();

const clock=new THREE.Clock();
(function loop(){
  const t=clock.getElapsedTime();
  knot.rotation.x=t*.5+my*.6;knot.rotation.y=t*.7+mx*.8;
  const s=1+Math.sin(t*2)*.05;knot.scale.set(s,s,s);
  wire.rotation.y=-t*.25;wire.rotation.x=t*.15;
  ring.rotation.z=t*.6;ring2.rotation.z=-t*.4;
  orbs.forEach(o=>{const d=o.userData;o.position.set(Math.cos(t*d.s+d.o)*d.r,Math.sin(t*d.s*1.3+d.o)*1.6,Math.sin(t*d.s+d.o)*d.r);});
  pts.rotation.y=t*.03;
  camera.position.x+=(mx*1.5-camera.position.x)*.05;
  camera.position.y+=(-my*1-camera.position.y)*.05;camera.lookAt(0,0,0);
  l1.color.setHSL((t*.05)%1,1,.6);
  renderer.render(scene,camera);requestAnimationFrame(loop);
})();
</script>
"""


# ======================================================================
# VIEWS/HOME — Landing page: department selection.
# ======================================================================
def _enter():
    choice = st.session_state.get("dept_choice")
    if choice != st.session_state.get("dept"):
        for k in ("stu_step", "stu_draft", "stu_primed", "stu_result"):
            st.session_state.pop(k, None)
    st.session_state["dept"] = choice
    goto(P_TAKE)


def render_home():
    render_hero(320)
    st.title("🎓 Departmental Assessment & Grading Portal")
    st.markdown(f"**{INSTITUTION_NAME}**")
    st.markdown("---")

    st.markdown("<div class='dept-card'><h3 style='margin:0'>🏛️ Select Your Department</h3>"
                "<div style='margin-top:6px'>Pick the department whose assessments and resources you need.</div></div>",
                unsafe_allow_html=True)
    current = st.session_state.get("dept")
    idx = DEPARTMENTS.index(current) if current in DEPARTMENTS else None
    st.selectbox(
        "Choose the academic department whose resources you want to access",
        DEPARTMENTS, index=idx, placeholder="Select a department…", key="dept_choice",
    )

    chosen = st.session_state.get("dept_choice")
    st.button("🚀 Enter Student Portal", type="primary", disabled=not chosen,
              on_click=_enter, **STRETCH)

    c1, c2, c3 = st.columns(3)
    c1.markdown("##### 🎓 Students\nTake assessments, review and edit answers, then download your report card.")
    c2.markdown("##### 👨‍🏫 Faculty\nSign in from the sidebar to create questions, evaluate and view analytics.")
    c3.markdown("##### 🛡️ Administrators\nManage departmental faculty credentials and monitor all departments.")
    if current_user() is None:
        st.info("🔐 Faculty and administrators: open **Faculty Login** from the sidebar. "
                "Teacher pages are never shown to students.")


# ======================================================================
# VIEWS/LOGIN — Faculty / administrator sign-in.
# ======================================================================
def render_login(dept):
    banner("🔐 Faculty Sign-In", "Department-scoped credentials issued by the administrator")
    if dept:
        st.markdown(f"Signing in to: **{dept}**")
    else:
        st.warning("Select your department on the **Home** page first (administrators may sign in directly).")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        go = st.form_submit_button("🔓 Sign In", **STRETCH)
    if go:
        ok, msg = login(username, password, dept)
        if ok:
            user = st.session_state["auth"]
            if user["must_change"]:
                st.session_state["flash"] = "🔑 Please set a new password to continue."
                goto(P_ACCOUNT)
            else:
                goto(P_ADMIN if user["role"] == "admin" else P_CREATOR)
            st.rerun()
        else:
            st.error(msg)
    st.caption("After 5 failed attempts the account is locked for 5 minutes. Sessions expire after 30 idle minutes.")


# ======================================================================
# VIEWS/ACCOUNT — Password change + sign-out for the logged-in teacher/admin.
# ======================================================================
def render_account(user):
    banner("⚙️ My Account", f"Signed in as **{user['username']}** · role: {user['role']}")
    if user.get("must_change"):
        st.warning("You are using a temporary password. Set a new one to unlock the dashboards.")
    with st.form("pw_form", clear_on_submit=True):
        old = st.text_input("Current password", type="password")
        new = st.text_input(f"New password (min {MIN_PASSWORD_LEN} chars, letters + digits)", type="password")
        new2 = st.text_input("Repeat new password", type="password")
        go = st.form_submit_button("🔑 Change Password", **STRETCH)
    if go:
        if new != new2:
            st.error("The new passwords do not match.")
        else:
            err = change_password(user, old, new)
            if err:
                st.error(err)
            else:
                st.success("Password updated.")
                st.rerun()
    st.markdown("---")
    if st.button("🚪 Sign Out", **STRETCH):
        logout()
        goto(P_HOME)
        st.rerun()


# ======================================================================
# VIEWS/ADMIN — Administrator console: teacher credentials per department, audit log.
# ======================================================================
def render_admin(user):
    banner("🛡️ Administrator Console", "Manage departmental faculty credentials")
    t_accounts, t_audit = st.tabs(["👥 Faculty Accounts", "🧾 Audit Log"])

    with t_accounts:
        dept = st.selectbox("Department", DEPARTMENTS, key="adm_dept")
        teachers = list_teachers(dept)
        st.markdown(f"**Faculty accounts in {dept}:** " + (", ".join(f"`{t}`" for t in teachers) or "none yet"))

        st.markdown("#### ➕ Create faculty account")
        with st.form(f"add_t_{dept}", clear_on_submit=True):
            u = st.text_input("Username")
            p = st.text_input("Temporary password", type="password",
                              help="The teacher must change it at first login.")
            if st.form_submit_button("Create account", **STRETCH):
                err = add_teacher(dept, u, p)
                st.error(err) if err else st.success(f"Created `{u.strip().lower()}`.")
                if not err:
                    st.rerun()

        if teachers:
            st.markdown("#### 🔄 Reset password / remove")
            who = st.selectbox("Account", teachers, key=f"adm_who_{dept}")
            with st.form(f"reset_{dept}_{who}", clear_on_submit=True):
                newp = st.text_input("New temporary password", type="password")
                c1, c2 = st.columns(2)
                reset = c1.form_submit_button("Reset password", **STRETCH)
                remove = c2.form_submit_button("🗑️ Delete account", **STRETCH)
            if reset:
                err = reset_teacher_password(dept, who, newp)
                st.error(err) if err else st.success("Password reset; teacher must change it at next login.")
            if remove:
                delete_teacher(dept, who)
                st.rerun()

    with t_audit:
        st.caption("Most recent security events first (logins, failures, lockouts, password changes, finalised evaluations).")
        lines = read_audit(80)
        st.code("\n".join(lines) if lines else "No events yet.", language="text")


# ======================================================================
# VIEWS/STUDENT — Student side: answer -> review/edit -> final submit, and report-card retrieval by ID + PIN.
# ======================================================================
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
SLOTS = {"doc": "w_up_{qid}", "code_file": "w_pyup_{qid}"}


# ------------------------------------------------------------------ state helpers
def _init():
    ss.setdefault("stu_step", "answer")          # answer | review | done
    ss.setdefault("stu_draft", {"name": "", "roll": "", "answers": {}})
    ss.setdefault("stu_primed", False)


def _reset():
    for k in list(ss.keys()):
        if k.startswith("w_") or k in ("stu_step", "stu_draft", "stu_primed", "stu_result"):
            del ss[k]
    _init()


def _slots_for(q):
    return {"mcq": [], "short": ["doc"], "long": ["doc"], "code": ["code_file", "doc"]}[q["type"]]


def _prime(questions):
    """Copy the saved draft back into widget state when (re)entering the answer step."""
    if ss["stu_primed"]:
        return
    d = ss["stu_draft"]
    ss["w_name"], ss["w_roll"] = d["name"], d["roll"]
    for q in questions:
        qid, a = q["id"], d["answers"].get(str(q["id"]), {})
        if q["type"] == "mcq":
            if a.get("choice") in q["options"]:
                ss[f"w_choice_{qid}"] = a["choice"]
            else:
                ss.pop(f"w_choice_{qid}", None)
        elif q["type"] == "code":
            ss[f"w_code_{qid}"] = a.get("code", "")
        else:
            ss[f"w_text_{qid}"] = a.get("text", "")
        for slot in SLOTS:
            ss[f"w_rm_{qid}_{slot}"] = False
    ss["stu_primed"] = True


def _collect(questions):
    """Read every widget into the draft. Returns a list of problems."""
    d, problems = ss["stu_draft"], []
    d["name"], d["roll"] = ss.get("w_name", "").strip(), ss.get("w_roll", "").strip()
    answers = {}
    for q in questions:
        qid = q["id"]
        prev = d["answers"].get(str(qid), {})
        a = {"choice": None, "text": "", "code": "", "files": {}}
        if q["type"] == "mcq":
            a["choice"] = ss.get(f"w_choice_{qid}")
        elif q["type"] == "code":
            a["code"] = ss.get(f"w_code_{qid}", "")
        else:
            a["text"] = ss.get(f"w_text_{qid}", "")
        for slot in _slots_for(q):
            up = ss.get(SLOTS[slot].format(qid=qid))
            if up is not None:
                if up.size > MAX_BYTES:
                    problems.append(f"Q{q['number']}: '{up.name}' is larger than {MAX_UPLOAD_MB} MB and was ignored.")
                else:
                    a["files"][slot] = {"name": up.name, "bytes": up.getvalue()}
            elif slot in prev.get("files", {}) and not ss.get(f"w_rm_{qid}_{slot}"):
                a["files"][slot] = prev["files"][slot]
        answers[str(qid)] = a
    d["answers"] = answers
    return problems


def _is_answered(q, a):
    if q["type"] == "mcq":
        return bool(a.get("choice"))
    return bool(a.get("text", "").strip() or a.get("code", "").strip() or a.get("files"))


# ------------------------------------------------------------------ step 1: answer
def _question_header(q):
    tag = f" · _{q['identifier']}_" if q.get("identifier") else ""
    st.markdown(f"#### Q{q['number']}. {q['question']}")
    st.caption(f"{q['max_marks']:g} mark(s) · {QUESTION_TYPES.get(q['type'], q['type'])}{tag}")


def _file_slot(q, slot, label, types):
    qid = q["id"]
    existing = ss["stu_draft"]["answers"].get(str(qid), {}).get("files", {}).get(slot)
    if existing:
        c1, c2 = st.columns([3, 1])
        c1.caption(f"📎 Attached: **{existing['name']}** ({len(existing['bytes']) / 1024:.1f} KB) — upload below to replace")
        c2.checkbox("Remove", key=f"w_rm_{qid}_{slot}")
    st.file_uploader(label, type=types, key=SLOTS[slot].format(qid=qid))


def _render_answer(questions):
    _prime(questions)
    banner("📝 Take Assessment", f"Department of {ss['dept']} — answer, review, modify, then submit")
    c1, c2 = st.columns(2)
    c1.text_input("Student Name", placeholder="e.g. Rahul Sharma", key="w_name")
    c2.text_input("Roll Number", placeholder="e.g. 102", key="w_roll")
    st.info("💡 Nothing is final yet. After answering you will get a **review screen** where you can still "
            "edit answers and replace uploaded files before the final submission.")
    st.markdown("---")

    for q in questions:
        qid = q["id"]
        _question_header(q)
        if q["type"] == "mcq":
            st.radio("Choose", q["options"], index=None, key=f"w_choice_{qid}", label_visibility="collapsed")
        elif q["type"] == "short":
            st.text_input("Answer", placeholder="Type a concise answer…", key=f"w_text_{qid}", label_visibility="collapsed")
            _file_slot(q, "doc", "📄 Upload handwritten answer (PDF / PNG / JPG) — optional", DOC_EXTS)
        elif q["type"] == "long":
            st.text_area("Answer", placeholder="Write the detailed answer / derivation…", height=180,
                         key=f"w_text_{qid}", label_visibility="collapsed")
            _file_slot(q, "doc", "📄 Upload handwritten answer script (PDF / PNG / JPG) — optional", DOC_EXTS)
        else:  # code
            st.text_area("Code", placeholder="# Paste or type your Python code here (it is stored, never executed)",
                         height=220, key=f"w_code_{qid}", label_visibility="collapsed")
            _file_slot(q, "code_file", "🐍 Upload code file (.py / .txt editor output)", CODE_EXTS)
            _file_slot(q, "doc", "🖼️ Upload output screenshot / report (PDF / PNG / JPG) — optional", DOC_EXTS)
        st.markdown("<br>", unsafe_allow_html=True)

    if st.button("👀 Review My Answers →", type="primary", **STRETCH):
        problems = _collect(questions)
        for p in problems:
            st.warning(p)
        d = ss["stu_draft"]
        if not d["name"] or not d["roll"]:
            st.error("Please enter both your name and roll number.")
        else:
            ss["stu_step"], ss["stu_primed"] = "review", False
            st.rerun()


# ------------------------------------------------------------------ step 2: review
def _preview_files(a):
    for slot, f in a.get("files", {}).items():
        kind = "Code file" if slot == "code_file" else "Document / image"
        st.markdown(f"📎 **{kind}:** `{f['name']}` ({len(f['bytes']) / 1024:.1f} KB)")
        name = f["name"].lower()
        if name.endswith((".png", ".jpg", ".jpeg")):
            st.image(f["bytes"], width=380)
        elif name.endswith((".py", ".txt")):
            st.code(f["bytes"].decode("utf-8", errors="replace")[:5000], language="python")


def _render_review(store, questions):
    d = ss["stu_draft"]
    banner("🔍 Review Before Final Submission", "Check everything. You can still go back and change any answer.")
    st.markdown(f"**Name:** {d['name']}  ·  **Roll No.:** {d['roll']}  ·  **Department:** {store.dept}")
    st.markdown("---")
    missing = []
    for q in questions:
        a = d["answers"].get(str(q["id"]), {})
        _question_header(q)
        if not _is_answered(q, a):
            missing.append(q["number"])
            st.error("⚠️ Not answered")
        elif q["type"] == "mcq":
            st.success(f"Selected: **{a['choice']}**")
        else:
            if a.get("text", "").strip():
                st.info(a["text"])
            if a.get("code", "").strip():
                st.code(a["code"], language="python")
            _preview_files(a)
        st.markdown("<br>", unsafe_allow_html=True)

    if missing:
        st.warning("Unanswered question(s): " + ", ".join(f"Q{m}" for m in missing) + ". Go back and answer them to submit.")
    confirm = st.checkbox("✅ I confirm these answers are my own work and I want to submit them.", key="w_confirm")

    c1, c2 = st.columns(2)
    if c1.button("✏️ Edit My Answers", **STRETCH):
        ss["stu_step"], ss["stu_primed"] = "answer", False
        st.rerun()
    if c2.button("🚀 Final Submit", type="primary", disabled=bool(missing) or not confirm, **STRETCH):
        _final_submit(store, questions)


def _final_submit(store, questions):
    d = ss["stu_draft"]
    if any(s["roll_no"].strip().lower() == d["roll"].lower() for s in store.submissions()):
        st.error("A submission already exists for this roll number. Please contact your faculty if this is a mistake.")
        return
    pin = f"{secrets.randbelow(10 ** 6):06d}"
    paper = [{k: q[k] for k in ("id", "number", "identifier", "type", "question", "options", "answer", "max_marks")}
             for q in questions]
    marks, answers = {}, {}
    for q in questions:
        a = d["answers"][str(q["id"])]
        answers[str(q["id"])] = {"choice": a["choice"], "text": a["text"], "code": a["code"], "files": {}}
        if q["type"] == "mcq":
            marks[str(q["id"])] = q["max_marks"] if a["choice"] == q["answer"] else 0.0
    sid = store.add_submission({
        "department": store.dept, "student_name": d["name"], "roll_no": d["roll"], "timestamp": now_str(),
        "pin": hash_secret(pin, iterations=200_000), "paper": paper, "answers": answers,
        "marks": marks, "remarks": {}, "overall_feedback": "", "status": "submitted",
    })
    for q in questions:  # persist uploads only now, under sanitised unique names
        for slot, f in d["answers"][str(q["id"])]["files"].items():
            rel = store.save_upload(sid, q["id"], slot, f["name"], f["bytes"])
            answers[str(q["id"])]["files"][slot] = {"name": f["name"], "path": rel}
    store.update_submission(sid, {"answers": answers})
    mcq_total = sum(q["max_marks"] for q in questions if q["type"] == "mcq")
    ss["stu_result"] = {"id": sid, "pin": pin, "name": d["name"], "mcq_got": sum(marks.values()),
                        "mcq_total": mcq_total, "celebrated": False}
    ss["stu_step"] = "done"
    ss["stu_primed"] = False
    st.rerun()


# ------------------------------------------------------------------ step 3: done
def _render_done():
    r = ss["stu_result"]
    st.success(f"🎉 Assessment submitted successfully, {r['name']}!")
    if not r["celebrated"]:
        st.balloons()
        r["celebrated"] = True
    st.markdown(f"### Submission ID: `{r['id']}`")
    st.markdown(f"<div class='pin-card'>YOUR PRIVATE ACCESS PIN<div class='pin'>{r['pin']}</div>"
                f"<div>Shown only once — you need <b>Submission ID + PIN</b> to download your report card.</div></div>",
                unsafe_allow_html=True)
    if r["mcq_total"]:
        c1, c2 = st.columns(2)
        c1.metric("MCQ marks (auto-graded)", f"{r['mcq_got']:g} / {r['mcq_total']:g}")
        c2.metric("Other answers", "Awaiting faculty evaluation ⏳")
    st.download_button("📥 Download Submission Receipt",
                       f"Submission ID: {r['id']}\nAccess PIN: {r['pin']}\nStudent: {r['name']}\n"
                       f"Keep this safe. Use both on the 'My Report Card' page once evaluation is finished.\n",
                       file_name=f"receipt_{r['id']}.txt", **STRETCH)
    if st.button("🔄 Start a New Assessment", **STRETCH):
        _reset()
        st.rerun()


# ------------------------------------------------------------------ entry points
def render_assessment(store):
    _init()
    if ss["stu_step"] == "done":
        _render_done()
        return
    questions = store.questions()
    if not questions:
        banner("📝 Take Assessment", f"Department of {store.dept}")
        st.warning("No questions have been published for this department yet. Please check back later.")
        return
    if ss["stu_step"] == "review":
        _render_review(store, questions)
    else:
        _render_answer(questions)


def render_report_card(store):
    banner("🎓 My Report Card", "Enter the Submission ID and PIN you received after submitting")
    with st.form("card_lookup"):
        sid = st.text_input("Submission ID", placeholder=f"e.g. {store.slug[:3].upper()}-0001").strip().upper()
        pin = st.text_input("Access PIN", type="password", max_chars=6)
        go = st.form_submit_button("🔎 Find My Report Card", **STRETCH)
    if go:
        key = f"pin:{store.slug}:{sid}"
        wait = lock_remaining(key)
        sub = store.get_submission(sid) if sid else None
        if wait:
            st.error(f"Too many wrong PINs. Try again in {wait // 60 + 1} minute(s).")
        elif not sub or not verify_secret(pin, sub["pin"]):
            register_failure(key if sub else f"pin:{store.slug}:unknown")
            st.error("Submission ID or PIN is incorrect.")
        else:
            clear_failures(key)
            ss["card_sid"] = sid
    sid = ss.get("card_sid")
    sub = store.get_submission(sid) if sid else None
    if sub:
        if sub["status"] != "finalized":
            st.info("⏳ Your answers are received, but the faculty has not finalised the evaluation yet.")
        else:
            t = totals(sub)
            st.success(f"Report card ready for **{sub['student_name']}** (Roll {sub['roll_no']})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Marks", f"{t['obtained']:g} / {t['max']:g}")
            c2.metric("Percentage", f"{t['percent']:.1f}%")
            c3.metric("Grade", t["grade"])
            c4.metric("Result", "PASS ✅" if t["passed"] else "FAIL ❌")
            try:
                rp = store.report_path(sid)
                data = rp.read_bytes() if rp.exists() else build_report_pdf(sub, store.dept)
                st.download_button("📄 Download Official Report Card (PDF)", data,
                                   file_name=f"ReportCard_{sid}.pdf", mime="application/pdf", **STRETCH)
            except ImportError:
                st.error("PDF support (reportlab) is not installed on the server.")


# ======================================================================
# VIEWS/CREATOR — Teacher question creator: numbering, identifiers, weightage, manager and OCR importer.
# ======================================================================
def _flash():
    if "form_success" in ss:
        st.success(ss.pop("form_success"))


def _add_section(store):
    st.markdown("#### ➕ Add New Question")
    ver = ss.setdefault("new_q_ver", 0)
    k = lambda name: f"{name}_{ver}"

    type_label = st.selectbox("Question Type", list(QUESTION_TYPES.values()), key=k("ntype"))
    qtype = next(code for code, lbl in QUESTION_TYPES.items() if lbl == type_label)

    c1, c2, c3 = st.columns([1, 2, 1])
    number = c1.text_input("Question No.", value=store.free_number(), key=k("nnum"),
                           help="Printed on the paper and report card, e.g. 1, 2a, Q3")
    identifier = c2.text_input("Identifier / Topic tag (optional)", placeholder="e.g. Unit 2 – Kinematics · CO3", key=k("nid"))
    marks = c3.number_input("Max Marks", min_value=0.5, max_value=100.0, step=0.5,
                            value=DEFAULT_MARKS[qtype], key=k(f"nmarks_{qtype}"))

    prompt = st.text_area("Question Prompt", placeholder="Enter question text…", key=k("nprompt"))
    options, answer = [], ""
    if qtype == "mcq":
        a, b = st.columns(2)
        raw = [a.text_input("Option A", key=k("oa")), b.text_input("Option B", key=k("ob")),
               a.text_input("Option C", key=k("oc")), b.text_input("Option D", key=k("od"))]
        options = [o.strip() for o in raw if o.strip()]
        if options:
            answer = st.selectbox("Correct Option", options, key=k("ocorrect"))
        else:
            st.info("💡 Type at least 2 options above to activate the correct-option selector.")
    elif qtype == "code":
        answer = st.text_area("Reference solution / marking rubric", key=k("nans"),
                              placeholder="Expected logic, test cases, rubric…")
    else:
        answer = st.text_area("Model answer / evaluation guidelines", key=k("nans"))

    if st.button("💾 Save Question to Bank", type="primary", **STRETCH):
        if not prompt.strip():
            st.error("Question prompt cannot be empty.")
        elif not number.strip():
            st.error("Please give the question a number / identifier.")
        elif store.number_exists(number):
            st.error(f"Question number **{number.strip()}** is already used in this department.")
        elif qtype == "mcq" and len(options) < 2:
            st.error("MCQs require at least 2 options.")
        else:
            store.add_question({
                "number": number.strip(), "identifier": identifier.strip(), "type": qtype,
                "question": prompt.strip(), "options": options if qtype == "mcq" else [],
                "answer": answer.strip(), "max_marks": float(marks),
            })
            ss["form_success"] = f"Saved Question {number.strip()} ({marks:g} marks)."
            ss["new_q_ver"] = ver + 1
            st.rerun()


def _bank_overview(store):
    qs = store.questions()
    st.markdown("#### 📚 Question Bank")
    if not qs:
        st.info("No questions yet — add the first one above.")
        return qs
    c1, c2, c3 = st.columns(3)
    c1.metric("Questions", len(qs))
    c2.metric("Total Marks", f"{sum(q['max_marks'] for q in qs):g}")
    c3.metric("MCQs", sum(q["type"] == "mcq" for q in qs))
    df = pd.DataFrame([{
        "No.": q["number"], "Identifier": q["identifier"], "Type": q["type"].upper(),
        "Marks": q["max_marks"], "Question": q["question"][:90] + ("…" if len(q["question"]) > 90 else ""),
    } for q in qs])
    st.dataframe(df, hide_index=True)
    return qs


def _edit_section(store, qs):
    if not qs:
        return
    st.markdown("#### ✏️ Modify or Remove a Question")
    st.caption("Edits never change submissions already made — each submission keeps its own copy of the paper.")
    labels = {f"Q{q['number']} · {q['question'][:50]}…": q["id"] for q in qs}
    sel = st.selectbox("Select question", list(labels), key="edit_sel")
    q = next(x for x in qs if x["id"] == labels[sel])
    with st.form(f"edit_form_{q['id']}"):
        c1, c2, c3 = st.columns([1, 2, 1])
        number = c1.text_input("Question No.", value=q["number"])
        identifier = c2.text_input("Identifier / Topic", value=q["identifier"])
        marks = c3.number_input("Max Marks", min_value=0.5, max_value=100.0, step=0.5, value=float(q["max_marks"]))
        prompt = st.text_area("Prompt", value=q["question"])
        opts_text = None
        if q["type"] == "mcq":
            opts_text = st.text_area("Options (one per line)", value="\n".join(q["options"]))
        answer = st.text_area("Correct option / model answer / rubric", value=q["answer"])
        col_a, col_b = st.columns(2)
        upd = col_a.form_submit_button("🔄 Update", **STRETCH)
        confirm_del = col_b.checkbox("Confirm deletion")
        dele = col_b.form_submit_button("🗑️ Delete", **STRETCH)

    if upd:
        options = [o.strip() for o in opts_text.splitlines() if o.strip()] if opts_text is not None else q["options"]
        if not prompt.strip() or not number.strip():
            st.error("Number and prompt are required.")
        elif store.number_exists(number, exclude_id=q["id"]):
            st.error("That question number is already used.")
        elif q["type"] == "mcq" and (len(options) < 2 or answer.strip() not in options):
            st.error("MCQ needs ≥2 options and the answer must exactly match one of them.")
        else:
            data = [dict(x) for x in read_raw(store)]
            for x in data:
                if x["id"] == q["id"]:
                    x.update(number=number.strip(), identifier=identifier.strip(), max_marks=float(marks),
                             question=prompt.strip(), answer=answer.strip(), options=options)
            store.save_questions(data)
            ss["form_success"] = f"Updated Question {number.strip()}."
            st.rerun()
    if dele:
        if confirm_del:
            store.save_questions([x for x in read_raw(store) if x["id"] != q["id"]])
            ss["form_success"] = f"Deleted Question {q['number']}."
            st.rerun()
        else:
            st.warning("Tick **Confirm deletion** first.")


def read_raw(store):
    return read_json(store._q_path, [])


def _import_section(store):
    st.markdown("#### 📄 Smart PDF / Scanned Image Importer")
    up = st.file_uploader("Upload Question Paper", type=DOC_EXTS, key="import_file")
    c1, c2 = st.columns(2)
    default_marks = c1.number_input("Marks per imported question", 0.5, 100.0, 5.0, 0.5)
    itype = c2.selectbox("Import as type", ["long", "short", "code"], format_func=lambda c: QUESTION_TYPES[c])
    if up is None or not st.button("🚀 Process & Import Questions", **STRETCH):
        return
    try:
        import pypdf, pytesseract, platform
        from pdf2image import convert_from_bytes
        from PIL import Image
    except ImportError as e:
        st.error(f"Importer needs extra packages: {e}. See requirements.txt.")
        return
    if platform.system() == "Windows":
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    with st.spinner("Extracting and structuring text…"):
        try:
            data, text = up.getvalue(), ""
            if up.name.lower().endswith(".pdf"):
                for page in pypdf.PdfReader(io.BytesIO(data)).pages:
                    text += (page.extract_text() or "") + "\n"
                if not text.strip():
                    text = "\n".join(pytesseract.image_to_string(img) for img in convert_from_bytes(data))
            else:
                text = pytesseract.image_to_string(Image.open(io.BytesIO(data)))
            if not text.strip():
                st.error("OCR could not extract readable text.")
                return
            added = 0
            for block in re.split(r"\n\s*(?=\d+[.)]\s)", text):
                block = block.strip()
                if not block:
                    continue
                m = re.match(r"(\d+)[.)]\s+", block)
                number = store.free_number(m.group(1) if m else None)
                store.add_question({"number": number, "identifier": "", "type": itype,
                                    "question": block[m.end():] if m else block, "options": [],
                                    "answer": "Faculty review guideline.", "max_marks": float(default_marks)})
                added += 1
            ss["form_success"] = f"Imported {added} questions ({default_marks:g} marks each) — review their numbers and marks below."
            st.rerun()
        except Exception as e:  # noqa: BLE001 - show any OCR/PDF failure to the teacher
            st.error(f"Import error: {e}")


def render_creator(store):
    banner("✍️ Question Creator Studio", f"{store.dept} — numbering, weightage, editing and import")
    _flash()
    _add_section(store)
    st.markdown("---")
    qs = _bank_overview(store)
    st.markdown("---")
    _edit_section(store, qs)
    st.markdown("---")
    _import_section(store)


# ======================================================================
# VIEWS/EVALUATION — Teacher evaluation & marking dashboard + report-card finalisation.
# ======================================================================
STATUS = {"submitted": "PENDING ⏳", "in_review": "IN REVIEW ✏️", "finalized": "FINALISED ✅"}


def _show_files(store, sub, qid, files):
    for slot, f in files.items():
        path = store.resolve_upload(f.get("path", ""))
        label = "Code file" if slot == "code_file" else "Document / image"
        st.markdown(f"📎 **{label}:** `{f['name']}`")
        if not path or not path.exists():
            st.warning("File is missing on the server.")
            continue
        low = f["name"].lower()
        if low.endswith((".png", ".jpg", ".jpeg")):
            st.image(str(path), width=520)
        elif low.endswith((".py", ".txt")):
            st.code(path.read_text(encoding="utf-8", errors="replace")[:20000], language="python")
        with open(path, "rb") as fh:
            st.download_button(f"📥 Download {f['name']}", fh.read(), file_name=f["name"],
                               key=f"dl_{sub['submission_id']}_{qid}_{slot}")


def _answer_block(store, sub, q):
    a = sub["answers"].get(str(q["id"]), {})
    if q["type"] == "mcq":
        ok = a.get("choice") == q["answer"]
        key = q["answer"]
        if ok:
            st.success(f"Student choice: **{a.get('choice')}** — Correct ✅")
        else:
            st.error(f"Student choice: **{a.get('choice')}** — Incorrect ❌ · Key: **{key}**")
        return
    if a.get("text", "").strip():
        st.info(f"**Typed answer**\n\n{a['text']}")
    if a.get("code", "").strip():
        st.markdown("**Submitted code (never executed):**")
        st.code(a["code"], language="python")
    if not a.get("files") and not a.get("text", "").strip() and not a.get("code", "").strip():
        st.warning("No answer provided.")
    _show_files(store, sub, q["id"], a.get("files", {}))
    st.caption(f"Model key / rubric: {q['answer'] or '—'}")


def _collect_marks(sub):
    marks = dict(sub.get("marks", {}))
    remarks = dict(sub.get("remarks", {}))
    sid = sub["submission_id"]
    for q in sub["paper"]:
        if q["type"] == "mcq":
            continue
        qid = str(q["id"])
        marks[qid] = float(ss.get(f"mark_{sid}_{qid}", marks.get(qid, 0.0)))
        remarks[qid] = ss.get(f"remark_{sid}_{qid}", remarks.get(qid, ""))
    return marks, remarks, ss.get(f"feedback_{sid}", sub.get("overall_feedback", ""))


def _save(store, sub, finalize, user):
    marks, remarks, feedback = _collect_marks(sub)
    updates = {"marks": marks, "remarks": remarks, "overall_feedback": feedback, "status": "in_review"}
    if finalize:
        updates.update(status="finalized", evaluated_by=user["username"], evaluated_at=now_str())
    new = store.update_submission(sub["submission_id"], updates)
    if finalize:
        audit("evaluation_finalized", user["username"], f"{store.dept}/{sub['submission_id']}")
        try:
            store.report_path(sub["submission_id"]).write_bytes(build_report_pdf(new, store.dept))
            ss["form_success"] = f"✅ Finalised {sub['submission_id']} — report card generated."
        except ImportError:
            ss["form_success"] = "Finalised, but PDF support (reportlab) is not installed — run: pip install reportlab"
    else:
        ss["form_success"] = f"Progress saved for {sub['submission_id']}."
    st.rerun()


def render_evaluation(store, user):
    banner("👨‍🏫 Evaluation & Marking Dashboard", f"{store.dept} — review code and scripts, award marks, issue report cards")
    if "form_success" in ss:
        st.success(ss.pop("form_success"))

    subs = store.submissions()
    if not subs:
        st.info("No student submissions yet.")
        return
    counts = {k: sum(s["status"] == k for s in subs) for k in STATUS}
    c1, c2, c3 = st.columns(3)
    c1.metric("Pending", counts["submitted"])
    c2.metric("In review", counts["in_review"])
    c3.metric("Finalised", counts["finalized"])

    flt = st.radio("Show", ["All", "Pending", "In review", "Finalised"], horizontal=True)
    want = {"All": None, "Pending": "submitted", "In review": "in_review", "Finalised": "finalized"}[flt]
    shown = [s for s in subs if want is None or s["status"] == want]
    if not shown:
        st.info("Nothing in this category.")
        return
    labels = {f"{s['submission_id']} — {s['student_name']} (Roll {s['roll_no']}) [{STATUS[s['status']]}]": s["submission_id"]
              for s in shown}
    sid = labels[st.selectbox("Select submission", list(labels))]
    sub = store.get_submission(sid)
    finalized = sub["status"] == "finalized"

    st.markdown(f"### {sub['student_name']} · Roll {sub['roll_no']} · `{sid}`")
    st.caption(f"Submitted {sub['timestamp']}")
    live_marks = _collect_marks(sub)[0] if not finalized else sub["marks"]
    t = totals({**sub, "marks": live_marks})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Marks", f"{t['obtained']:g} / {t['max']:g}")
    m2.metric("Percentage", f"{t['percent']:.1f}%")
    m3.metric("Grade", t["grade"])
    m4.metric("Result", "PASS" if t["passed"] else "FAIL")
    st.markdown("---")

    for q in sub["paper"]:
        qid = str(q["id"])
        with st.expander(f"Q{q['number']} · {q['max_marks']:g} marks · {q['type'].upper()}"
                         + (f" · {q['identifier']}" if q.get("identifier") else ""), expanded=True):
            st.markdown(f"**{q['question']}**")
            _answer_block(store, sub, q)
            if q["type"] == "mcq":
                st.caption(f"Auto-awarded: {sub['marks'].get(qid, 0):g} / {q['max_marks']:g}")
            elif finalized:
                st.markdown(f"**Awarded:** {sub['marks'].get(qid, 0):g} / {q['max_marks']:g}  \n"
                            f"**Remark:** {sub.get('remarks', {}).get(qid) or '—'}")
            else:
                a, b = st.columns([1, 3])
                a.number_input(f"Marks (max {q['max_marks']:g})", 0.0, float(q["max_marks"]), step=0.5,
                               value=min(float(sub["marks"].get(qid, 0.0)), float(q["max_marks"])),
                               key=f"mark_{sid}_{qid}")
                b.text_input("Faculty remark", value=sub.get("remarks", {}).get(qid, ""),
                             placeholder="e.g. Correct logic, missing edge-case handling", key=f"remark_{sid}_{qid}")

    if finalized:
        st.markdown(f"**Overall feedback:** {sub.get('overall_feedback') or '—'}")
        st.caption(f"Finalised by {sub.get('evaluated_by')} on {sub.get('evaluated_at')}")
        _report_download(store, sub)
        if st.button("🔓 Re-open for editing", **STRETCH):
            store.update_submission(sid, {"status": "in_review"})
            audit("evaluation_reopened", user["username"], f"{store.dept}/{sid}")
            st.rerun()
    else:
        st.text_area("Overall feedback for the student", value=sub.get("overall_feedback", ""), key=f"feedback_{sid}")
        b1, b2 = st.columns(2)
        if b1.button("💾 Save Progress", **STRETCH):
            _save(store, sub, False, user)
        if b2.button("✅ Finalise & Generate Report Card", type="primary", **STRETCH):
            _save(store, sub, True, user)

    with st.expander("⚠️ Danger zone"):
        ok = st.checkbox("I understand this permanently deletes the submission and its files", key=f"del_ok_{sid}")
        if st.button("🗑️ Delete submission", disabled=not ok, key=f"del_{sid}"):
            store.delete_submission(sid)
            audit("submission_deleted", user["username"], f"{store.dept}/{sid}")
            st.rerun()


def _report_download(store, sub):
    try:
        rp = store.report_path(sub["submission_id"])
        data = rp.read_bytes() if rp.exists() else build_report_pdf(sub, store.dept)
        st.download_button("📄 Download Report Card (PDF)", data, file_name=f"ReportCard_{sub['submission_id']}.pdf",
                           mime="application/pdf", key=f"rc_{sub['submission_id']}", **STRETCH)
    except ImportError:
        st.error("Install reportlab to generate PDFs: pip install reportlab")


# ======================================================================
# VIEWS/ANALYTICS — Performance analytics dashboard (finalised evaluations only).
# ======================================================================
GRADES = [g for _, g, _ in GRADE_SCALE]


def _results_frame(subs):
    rows = []
    for s in subs:
        if s["status"] != "finalized":
            continue
        t = totals(s)
        rows.append({
            "Submission": s["submission_id"], "Roll": s["roll_no"], "Student": s["student_name"],
            "Marks": t["obtained"], "Max": t["max"], "Percent": t["percent"], "Grade": t["grade"],
            "Result": "PASS" if t["passed"] else "FAIL", "Date": s["timestamp"][:10],
        })
    return pd.DataFrame(rows)


def _question_frame(subs):
    rows = []
    for s in subs:
        if s["status"] != "finalized":
            continue
        for q in s["paper"]:
            got = min(float(s["marks"].get(str(q["id"]), 0) or 0), float(q["max_marks"]))
            rows.append({"Q": f"Q{q['number']}", "Type": q["type"], "pct": got / float(q["max_marks"]) * 100})
    return pd.DataFrame(rows)


def _kpis(df, total_subs):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Submissions", total_subs)
    c2.metric("Evaluated", len(df))
    c3.metric("Average", f"{df['Percent'].mean():.1f}%")
    c4.metric("Highest", f"{df['Percent'].max():.1f}%")
    c5.metric("Pass rate", f"{(df['Result'] == 'PASS').mean() * 100:.0f}%")


def _department_view(store):
    subs = store.submissions()
    if not subs:
        st.info("No submissions in this department yet.")
        return
    df = _results_frame(subs)
    st.markdown("##### 🧭 Evaluation progress")
    done = len(df)
    st.progress(done / len(subs), text=f"{done} of {len(subs)} submissions finalised")
    if df.empty:
        st.info("Analytics appear once at least one evaluation is finalised.")
        return
    _kpis(df, len(subs))

    t_dist, t_q, t_students = st.tabs(["📈 Score Distribution", "🧩 Question Analysis", "🏅 Student Records"])
    with t_dist:
        bins = list(range(0, 101, 10))
        labels = [f"{b}-{b + 10}" for b in bins[:-1]]
        hist = pd.cut(df["Percent"], bins=bins, labels=labels, include_lowest=True, right=False)
        hist = hist.fillna(labels[-1]).value_counts().reindex(labels, fill_value=0)
        st.markdown("**Score distribution (% bands)**")
        st.bar_chart(hist, color="#ff2e97")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Grade distribution**")
            st.bar_chart(df["Grade"].value_counts().reindex(GRADES, fill_value=0), color="#00e5ff")
        with c2:
            st.markdown("**Submissions per day**")
            st.line_chart(pd.to_datetime(df["Date"]).value_counts().sort_index(), color="#ffd400")
        st.caption(f"Median {df['Percent'].median():.1f}% · Std. deviation {df['Percent'].std(ddof=0):.1f} · "
                   f"Lowest {df['Percent'].min():.1f}%")
    with t_q:
        qdf = _question_frame(subs)
        avg = qdf.groupby("Q", sort=False)["pct"].mean().round(1)
        st.markdown("**Average score per question (%)** — low bars flag difficult or poorly-taught topics")
        st.bar_chart(avg, color="#7b2ff7")
        weak = avg[avg < 50]
        if len(weak):
            st.warning("Questions averaging below 50%: " + ", ".join(f"{q} ({v:.0f}%)" for q, v in weak.items()))
        by_type = qdf.groupby("Type")["pct"].mean().round(1)
        st.markdown("**Average by question type (%)**")
        st.bar_chart(by_type, color="#00ff9d")
    with t_students:
        c1, c2 = st.columns(2)
        c1.markdown("**🏆 Top performers**")
        c1.dataframe(df.nlargest(5, "Percent")[["Roll", "Student", "Percent", "Grade"]], hide_index=True)
        c2.markdown("**🚨 Needs attention (below pass mark)**")
        low = df[df["Percent"] < PASS_PERCENT].sort_values("Percent")[["Roll", "Student", "Percent", "Grade"]]
        c2.dataframe(low, hide_index=True) if len(low) else c2.success("Everyone has passed 🎉")
        st.markdown("**All finalised results**")
        st.dataframe(df.sort_values("Percent", ascending=False), hide_index=True)
        st.download_button("📥 Download results (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{store.slug}_results.csv", mime="text/csv")


def _all_departments_view():
    rows = []
    for dept in DEPARTMENTS:
        subs = DeptStore(dept).submissions()
        df = _results_frame(subs)
        rows.append({
            "Department": dept, "Submissions": len(subs), "Finalised": len(df),
            "Progress %": round(len(df) / len(subs) * 100) if subs else 0,
            "Avg %": round(df["Percent"].mean(), 1) if len(df) else None,
            "Pass rate %": round((df["Result"] == "PASS").mean() * 100) if len(df) else None,
        })
    summary = pd.DataFrame(rows)
    st.markdown("**Departmental progress summary**")
    st.dataframe(summary, hide_index=True)
    if summary["Avg %"].notna().any():
        st.markdown("**Average score by department (%)**")
        st.bar_chart(summary.set_index("Department")["Avg %"].dropna(), color="#ff2e97")
        st.markdown("**Evaluation progress by department (%)**")
        st.bar_chart(summary.set_index("Department")["Progress %"], color="#00e5ff")


def render_analytics(store, user):
    banner("📊 Performance Analytics", "Scores, distributions and progress — restricted to faculty")
    if user["role"] == "admin":
        t1, t2 = st.tabs([f"🏛️ {store.dept}", "🌐 All Departments"])
        with t1:
            _department_view(store)
        with t2:
            _all_departments_view()
    else:
        _department_view(store)


# ======================================================================
# APP — Departmental Assessment & Grading Portal - entry point.   Run:  streamlit run app.py
# ======================================================================
apply_theme()
apply_admin_reset_secret()
ensure_admin_bootstrap()

# ---------------------------------------------------------------- session & role
user = current_user()                    # enforces idle timeout
dept = st.session_state.get("dept")
if "flash" in st.session_state:
    st.warning(st.session_state.pop("flash"))


def allowed_pages():
    pages = [P_HOME]
    if dept:
        pages += [P_TAKE, P_CARD]
    if user is None:
        pages.append(P_LOGIN)
    else:
        if can_manage(user, dept):
            pages += [P_CREATOR, P_EVAL, P_ANALYTICS]
        if is_admin(user):
            pages.append(P_ADMIN)
        pages.append(P_ACCOUNT)
    return pages


pages = allowed_pages()
if user and user.get("must_change"):
    pages = [P_ACCOUNT]                       # forced password change before anything else

# programmatic navigation requested by a previous run
if "_goto" in st.session_state:
    target = st.session_state.pop("_goto")
    if target in pages:
        st.session_state["nav"] = target
if st.session_state.get("nav") not in pages:
    st.session_state["nav"] = pages[0]

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 🎓 Portal")
    if user is None:
        st.markdown("<span class='role-chip student'>STUDENT / GUEST</span>", unsafe_allow_html=True)
    else:
        st.markdown(f"<span class='role-chip'>{user['role'].upper()} · {user['username']}</span>", unsafe_allow_html=True)
    st.markdown(f"**Department:** {dept or '— not selected —'}")
    page = st.radio("Navigate", pages, key="nav", label_visibility="collapsed")
    if user:
        st.caption("Session auto-expires after 30 idle minutes.")

# ---------------------------------------------------------------- RBAC gate (defence in depth)
if page in TEACHER_PAGES and not can_manage(user, dept):
    audit("access_denied", user["username"] if user else "student", f"{page} / {dept}")
    st.error("⛔ Access denied. This page is restricted to faculty of the selected department.")
    st.stop()
if page in ADMIN_PAGES and not is_admin(user):
    audit("access_denied", user["username"] if user else "student", page)
    st.error("⛔ Access denied. Administrators only.")
    st.stop()

# ---------------------------------------------------------------- router
if page == P_HOME:
    render_home()
elif page == P_LOGIN:
    render_login(dept)
elif page == P_ACCOUNT and user:
    render_account(user)
elif page == P_ADMIN:
    render_admin(user)
elif dept is None:
    st.warning("Please select a department on the Home page first.")
else:
    store = DeptStore(dept)
    if page == P_TAKE:
        render_assessment(store)
    elif page == P_CARD:
        render_report_card(store)
    elif page == P_CREATOR:
        render_creator(store)
    elif page == P_EVAL:
        render_evaluation(store, user)
    elif page == P_ANALYTICS:
        render_analytics(store, user)
