
import streamlit as st
import pandas as pd
from datetime import datetime, date
import json, re
import gspread
from google.oauth2.service_account import Credentials
from urllib.parse import quote

st.set_page_config(page_title="Padel Splitter", page_icon="🎾", layout="wide")

# ----------------- Global styling -----------------
st.markdown(
    '''
    <style>
    .login-bg { position: fixed; inset: 0;
        background: radial-gradient(1200px 600px at 10% -10%, #dbeafe 0%, rgba(219,234,254,0) 60%),
                    radial-gradient(800px 400px at 110% 10%, #fce7f3 0%, rgba(252,231,243,0) 60%);
        z-index: -1; }
    /* Base buttons */
    .stButton>button {
        border-radius: 9999px !important;
        padding: .45rem .9rem !important;
        border: 1px solid rgba(49,51,63,.2);
        background: rgba(49,51,63,.04);
        white-space: nowrap;
    }
    /* Primary buttons (active nav) */
    .stButton>button[kind="primary"] {
        background: #dc2626 !important;   /* red-600 */
        border-color: #dc2626 !important;
        color: white !important;
    }
    .stButton>button[kind="primary"]:hover {
        background: #b91c1c !important;   /* red-700 */
        border-color: #b91c1c !important;
        color: white !important;
    }
    /* Title & chip row */
    .chip {
        background:#eef2ff; color:#3730a3;
        padding:.35rem .65rem; border-radius:9999px;
        font-size:.9rem; white-space:nowrap;
        max-width: 260px; text-overflow: ellipsis; overflow: hidden; display:inline-block;
    }
    .top-right { display:flex; justify-content:flex-end; align-items:flex-start; margin-top:.2rem; }
    /* Mobile tweaks */
    @media (max-width: 600px) {
        .stButton>button { padding:.32rem .6rem !important; font-size:.85rem !important; }
        .chip { max-width: 160px; font-size:.82rem; }
    }
    
    /* --- Dark mode fixes for login screen --- */
    @media (prefers-color-scheme: dark) {
        .login-bg {
            background: #0b0b0c !important;
        }
        .login-card {
            background: #0b0b0c !important;
            color: #ffffff !important;
            border-color: rgba(255,255,255,.18) !important;
        }
        .login-card * {
            color: inherit !important;
        }
    }

    </style>
    ''', unsafe_allow_html=True
)

# ----------------- Column specs -----------------
SESSIONS_COLUMNS = ["session_id", "date", "fee", "notes", "created_at"]
REG_COLUMNS      = ["session_id", "player_email", "player_name", "registered_at"]
PAY_COLUMNS      = ["player_email", "player_name", "amount", "paid_at", "note"]
PLAYERS_COLUMNS  = ["player_email", "player_name", "whatsapp", "payout_link", "active", "created_at"]

# ----------------- Helpers -----------------
def now_iso() -> str: return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
def to_iso_date(d: date) -> str: return d.strftime("%Y-%m-%d")
def parse_float(value, default=0.0):
    try: return float(value)
    except Exception: return default
def currency(v):
    try: return f"£{float(v):.2f}"
    except Exception: return "£0.00"

def signed_in_email(): return (st.session_state.get("email") or "").strip().lower()

def logout():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# Pretty, *separate* login screen

def login_page():
    # Always read meta directly (no cache) for the login card
    try:
        meta_now = read_meta_dict_direct()
    except Exception:
        meta_now = {}

    gn_raw = str(meta_now.get("group_name", "") or "").strip()
    gn = gn_raw if gn_raw else "Set `group_name` in the Sheet → meta!"
    # Update session for consistency elsewhere
    st.session_state["meta_settings"] = meta_now

    st.markdown('<div class="login-bg"></div>', unsafe_allow_html=True)
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    _, c2, _ = st.columns([1,2,1])
    with c2:
        st.markdown(
            f"""
            <div class='login-card' style='background:white; border:1px solid rgba(49,51,63,.15); border-radius:16px; padding:1.25rem 1.25rem 1rem'>
                <div style='display:flex;align-items:center;gap:.6rem;margin-bottom:.75rem'>
                    <div style='font-size:1.75rem'>🎾</div>
                    <div>
                      <div style='font-size:1.05rem;opacity:.7'>Padel Splitter</div>
                      <div style='font-size:1.35rem;font-weight:700'>{gn}</div>
                    </div>
                </div>
                <div style='opacity:.8;margin-bottom:.75rem'>Sign in to continue. Use your email and the group passcode.</div>
            </div>
            """, unsafe_allow_html=True
        )
        with st.form("signin_global"):
            email = st.text_input("Email address")
            join_code = st.text_input("Group passcode", type="password")
            submitted = st.form_submit_button("Log in", use_container_width=True, type="primary")
            if submitted:
                # Validate against meta join_code (fallback to secrets only if meta missing)
                code = (meta_now.get("join_code", "") or st.secrets.get("auth", {}).get("join_code", "")).strip()
                if not email:
                    st.error("Email is required.", icon="⚠️")
                elif code and join_code != code:
                    st.error("Passcode is incorrect.", icon="⚠️")
                else:
                    st.session_state["email"] = email.strip().lower()
                    st.session_state["flash_msg"] = "Signed in."
                    st.rerun()
    st.stop()

# ----------------- Google Sheets client -----------------
@st.cache_resource(show_spinner=False)
def get_gsheet_client():
    raw = st.secrets["gcp_service_account"]
    creds_dict = json.loads(raw) if isinstance(raw, str) else dict(raw)
    pk = creds_dict.get("private_key", "")
    if "\n" in pk and "\n" not in pk.replace("\\n", ""):
        try: creds_dict["private_key"] = pk.encode("utf-8").decode("unicode_escape")
        except Exception: pass
    scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def open_db():
    return get_gsheet_client().open_by_key(st.secrets["sheets"]["db_key"])

def ensure_worksheet(sh, title, header):
    try: ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(header)); ws.append_row(header)
    try:
        first = ws.row_values(1)
        if first != header: ws.update('1:1', [header])
    except Exception: pass
    return ws

@st.cache_resource(show_spinner=False)
def ensure_all_tabs():
    sh = open_db()
    return {
        "sessions":      ensure_worksheet(sh, "sessions",      SESSIONS_COLUMNS),
        "registrations": ensure_worksheet(sh, "registrations", REG_COLUMNS),
        "payments":      ensure_worksheet(sh, "payments",      PAY_COLUMNS),
        "players":       ensure_worksheet(sh, "players",       PLAYERS_COLUMNS),
        "meta":          ensure_worksheet(sh, "meta",          ["key", "value", "updated_at"]),
    }

@st.cache_data(show_spinner=False, ttl=20)
def fetch_all_tables_as_dfs():
    # Use low-level HttpClient to batch-get values (works across gspread versions)
    sh = open_db()
    http = sh.client  # this is a gspread HttpClient
    ranges = ["sessions!A1:E", "registrations!A1:D", "payments!A1:E", "players!A1:F"]
    resp = http.values_batch_get(sh.id, ranges)
    value_ranges = resp.get("valueRanges", [])
    while len(value_ranges) < 4:
        value_ranges.append({"values": []})
    values_list = [vr.get("values", []) for vr in value_ranges]

    def to_df(vals, expected_header):
        if not vals: return pd.DataFrame(columns=expected_header)
        header = vals[0]; rows = vals[1:] if len(vals)>1 else []
        width = max(len(header), len(expected_header))
        header = (header + [""]*(width-len(header)))[:width]
        rows = [(r + [""]*(width-len(r)))[:width] for r in rows]
        df = pd.DataFrame(rows, columns=header)
        for c in expected_header:
            if c not in df.columns: df[c] = None
        return df[expected_header]

    return (
        to_df(values_list[0], SESSIONS_COLUMNS),
        to_df(values_list[1], REG_COLUMNS),
        to_df(values_list[2], PAY_COLUMNS),
        to_df(values_list[3], PLAYERS_COLUMNS),
    )

def append_row(ws, row):
    ws.append_row(row, value_input_option="USER_ENTERED")
    st.cache_data.clear()

# ----------------- Payments helpers (Monzo only) -----------------
def normalise_monzo_username(raw):
    if not raw: return None
    s = str(raw).strip()
    for pref in ("https://","http://"):
        if s.lower().startswith(pref): s = s[len(pref):]
    s = s.strip().strip('/')
    if s.lower().startswith("monzo.me/"): s = s.split("/",1)[1]
    elif s.lower().startswith("www.monzo.me/"): s = s.split("/",1)[1]
    s = s.split("?",1)[0].split("#",1)[0]
    if "/" in s:
        parts = [p for p in s.split("/") if p]
        if parts: s = parts[-1]
    if s.startswith("@"): s = s[1:]
    return s

def payer_monzo_username():
    raw = st.secrets.get("payments", {}).get("monzo_username")
    return normalise_monzo_username(raw) if raw else None

def monzo_request_link(username, amount, description):
    amt = f"{float(amount):.2f}"
    return f"https://monzo.me/{username}/{amt}?d={quote(description)}"

# Helper: UK date from sid like 'YYYY-MM-DD'
def fmt_uk_date(s: str) -> str:
    try:
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(s)

def _derived_name_from_email(email: str) -> str:
    local = (email or "").split("@")[0]
    local = local.replace('.', ' ').replace('_',' ').replace('-',' ')
    return " ".join([w.capitalize() for w in local.split() if w]) or email

def get_meta(key, default=None):
    return st.session_state.get("meta_settings", {}).get(key, default)

@st.cache_data(show_spinner=False, ttl=30)
def read_meta_dict_cached():
    try:
        sh = open_db()
        try:
            ws = sh.worksheet("meta")
        except Exception:
            return {}
        rows = ws.get_all_records()
        meta = {}
        for r in rows:
            k = str(r.get("key","")).strip()
            v = str(r.get("value","")).strip()
            if k:
                meta[k] = v
        return meta
    except Exception:
        return {}


def read_meta_dict_direct():
    """Fetch meta directly from Google Sheets (no cache), used for login screen."""
    try:
        sh = open_db()
        try:
            ws = sh.worksheet("meta")
        except Exception:
            return {}
        rows = ws.get_all_records()
        meta = {}
        for r in rows:
            k = str(r.get("key","")).strip()
            v = str(r.get("value","")).strip()
            if k:
                meta[k] = v
        return meta
    except Exception:
        return {}


def group_name():
    return get_meta("group_name") or st.secrets.get("sheets", {}).get("group_name", "Wainwright Paddle Team")

def payer_email_setting():
    raw = get_meta("payer_email") or st.secrets.get("sheets", {}).get("payer_email", "")
    return (raw or "").strip().lower()

def payer_monzo_username():
    raw = get_meta("monzo_username") or st.secrets.get("payments", {}).get("monzo_username")
    return normalise_monzo_username(raw) if raw else None


# ----------------- Domain logic -----------------
def compute_balances(sessions_df, regs_df, payments_df, payer_email):
    balances = {}
    emails = set(regs_df["player_email"].dropna().tolist()) | set(payments_df["player_email"].dropna().tolist())
    emails.add(payer_email)
    for e in emails: balances[e] = 0.0
    for _, s in sessions_df.iterrows():
        sid = s.get("session_id") or s.get("date")
        fee = parse_float(s.get("fee", 0.0))
        attendees = regs_df[regs_df["session_id"] == sid]["player_email"].dropna().unique().tolist()
        n = len(attendees)
        if n<=0 or fee<=0: continue
        share = fee/n
        for e in attendees: balances[e] = balances.get(e,0.0)+share
    for _, p in payments_df.iterrows():
        e = p.get("player_email"); amt = parse_float(p.get("amount",0.0))
        if not e or amt<=0: continue
        balances[e] = balances.get(e,0.0)-amt
    non_payer_total = sum(v for k,v in balances.items() if k!=payer_email)
    balances[payer_email] = -non_payer_total
    return balances

# ----------------- Pages -----------------
def page_balances(tabs, sessions, regs, pays, players):
    if st.session_state.get("flash_msg"): st.success(st.session_state.pop("flash_msg"), icon="✅")

    payer_email = payer_email_setting()
    if not payer_email:
        st.warning("Set **payer_email** in Streamlit secrets.", icon="⚙️"); return
    balances = compute_balances(sessions, regs, pays, payer_email)

    names = {r["player_email"]: r["player_name"] for _, r in players.iterrows() if r.get("player_email")}
    players_wa_map = {r["player_email"]: r.get("whatsapp","") for _, r in players.iterrows() if r.get("player_email")}

    entries = [{"Player": names.get(e, e), "Email": e, "Balance": round(float(amt),2)} for e,amt in balances.items()]
    df = pd.DataFrame(entries).sort_values(by="Balance", ascending=False).reset_index(drop=True)

    st.subheader("Current balances")
    st.caption("Positive means the player **owes** the payer. Negative means they have **credit**.")
    st.dataframe(df[["Player","Email","Balance"]].style.format({"Balance":"£{:.2f}"}), use_container_width=True, hide_index=True)

    me = signed_in_email()
    monzo_user = payer_monzo_username()

    # --- Log payment (self only) ---
    st.divider(); st.subheader("Log a payment (you only)")
    if me == payer_email:
        st.info("You're the payer. Players log their own payments; you can't log on behalf of others.", icon="ℹ️")
    else:
        my_name = names.get(me, "")

        # Replace tabs with a persistent, horizontal radio (preselect Monzo)
        pay_mode = st.radio(
            "Payment method",
            ["Pay manually, and log paid", "Pay by Monzo"],
            horizontal=True,
            index=1,
            key="pay_mode_choice",
            help="Choose how you want to pay and record it."
        )

        if pay_mode == "Pay manually, and log paid":
            with st.form("log_payment_self_manual"):
                c1, c2 = st.columns([2,1])
                with c1:
                    st.text_input("Your email", value=me, disabled=True)
                    name = st.text_input("Your name", value=my_name)
                    note = st.text_input("Note (optional)", value="")
                with c2:
                    amount = st.number_input("Amount (£)", min_value=0.0, step=1.0, format="%.2f", key="amt_manual")
                    paid_at = st.date_input("Paid on", value=date.today(), key="date_manual")
                if st.form_submit_button("Log paid", use_container_width=True):
                    if not name: st.error("Name is required.", icon="⚠️")
                    elif amount <= 0: st.error("Amount must be greater than zero.", icon="⚠️")
                    else:
                        append_row(tabs["payments"], [me, name, amount, to_iso_date(paid_at), note])
                        st.session_state["flash_msg"] = "Payment recorded and balances updated."
                        st.rerun()

        else:  # Pay by Monzo
            st.caption("Pay the payer securely via Monzo. We’ll prefill the amount and reference; then confirm below to log it.")
            c1, c2 = st.columns([2,1])
            with c1:
                st.text_input("Your email", value=me, disabled=True, key="paylink_email")
                name2 = st.text_input("Your name", value=my_name, key="paylink_name")
                note2 = st.text_input("Note (optional)", value="Padel settle-up", key="paylink_note")
            with c2:
                amount2 = st.number_input("Amount (£)", min_value=0.0, step=1.0, format="%.2f", key="amt_link")
                paid_at2 = st.date_input("Paid on", value=date.today(), key="date_link")

            if monzo_user and amount2 > 0:
                monzo_url = monzo_request_link(monzo_user, amount2, f"Padel {group_name()}")
                try: st.link_button("Pay with Monzo", monzo_url, use_container_width=True, type="secondary")
                except Exception: st.markdown(f"[Pay with Monzo]({monzo_url})")
            elif monzo_user:
                st.info("Enter an amount to enable Monzo link.", icon="ℹ️")
            else:
                st.warning("Monzo username not configured. Add `payments.monzo_username` in Streamlit **Secrets**.", icon="⚙️")

            if st.button("I've paid — Log it", use_container_width=True, type="primary"):
                if not name2: st.error("Name is required.", icon="⚠️")
                elif amount2 <= 0: st.error("Amount must be greater than zero.", icon="⚠️")
                else:
                    append_row(tabs["payments"], [me, name2, amount2, to_iso_date(paid_at2), note2])
                    st.session_state["flash_msg"] = "Payment recorded and balances updated."
                    st.rerun()

    # --- WhatsApp settle-up ---
    st.divider(); st.subheader("WhatsApp settle‑up (admin)")
    lines = [f"Hi all — settle‑up for {group_name()}:", ""]
    for _, row in df.iterrows():
        if row["Email"] == payer_email: continue
        if row["Balance"] > 0.0:
            part = f"- {row['Player']}: {currency(row['Balance'])}"
            if monzo_user:
                part += f" → {monzo_request_link(monzo_user, row['Balance'], f'Padel {group_name()}')}"
            lines.append(part)
    wa_text = "\n".join(lines) if len(lines) > 2 else "No one owes anything right now 🎉"
    st.caption("Option A — share to **your group chat** via WhatsApp composer:")
    st.caption(f"Pick your WhatsApp group (e.g. “{group_name()}”) after tapping the button.")
    share_url = f"https://wa.me/?text={quote(wa_text)}"
    try: st.link_button("Open WhatsApp (compose for group)", share_url, use_container_width=True)
    except Exception: st.markdown(f"[Open WhatsApp (compose for group)]({share_url})")

    # --- Option B: Combined message (selected players) for posting into the group ---
    owe_df = df[(df["Balance"] > 0) & (df["Email"] != payer_email)].copy()
    owe_df["WhatsApp"] = owe_df["Email"].map(players_wa_map).fillna("")
    owe_df["wa_clean"] = owe_df["WhatsApp"].map(lambda s: re.sub(r'\D', '', s or ''))

    st.caption("Option B — build a **combined message** for the group from selected players:")
    options = []
    for _, r in owe_df.iterrows():
        options.append((r["Player"], r["Balance"]))

    if options:
        display = [f"{p} — {currency(amt)}" for p,amt in options]
        selected = st.multiselect("Include players", display, default=display)
        if selected:
            lookup = {f"{p} — {currency(amt)}": (p,amt) for p,amt in options}
            lines_sel = [f"Hi all — settle‑up for {group_name()}:", ""]
            for disp in selected:
                p, amt = lookup[disp]
                if monzo_user:
                    lines_sel.append(f"- {p}: {currency(amt)} → {monzo_request_link(monzo_user, amt, f'Padel {group_name()}')}")
                else:
                    lines_sel.append(f"- {p}: {currency(amt)}")
            msg = "\n".join(lines_sel)
            share_url_sel = f"https://wa.me/?text={quote(msg)}"
            try: st.link_button("Open WhatsApp (group message)", share_url_sel, use_container_width=True)
            except Exception: st.markdown(f"[Open WhatsApp (group message)]({share_url_sel})")
        else:
            st.info("Select at least one player to generate a combined message.", icon="ℹ️")
    else:
        st.info("No outstanding balances to message about.", icon="ℹ️")

    st.caption("On desktop this opens WhatsApp Web; on mobile it opens the WhatsApp app.")

def page_register(tabs, sessions, regs, pays, players):
    st.subheader("Register your game sessions")
    if sessions.empty:
        st.info("No sessions yet. Ask the payer/admin to add one on the Sessions page."); return

    latest_first = sessions.sort_values("date", ascending=False)
    email = signed_in_email()
    existing = players[players["player_email"].str.lower() == email]
    name_to_use = (existing["player_name"].iloc[0] if not existing.empty else _derived_name_from_email(email))

    # Session dropdown formatted as dd/mm/yyyy, but values are session_ids
    options = latest_first["session_id"].tolist()
    sid = st.selectbox("Which session?", options, index=0, format_func=fmt_uk_date)

    if st.button("I'm Playing / I Played", use_container_width=True, type="primary"):
        already = regs[(regs["session_id"] == sid) & (regs["player_email"].str.lower() == email)]
        if not already.empty:
            st.error("You're already registered for that session.", icon="⚠️")
        else:
            append_row(tabs["registrations"], [sid, email, name_to_use, now_iso()])
            if existing.empty:
                append_row(tabs["players"], [email, name_to_use, "", "", "TRUE", now_iso()])
            st.session_state["flash_msg"] = "Registered."
            st.rerun()

    st.divider(); st.subheader("Who else is playing / played?")
    regs_for_selected = regs[regs["session_id"] == sid].copy()

    # Registered column: dd/mm/yyyy HH:MM (drop any trailing Z)
    def fmt_ts_ddmm(s):
        try:
            ts = pd.to_datetime(s, errors="raise")
            if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                py = ts.to_pydatetime().replace(tzinfo=None)
            else:
                py = ts.to_pydatetime()
            return py.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(s).replace("T", " ").replace("Z", "")

    if not regs_for_selected.empty:
        regs_for_selected["Registered"] = regs_for_selected["registered_at"].map(fmt_ts_ddmm)
        regs_for_selected["Session Date"] = fmt_uk_date(sid)
        out = regs_for_selected.rename(columns={"player_name":"Name","player_email":"Email"})
        st.dataframe(out[["Session Date","Name","Email","Registered"]], use_container_width=True, hide_index=True)

def page_sessions(tabs, sessions, regs, pays, players):
    st.subheader("Sessions (admin)")
    with st.form("add_session"):
        c1, c2, c3 = st.columns([1,1,2])
        with c1: d = st.date_input("Date (dd/mm/yyyy)", value=date.today())
        with c2: fee = st.number_input("Court fee (£)", min_value=0.0, step=1.0, format="%.2f")
        with c3: notes = st.text_input("Notes (optional)", value="")
        if st.form_submit_button("Add session", use_container_width=True):
            sid = to_iso_date(d)  # store canonical yyyy-mm-dd
            if not sessions[sessions["session_id"] == sid].empty:
                st.error("A session for this date already exists.", icon="⚠️")
            else:
                append_row(tabs["sessions"], [sid, sid, fee, notes, now_iso()])
                st.session_state["flash_msg"] = "Session added."
                st.rerun()
    if sessions.empty: return
    st.divider(); st.subheader("Session list")
    sess = sessions.sort_values("date", ascending=False).copy()
    rows = []
    for _, s in sess.iterrows():
        sid = s["session_id"]; fee = parse_float(s["fee"],0.0)
        attendees = regs[regs["session_id"] == sid]["player_email"].nunique()
        share = (fee/attendees) if attendees>0 else 0.0
        rows.append({
            "Session Date": fmt_uk_date(sid),
            "Fee": fee,
            "Attendees": attendees,
            "Per-person share": share,
            "Notes": s.get("notes",""),
        })
    view = pd.DataFrame(rows)
    if not view.empty:
        st.dataframe(view.style.format({"Fee":"£{:.2f}","Per-person share":"£{:.2f}"}), use_container_width=True, hide_index=True)

def page_profile(tabs, sessions, regs, pays, players):
    email = signed_in_email()
    existing = players[players["player_email"].str.lower() == email]
    name_default = existing["player_name"].iloc[0] if not existing.empty else ""
    wa_default = existing["whatsapp"].iloc[0] if not existing.empty else ""
    payout_existing = existing["payout_link"].iloc[0] if not existing.empty else ""  # preserved silently

    if "profile_name" not in st.session_state: st.session_state["profile_name"] = name_default
    if "profile_whatsapp" not in st.session_state: st.session_state["profile_whatsapp"] = wa_default

    st.subheader("Profile")
    with st.form("profile"):
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Your name", key="profile_name")
            st.text_input("Your WhatsApp number (optional)", key="profile_whatsapp", help="Just digits or +44…")
        with c2:
            st.write(f"Your email: **{email}**")
            st.caption("Tip: add your WhatsApp number to make one‑tap settle‑ups easy.")
        if st.form_submit_button("Save profile", use_container_width=True):
            name = st.session_state["profile_name"].strip()
            whatsapp = st.session_state["profile_whatsapp"].strip()
            if not name:
                st.error("Name is required.", icon="⚠️")
            else:
                ws = tabs["players"]
                if not existing.empty:
                    rownum = int(existing.index[0]) + 2
                    # keep existing payout_link unchanged, set active TRUE
                    ws.update(f"B{rownum}:E{rownum}", [[name, whatsapp, payout_existing, "TRUE"]])
                    st.cache_data.clear()
                else:
                    # create with empty payout_link
                    ws.append_row([email, name, whatsapp, "", "TRUE", now_iso()], value_input_option="USER_ENTERED")
                    st.cache_data.clear()
                st.session_state["flash_msg"] = "Profile saved."
                st.rerun()

# ----------------- App shell -----------------
if not signed_in_email():
    login_page()

# Header row: title on left, chip on right (top-right alignment)
header_left, header_right = st.columns([5,2])
with header_left:
    st.markdown(f"<h1 style='margin-bottom:0'>🎾 {group_name()}</h1>", unsafe_allow_html=True)
    st.caption("Fair splits for weekly court fees.")
with header_right:
    st.markdown(f"<div class='top-right'><span class='chip'>Logged in as {signed_in_email()}</span></div>", unsafe_allow_html=True)

if "page" not in st.session_state:
    st.session_state["page"] = "Payments"

# 5 equal-width pills including Logout
pages = ["Payments", "Register", "Sessions", "Profile"]
nav_cols = st.columns([1,1,1,1,1])

# Left 4: pages
for i, p in enumerate(pages):
    is_active = (st.session_state["page"] == p)
    with nav_cols[i]:
        if st.button(p, key=f"nav_{p}", use_container_width=True, type=("primary" if is_active else "secondary")):
            if not is_active:
                st.session_state["page"] = p
                st.rerun()

# Rightmost: Logout pill (styled like others, not a page)
with nav_cols[-1]:
    if st.button("Log out", key="logout_btn", use_container_width=True, type="secondary"):
        logout()

tabs = ensure_all_tabs()
sessions, regs, pays, players = fetch_all_tables_as_dfs()

page = st.session_state["page"]
if page in ("Payments", "Balances"):
    page_balances(tabs, sessions, regs, pays, players)
elif page == "Register":
    page_register(tabs, sessions, regs, pays, players)
elif page == "Sessions":
    page_sessions(tabs, sessions, regs, pays, players)
else:
    page_profile(tabs, sessions, regs, pays, players)

st.markdown("---")
st.markdown("<div style='text-align:center; opacity:0.6'>Made with ❤️ for fair splits.</div>", unsafe_allow_html=True)
