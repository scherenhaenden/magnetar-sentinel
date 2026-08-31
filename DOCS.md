# 🛰️ Magnetar Sentinel — Documentation & User Guide

**Version:** `0.3.0`  
**License:** MIT License  
**Repository:** [https://github.com/scherenhaenden/magnetar-sentinel](https://github.com/scherenhaenden/magnetar-sentinel)

---

## 1. Overview & Architecture

**Magnetar Sentinel** is a high-performance, real-time web analytics and threat defense engine designed for multi-domain hosting environments. It analyzes raw Nginx server logs, extracts rich behavioral metrics without cookies or invasive client-side scripts, and integrates natively with Linux firewalls (`nftables` / `fail2ban`) for automatic threat mitigation.

```
                  ┌──────────────────────────────────────────────┐
                  │            Incoming HTTP Traffic             │
                  └──────────────────────┬───────────────────────┘
                                         │
                                   [ Nginx Logs ]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
       [ magnetar.sync Engine ]                     [ Fail2ban / nftables ]
   - Incremental log parsing                    - nginx-critical-probes (1-strike BAN)
   - Multi-domain log discovery                 - nginx-dev-tolerant (Dev tolerance)
   - Bot vs. Human classifier                                  │
   - Session & Journey builder                                 │
                   │                                           │
                   ▼                                           ▼
          [ SQLite / DB Engine ]                     [ Live Shield API ]
                   │                                           │
                   └─────────────────────┬─────────────────────┘
                                         ▼
                            [ Flask Modular Engine ]
                   ┌───────────────────────────────────────────┐
                   │  • Dashboard & Multi-Domain Filter Chips  │
                   │  • Drilldown ("De dónde → Hacia dónde")   │
                   │  • Dedicated Reports (Pages/Ref/Geo/User) │
                   │  • Journey, Retention, Cohorts & Funnels  │
                   │  • Security Shield & IP Ban Manager       │
                   └───────────────────────────────────────────┘
```

---

## 2. Directory Structure

```
magnetar-sentinel/
├── app.py                      # Flask Application Factory (~60 lines)
├── requirements.txt            # Production dependencies
├── config.example.env          # Template for secure production configuration
├── DOCS.md                     # Comprehensive documentation
├── .github/workflows/ci.yml    # Automated CI/CD test and artifact pipeline
├── magnetar/
│   ├── __init__.py             # Package init & version
│   ├── config.py               # Central environment & secure external configuration
│   ├── auth.py                 # HTTP Basic Auth & security decorators
│   ├── context_processors.py   # Domain filter injection & stats helpers
│   ├── db.py                   # SQLAlchemy 2.0 Engine & Session factory
│   ├── models.py               # Database schema (Hit, Session, Visitor, Event, Funnel, etc.)
│   ├── log_parser.py           # Nginx access log parser & bot detection
│   ├── sync.py                 # Incremental SSH / local log synchronization engine
│   ├── aggregator.py           # Summary statistics & search keyword extraction
│   ├── scheduler.py            # Background APScheduler task manager
│   ├── security.py             # Fail2ban / nftables CLI shield integration
│   └── blueprints/
│       ├── dashboard.py        # / and /dashboard routes
│       ├── security.py         # /security shield and banned IPs view
│       ├── reports.py          # /pages, /referrers, /countries, /visitors
│       ├── analytics.py        # /journey, /retention, /cohorts, /funnels, /events
│       ├── settings.py         # /settings & DB inspector
│       └── api.py              # REST & AJAX endpoints (/api/*)
├── templates/                  # Zero-dependency responsive dark Jinja2 templates
└── tests/                      # Pytest unit & integration test suite
```

---

## 3. Installation & Local Development

### Prerequisites
* Python 3.11+
* (Optional) MaxMind GeoIP2 Country database (`GeoLite2-City.mmdb`)

### Step-by-Step Setup
```bash
# 1. Clone repository
git clone https://github.com/scherenhaenden/magnetar-sentinel.git
cd magnetar-sentinel

# 2. Create virtual environment & install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest

# 3. Create secure configuration outside web directory
sudo mkdir -p /etc/magnetar
sudo cp config.example.env /etc/magnetar/magnetar.env
sudo chmod 600 /etc/magnetar/magnetar.env

# 4. Run unit test suite
pytest tests/ -v

# 5. Start development server
python app.py
```
Open **`http://localhost:5050`** in your browser.

---

## 4. Environment Variables Reference

> [!IMPORTANT]
> **Production Security Note:** Place your credentials in `/etc/magnetar/magnetar.env` (accessible only by the service user) or systemd environment. Do NOT commit passwords to Git or `.env` inside the repository.

| Variable | Default (Fallback) | Description |
| :--- | :--- | :--- |
| `MS_CONFIG_FILE` | `/etc/magnetar/magnetar.env` | Path to secure external configuration file |
| `MS_DASHBOARD_USER` | `admin` | HTTP Basic Auth username |
| `MS_DASHBOARD_PASS` | `ChangeMeImmediately!` | HTTP Basic Auth password (set in secure config) |
| `MS_PORT` | `5050` | HTTP port for Flask/Gunicorn |
| `MS_DATABASE_URL` | `sqlite:///magnetar.db` | SQLAlchemy connection URL (SQLite/PostgreSQL/MySQL) |
| `MS_SSH_HOST` | `127.0.0.1` | Target log server IP / hostname |
| `MS_SSH_USER` | `admin` | Target SSH user for remote log parsing |
| `MS_SSH_KEY` | `~/.ssh/id_rsa` | Private SSH key path |
| `MS_LOG_DIR` | `/var/log/nginx` | Primary log directory |
| `MS_GEOIP_DB` | `/usr/share/GeoIP/GeoLite2-City.mmdb` | Path to MaxMind GeoIP2 database |
| `MS_DAYS` | `7` | Default aggregation window in days |

---

## 5. Key Features & How to Use

### 🎯 Multi-Domain Filter Chips
* At the top of every page, interactive domain chips allow filtering traffic for individual domains (`example.com`, `blog.example.com`, `docs.example.com`) or global traffic (`🌐 All Domains`).
* **Single Click:** Isolates a single domain.
* **Ctrl+Click / Shift+Click:** Combines multiple domains (e.g. `domain=example.com,blog.example.com`).

### 🔍 Drilldown Analytics ("De dónde → Hacia dónde")
* Clicking on any row in **🌍 Countries** or **🔗 External Referrers** opens an interactive drilldown breakdown:
  * **Referrer Destination:** Shows the exact target articles, pages, and percentage of visitors brought by that search engine, forum, or social channel.
  * **Country Audience:** Shows what articles readers from that country preferred and which referrers brought them.

### 🛡️ Fail2ban & Security Shield
* **Producción (`nginx-critical-probes`):**
  * Rule: **1 strike = 14-day BAN** on ports 80/443.
  * Triggers on: `/.env*`, `/.git*`, `/wp-admin*`, `*.php`, `/phpmyadmin`, shells, and directory traversal probes.
* **Non-Prod (`nginx-dev-tolerant`):**
  * Relaxed threshold (`maxretry = 10`, `bantime = 1h`) to prevent accidental bans during development and testing.
* **Security Page (`/security`):**
  * Displays active jails and all currently blocked IPs in real-time.
  * Provides 1-click **Unban** and **Manual Ban** controls.

### 📊 Dedicated Reports & Navigation
* **`/dashboard`:** KPI summary cards, draggable grid widgets, and quick action toolbar.
* **`/security`:** Live firewall shield inspector and IP ban table.
* **`/pages`:** Full inventory of all visited pages, unique readers, human hits, and top traffic source.
* **`/referrers`:** Side-by-side acquisition report (Domains, Full URLs, and Extracted Search Keywords).
* **`/countries`:** Geographic distribution of visitors and per-country content metrics.
* **`/visitors`:** Real-time visitor log with session counts, last activity, and `🚫 BANNED` tags.
* **`/journey`:** Top user navigation sequences and pure SVG Sankey-style transition diagrams.
* **`/retention`:** Weekly IP cohort retention matrix.
* **`/funnels`:** Visual step conversion funnels and interactive funnel builder.
* **`/events`:** Real-time stream of classified events (`article_read`, `home_visit`, `attack_probe`, `bot_probe`, `404_error`).
* **`/settings`:** Sync interval scheduler controls (1m, 5m, 15m, 1h, Manual) and database storage stats.

---

## 6. REST API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Public service health check (`{"status": "ok", "version": "0.3.0"}`) |
| `GET` | `/api/status` | Current sync timestamp and DB hit count |
| `GET` | `/api/security/status` | Active Fail2ban jails and list of currently banned IPs |
| `POST`| `/api/security/unban` | Unban an IP (`{"jail": "...", "ip": "..."}`) |
| `POST`| `/api/security/ban` | Ban an IP (`{"jail": "...", "ip": "..."}`) |
| `GET` | `/api/drilldown/country`| Country visitor metrics and top read articles |
| `GET` | `/api/drilldown/referrer`| Referrer target destinations and origin countries |
| `POST`| `/api/sync/now` | Trigger immediate log ingestion from Nginx logs |
| `POST`| `/api/sync/interval` | Update automated sync frequency (`{"seconds": 300}`) |
| `POST`| `/api/seed` | Generate multi-domain synthetic test dataset |

---

## 7. Production Deployment (Systemd & Gunicorn)

### Systemd Service: `/etc/systemd/system/magnetar-sentinel.service`
```ini
[Unit]
Description=Magnetar Sentinel Analytics Service
After=network.target

[Service]
User=magnetar
Group=magnetar
WorkingDirectory=/opt/magnetar-sentinel
EnvironmentFile=/etc/magnetar/magnetar.env
Environment="PATH=/opt/magnetar-sentinel/.venv/bin"
ExecStart=/opt/magnetar-sentinel/.venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:5050 \
    --timeout 120 \
    app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### Management Commands:
```bash
sudo systemctl restart magnetar-sentinel.service
sudo systemctl status magnetar-sentinel.service
sudo journalctl -u magnetar-sentinel.service -f
```
