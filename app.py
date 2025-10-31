
import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from google.oauth2.service_account import Credentials
from urllib.parse import quote

st.set_page_config(page_title="Padel Splitter", page_icon="🎾", layout="wide")

# -----------------------------
# Configuration & Secrets
# -----------------------------
# [gcp_service_account]  # your service account JSON fields
#
# [sheets]
# db_key="YOUR_GOOGLE_SHEET_ID"
# payer_email="marcusadams@fastmail.fm"  # prefilled per request
# group_name="Wainwright Paddle Team"
#
# [auth]
# join_code="WAIN2025"  # lightweight sign-in
#
# [payments]
# monzo_username="monzo.me/marcusadams3"  # paste full monzo.me link or just the handle; app normalises it

REQUIRED_TABS = ["sessions", "registrations", "payments", "players", "meta"]
SESSIONS_COLUMNS = ["session_id", "date", "fee", "notes", "created_at"]
REG_COLUMNS = ["session_id", "player_email", "player_name", "registered_at"]
PAY_COLUMNS = ["player_email", "player_name", "amount", "paid_at", "note"]
PLAYERS_COLUMNS = ["player_email", "player_name", "whatsapp", "payout_link", "active", "created_at"]

# -----------------------------
# Google Sheets helpers
# -----------------------------
@st.cache_resource(show_spinner=False)
def get_gsheet_client():
    creds_dict = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    return gc

@st.cache_resource(show_spinner=False)
def open_db():
    gc = get_gsheet_client()
    key = st.secrets["sheets"]["db_key"]
    return gc.open_by_key(key)

def ensure_worksheet(sh, title, header):
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(header))
        ws.append_row(header)
    try:
        first_row = ws.row_values(1)
        if first_row != header:
            ws.update('1:1', [header])
    except Exception:
        pass
    return ws

def ensure_all_tabs():
    sh = open_db()
    tabs = {}
    tabs["sessions"] = ensure_worksheet(sh, "sessions", SESSIONS_COLUMNS)
    tabs["registrations"] = ensure_worksheet(sh, "registrations", REG_COLUMNS)
    tabs["payments"] = ensure_worksheet(sh, "payments", PAY_COLUMNS)
    tabs["players"] = ensure_worksheet(sh, "players", PLAYERS_COLUMNS)
    tabs["meta"] = ensure_worksheet(sh, "meta", ["key", "value", "updated_at"])
    return tabs

def load_df(ws, header):
    rows = ws.get_all_records()
    if not rows:
        return pd.DataFrame(columns=header)
    df = pd.DataFrame(rows)
    for c in header:
        if c not in df.columns:
            df[c] = None
    return df[header]

def append_row(ws, row):
    ws.append_row(row, value_input_option="USER_ENTERED")

def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def to_iso_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def parse_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default

# -----------------------------
# Domain logic
# -----------------------------
def compute_balances(sessions_df, regs_df, payments_df, payer_email):
    balances = {}
    emails = set(regs_df["player_email"].dropna().tolist()) | set(payments_df["player_email"].dropna().tolist())
    emails.add(payer_email)
    for e in emails:
        balances[e] = 0.0

    for _, s in sessions_df.iterrows():
        sid = s.get("session_id") or s.get("date")
        fee = parse_float(s.get("fee", 0.0))
        attendees = regs_df[regs_df["session_id"] == sid]["player_email"].dropna().unique().tolist()
        n = len(attendees)
        if n <= 0 or fee <= 0:
            continue
        share = fee / n
        for e in attendees:
            balances[e] = balances.get(e, 0.0) + share

    for _, p in payments_df.iterrows():
        e = p.get("player_email")
        amt = parse_float(p.get("amount", 0.0))
        if not e or amt <= 0:
            continue
        balances[e] = balances.get(e, 0.0) - amt

    non_payer_total = sum(v for k, v in balances.items() if k != payer_email)
    balances[payer_email] = -non_payer_total
    return balances

def load_all():
    tabs = ensure_all_tabs()
    sessions = load_df(tabs["sessions"], SESSIONS_COLUMNS)
    regs = load_df(tabs["registrations"], REG_COLUMNS)
    pays = load_df(tabs["payments"], PAY_COLUMNS)
    players = load_df(tabs["players"], PLAYERS_COLUMNS)
    return tabs, sessions, regs, pays, players

# -----------------------------
# Auth & Profile
# -----------------------------
def group_name():
    return st.secrets["sheets"].get("group_name", "Wainwright Paddle Team")

def signed_in_email():
    return st.session_state.get("email")

def require_sign_in():
    if signed_in_email():
        return True
    st.info("Sign in to continue.")
    with st.form("signin"):
        email = st.text_input("Your email")
        join_code = st.text_input("Group join code", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            code = st.secrets.get("auth", {}).get("join_code", "").strip()
            if not email:
                st.error("Email is required.", icon="⚠️")
            elif code and join_code != code:
                st.error("Join code is incorrect.", icon="⚠️")
            else:
                st.session_state["email"] = email.strip().lower()
                st.success("Signed in.", icon="✅")
                return True
    return False

def upsert_player(tabs, players_df, email, name=None, whatsapp=None, payout_link=None, active="TRUE"):
    append_row(tabs["players"], [email, name or "", whatsapp or "", payout_link or "", active, now_iso()])

# -----------------------------
# UI helpers
# -----------------------------
def header():
    st.markdown(f"<h1 style='margin-bottom:0'>🎾 {group_name()}</h1>", unsafe_allow_html=True)
    st.caption("Fair splits for weekly court fees.")

def toast_ok(msg):
    st.success(msg, icon="✅")

def toast_err(msg):
    st.error(msg, icon="⚠️")

def currency(v):
    try:
        return f"£{float(v):.2f}"
    except Exception:
        return "£0.00"

# --- Monzo helpers ---
def normalise_monzo_username(raw):
    """Accepts 'marcus', 'monzo.me/marcus', or full URL with params and returns 'marcus'."""
    if not raw:
        return None
    s = str(raw).strip()
    # remove scheme
    for pref in ("https://", "http://"):
        if s.lower().startswith(pref):
            s = s[len(pref):]
    # strip whitespace and slashes
    s = s.strip().strip('/')
    # if domain present, drop it
    if s.lower().startswith("monzo.me/"):
        s = s.split("/", 1)[1]
    elif s.lower().startswith("www.monzo.me/"):
        s = s.split("/", 1)[1]
    # drop query/fragment
    s = s.split("?", 1)[0].split("#", 1)[0]
    # if still a path, take last segment
    if "/" in s:
        parts = [p for p in s.split("/") if p]
        if parts:
            s = parts[-1]
    # drop leading @ if any
    if s.startswith("@"):
        s = s[1:]
    return s

def payer_monzo_username():
    raw = st.secrets.get("payments", {}).get("monzo_username")
    handle = normalise_monzo_username(raw) if raw else None
    return handle

def monzo_request_link(username, amount, description):
    amt = f"{float(amount):.2f}"
    return f"https://monzo.me/{username}/{amt}?d={quote(description)}"

# -----------------------------
# Pages
# -----------------------------
def page_balances(tabs, sessions, regs, pays, players):
    payer_email = st.secrets["sheets"].get("payer_email", "").strip()
    if not payer_email:
        st.warning("Set **payer_email** in Streamlit secrets.", icon="⚙️")
        return

    balances = compute_balances(sessions, regs, pays, payer_email)

    names = {r["player_email"]: r["player_name"] for _, r in players.iterrows() if r.get("player_email")}

    entries = []
    for e, amt in balances.items():
        name = names.get(e, e)
        entries.append({"Player": name, "Email": e, "Balance": round(float(amt), 2)})
    df = pd.DataFrame(entries).sort_values(by="Balance", ascending=False).reset_index(drop=True)

    st.subheader("Current balances")
    st.caption("Positive means the player **owes** the payer. Negative means they have **credit**.")
    st.dataframe(df[["Player", "Email", "Balance"]].style.format({"Balance": "£{:.2f}"}), use_container_width=True)

    # Quick Monzo request links
    monzo_user = payer_monzo_username()
    if monzo_user:
        st.divider()
        st.subheader("Quick Monzo request links")
        for _, row in df.iterrows():
            if row["Email"] == payer_email:
                continue
            if row["Balance"] > 0.0:
                link = monzo_request_link(monzo_user, row["Balance"], f"Padel {group_name()}")
                st.markdown(f"- **{row['Player']}** — {currency(row['Balance'])} → [Monzo Request]({link})")

    # WhatsApp settle-up message
    st.divider()
    st.subheader("WhatsApp settle‑up message")
    lines = [f"Hi all — settle‑up for {group_name()}:", ""]
    for _, row in df.iterrows():
        if row["Email"] == payer_email:
            continue
        if row["Balance"] > 0.0:
            part = f"- {row['Player']}: {currency(row['Balance'])}"
            if monzo_user:
                pay = monzo_request_link(monzo_user, row["Balance"], f"Padel {group_name()}")
                part += f" → {pay}"
            lines.append(part)
    wa_text = "\n".join(lines) if len(lines) > 2 else "No one owes anything right now 🎉"
    st.text_area("Copy & paste into WhatsApp:", value=wa_text, height=200)

    # Log a payment
    st.divider()
    st.subheader("Log a payment")
    with st.form("log_payment"):
        c1, c2 = st.columns([2,1])
        with c1:
            who = st.selectbox("Who paid the payer?", df[df["Email"] != payer_email]["Email"].tolist())
            name_default = names.get(who, "")
            name = st.text_input("Player name", value=name_default)
            note = st.text_input("Note (optional)", value="")
        with c2:
            amount = st.number_input("Amount (£)", min_value=0.0, step=1.0, format="%.2f")
            paid_at = st.date_input("Paid on", value=date.today())
        submitted = st.form_submit_button("Add payment", use_container_width=True)
        if submitted:
            if amount <= 0:
                toast_err("Amount must be greater than zero.")
            else:
                append_row(tabs["payments"], [who, name, amount, to_iso_date(paid_at), note])
                st.cache_data.clear()
                st.cache_resource.clear()
                toast_ok("Payment recorded.")

def page_register(tabs, sessions, regs, pays, players):
    if not require_sign_in():
        return
    st.subheader("Register that you played")
    if sessions.empty:
        st.info("No sessions yet. Ask the payer/admin to add one on the Sessions page.")
        return
    latest_first = sessions.sort_values("date", ascending=False)

    email = signed_in_email()
    existing = players[players["player_email"] == email]
    name_default = existing["player_name"].iloc[0] if not existing.empty else ""

    sid = st.selectbox("Which session?", latest_first["session_id"].tolist(), index=0)
    name = st.text_input("Your name", value=name_default)

    if st.button("I played", use_container_width=True, type="primary"):
        if not name:
            toast_err("Please fill in your name.")
            return
        already = regs[(regs["session_id"] == sid) & (regs["player_email"] == email)]
        if not already.empty:
            toast_err("You're already registered for that session.")
            return
        append_row(tabs["registrations"], [sid, email, name, now_iso()])
        if existing.empty:
            upsert_player(tabs, players, email=email, name=name, active="TRUE")
        st.cache_data.clear()
        st.cache_resource.clear()
        toast_ok("Registered.")

    st.divider()
    st.subheader("Who else is playing?")
    regs_for_selected = regs[regs["session_id"] == sid]
    st.dataframe(regs_for_selected[["player_name", "player_email", "registered_at"]].rename(
        columns={"player_name": "Name", "player_email": "Email", "registered_at":"Registered"}),
        use_container_width=True
    )

def page_sessions(tabs, sessions, regs, pays, players):
    st.subheader("Sessions (admin)")
    with st.form("add_session"):
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            d = st.date_input("Date", value=date.today())
        with c2:
            fee = st.number_input("Court fee (£)", min_value=0.0, step=1.0, format="%.2f")
        with c3:
            notes = st.text_input("Notes (optional)", value="")
        submitted = st.form_submit_button("Add session", use_container_width=True)
        if submitted:
            sid = to_iso_date(d)
            if not sessions[sessions["session_id"] == sid].empty:
                toast_err("A session for this date already exists.")
            else:
                append_row(tabs["sessions"], [sid, sid, fee, notes, now_iso()])
                st.cache_data.clear()
                st.cache_resource.clear()
                toast_ok("Session added.")

    if sessions.empty:
        return

    st.divider()
    st.subheader("Session list")
    sess = sessions.sort_values("date", ascending=False).copy()
    rows = []
    for _, s in sess.iterrows():
        sid = s["session_id"]
        fee = parse_float(s["fee"], 0.0)
        attendees = regs[regs["session_id"] == sid]["player_email"].nunique()
        share = (fee / attendees) if attendees > 0 else 0.0
        rows.append({
            "Date": sid,
            "Fee": fee,
            "Attendees": attendees,
            "Per-person share": share,
            "Notes": s.get("notes", "")
        })
    view = pd.DataFrame(rows)
    if not view.empty:
        st.dataframe(
            view.style.format({"Fee": "£{:.2f}", "Per-person share": "£{:.2f}"}),
            use_container_width=True
        )

def page_players(tabs, sessions, regs, pays, players):
    if not require_sign_in():
        return
    email = signed_in_email()
    st.subheader("My profile")
    existing = players[players["player_email"] == email]
    name_default = existing["player_name"].iloc[0] if not existing.empty else ""
    wa_default = existing["whatsapp"].iloc[0] if not existing.empty else ""
    link_default = existing["payout_link"].iloc[0] if not existing.empty else ""

    with st.form("profile"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Your name", value=name_default)
            whatsapp = st.text_input("Whatsapp number (optional)", value=wa_default, help="Just digits or +44…")
        with c2:
            payout_link = st.text_input("Your payment link (optional)", value=link_default, help="Your Monzo/Revolut/PayPal link")
            st.write(f"Your email: **{email}**")
        submitted = st.form_submit_button("Save profile", use_container_width=True)
        if submitted:
            if not name:
                toast_err("Name is required.")
            else:
                upsert_player(tabs, players, email=email, name=name, whatsapp=whatsapp, payout_link=payout_link, active="TRUE")
                st.cache_data.clear()
                st.cache_resource.clear()
                toast_ok("Profile saved.")

    st.divider()
    st.subheader("All players (read‑only)")
    if not players.empty:
        show = players.copy().rename(columns={"player_name":"Name","player_email":"Email","whatsapp":"WhatsApp","payout_link":"Pay link","active":"Active"})
        st.dataframe(show[["Name","Email","WhatsApp","Pay link","Active"]], use_container_width=True)

# -----------------------------
# App
# -----------------------------
st.markdown(f"<h1 style='margin-bottom:0'>🎾 {group_name()}</h1>", unsafe_allow_html=True)
st.caption("Fair splits for weekly court fees.")

tabs, sessions, regs, pays, players = load_all()

pg = st.sidebar.radio("Navigation", ["Balances", "Register", "Sessions", "Players / Profile"])

if pg == "Balances":
    page_balances(tabs, sessions, regs, pays, players)
elif pg == "Register":
    page_register(tabs, sessions, regs, pays, players)
elif pg == "Sessions":
    page_sessions(tabs, sessions, regs, pays, players)
else:
    page_players(tabs, sessions, regs, pays, players)

st.sidebar.markdown("---")
st.sidebar.caption("Made with ❤️ for fair splits.")
