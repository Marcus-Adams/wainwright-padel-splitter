
# Padel Splitter — Wainwright Paddle Team (v3)

Ready-to-run Streamlit app for **Wainwright Paddle Team**. Tracks weekly padel court fees, splits costs by attendees, and keeps rolling balances against a single payer.

## Prefilled for you
- **payer_email**: `xxx@xxx.com`
- **group_name**: `xxx Paddle Team`
- **Monzo**: you can paste **either** just the handle  **or** a full link like `https://monzo.me/xxx` — the app normalises it automatically.

---

## Streamlit secrets (paste this then tweak your Sheet ID)
```toml
[gcp_service_account]
# …your service account JSON fields…

[sheets]
db_key = "YOUR_SPREADSHEET_ID"
payer_email = "xxx@xxx.com"
group_name = "xxx Paddle Team"

[auth]
join_code = "yyyy"                 # share privately with the team

[payments]
monzo_username = "monzo.me/xxxx"  # full link or just 'xxx' both work
```

## Monzo normalisation
The app converts any of these to `xxx`:
- `xxx`
- `monzo.me/xxx`
- `https://monzo.me/xxx?d=Hello`
- `www.monzo.me/xxx/`

## Deploy
1) Create a Google Sheet with tabs: `sessions`, `registrations`, `payments`, `players`, `meta` (leave empty).  
2) Create a Google **Service Account** and share the sheet with its **client_email** (Editor).  
3) Put `app.py` + `requirements.txt` in a GitHub repo.  
4) Deploy on Streamlit Community Cloud and paste the **Secrets** (above).

## Use
- **Sessions** → add date & fee.  
- **Register** → players sign in (email + join code) and tap **I played**.  
- **Players / Profile** → everyone adds name, WhatsApp, (optional) payment link.  
- **Balances** → shows who owes what, provides **Monzo request links**, and generates a **WhatsApp settle‑up message**.

---

© 2025 Wainwright Paddle Team
