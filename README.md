# 🛰️ Magnetar Sentinel

[![CI/CD Pipeline](https://github.com/scherenhaenden/magnetar-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/scherenhaenden/magnetar-sentinel/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://github.com/scherenhaenden/magnetar-sentinel)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.14-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT%20%2F%20Proprietary-lightgrey.svg)](LICENSE)

> **Real-time multi-domain traffic intelligence & automated firewall defense engine.**  
> Zero client-side JavaScript tracking · AdBlocker immune · Privacy-first · Native Linux firewall (`nftables` / `fail2ban`) integration.

---

## 🌟 Key Features

* **🎯 Multi-Domain Intelligence:** Real-time log discovery across multiple sites (`example.com`, `blog.example.com`, `docs.example.com`, and global `🌐 All Domains` view) with interactive filter chips and multi-select support (`Ctrl+Click` / `Shift+Click`).
* **🔍 Granular Drilldown (*"De dónde → Hacia dónde"*):** Click on any country or referrer to reveal the exact destination articles, landing pages, traffic percentages, and origin breakdown.
* **🔗 3-Way Referrer Inspector:** Switch seamlessly between **🌐 Dominios** (Host-level aggregates), **🔗 URLs Completas** (full paths, UTM campaigns, forum subreddits), and **🔍 Keywords / Búsquedas** (automatically extracted search terms).
* **🛡️ Fail2ban & Firewall Active Shield (`/security`):**
  * **Production (`nginx-critical-probes`):** 1-strike instant 14-day ban on ports 80/443 for probes targeting `/.env*`, `/.git*`, `/wp-admin*`, `*.php`, `/phpmyadmin`, shells, and directory traversal attempts.
  * **Non-Prod (`nginx-dev-tolerant`):** Relaxed threshold (`maxretry = 10`, `bantime = 1h`) with immunity for standard 400/404 development errors.
  * **Live Shield Dashboard:** Real-time table of all blocked IPs, active jail statuses, 1-click **Unban**, and instant **Manual Ban** controls.
* **📊 Dedicated Full-Screen Reports:**
  * 📰 **`/pages`:** Full inventory of all visited pages, unique readers, human hits, bot hits, and top traffic source.
  * 🔗 **`/referrers`:** Side-by-side acquisition channel reports with interactive destination inspectors.
  * 🌍 **`/countries`:** Geographic distribution (GeoIP2) with per-country audience preferences.
  * 👥 **`/visitors`:** Visitor log with session counters, human vs. bot filters, and live **`🚫 BANNED`** tags.
* **🗺️ Behavioral Analytics:**
  * 🗺️ **`/journey`:** Top 20 user navigation sequences and pure SVG Sankey flow transitions.
  * 🔄 **`/retention`:** Weekly IP cohort retention matrix.
  * 👥 **`/cohorts`:** Acquisition cohorts grouped by first-seen week.
  * 🎯 **`/funnels`:** Visual step conversion funnels and interactive funnel builder.
  * ⚡ **`/events`:** Real-time stream of classified events (`article_read`, `home_visit`, `attack_probe`, `bot_probe`, `404_error`).
* **⚡ Incremental Ingestion Engine:** High-performance log ingestion via local filesystem or SSH with automatic deduplication, sessionization (30 min window), and APScheduler background tasks.
* **🏛️ Modular Architecture:** Clean Flask Blueprints (`dashboard`, `security`, `reports`, `analytics`, `settings`, `api`) under 70 lines in `app.py`.

---

## 📸 Architecture Overview

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

## ⚡ Quick Start

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/scherenhaenden/magnetar-sentinel.git
cd magnetar-sentinel

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
```

### 2. Run Test Suite
```bash
pytest tests/ -v
```

### 3. Configure Securely & Start Application
```bash
# Create secure config outside web directory
sudo mkdir -p /etc/magnetar
sudo cp config.example.env /etc/magnetar/magnetar.env
sudo chmod 600 /etc/magnetar/magnetar.env

# Edit with your production password & settings
sudo nano /etc/magnetar/magnetar.env

# Start app
python app.py
```
Open **`http://localhost:5050`** in your browser.

---

## 🔒 Secure Production Configuration

> [!IMPORTANT]
> **Security Rule:** Never place secrets, passwords, or production keys inside `.env` files in the repository or web-accessible root directory.

Configure Magnetar Sentinel via system environment variables, systemd, or `/etc/magnetar/magnetar.env` (restricted permissions `chmod 600`):

| Variable | Default (Fallback) | Description |
| :--- | :--- | :--- |
| `MS_CONFIG_FILE` | `/etc/magnetar/magnetar.env` | Path to secure external configuration file |
| `MS_DASHBOARD_USER` | `admin` | HTTP Basic Auth username |
| `MS_DASHBOARD_PASS` | `ChangeMeImmediately!` | HTTP Basic Auth password (set in secure config) |
| `MS_PORT` | `5050` | Port to listen on |
| `MS_DATABASE_URL` | `sqlite:///magnetar.db` | Database URL (SQLite, PostgreSQL, MySQL/MariaDB) |
| `MS_SSH_HOST` | `127.0.0.1` | Remote log server hostname / IP |
| `MS_SSH_USER` | `admin` | Remote SSH user |
| `MS_SSH_KEY` | `~/.ssh/id_rsa` | Private SSH key path |
| `MS_LOG_DIR` | `/var/log/nginx` | Primary Nginx log directory |
| `MS_GEOIP_DB` | `/usr/share/GeoIP/GeoLite2-City.mmdb` | Path to MaxMind GeoIP2 database |
| `MS_DAYS` | `7` | Default aggregation window (in days) |

---

## 📁 Modular Project Structure

```
magnetar-sentinel/
├── app.py                      # Flask Application Entrypoint (~60 lines)
├── requirements.txt            # Python dependencies
├── config.example.env          # Template for /etc/magnetar/magnetar.env
├── README.md                   # Project overview & quickstart
├── DOCS.md                     # Comprehensive technical documentation & API guide
├── .github/workflows/ci.yml    # CI/CD pipeline (testing & release artifact packaging)
├── magnetar/
│   ├── __init__.py             # Package init & __version__ = "0.3.0"
│   ├── config.py               # Secure external environment configuration loader
│   ├── auth.py                 # Security decorators & HTTP Basic Auth
│   ├── context_processors.py   # Domain filter context injection
│   ├── db.py                   # SQLAlchemy 2.0 Engine & SessionFactory
│   ├── models.py               # Declarative models (Hit, Session, Visitor, Event, Funnel)
│   ├── log_parser.py           # Nginx regex parser & bot detector
│   ├── sync.py                 # Multi-domain incremental log sync engine
│   ├── aggregator.py           # Traffic aggregator & search query extractor
│   ├── scheduler.py            # APScheduler background sync manager
│   ├── security.py             # Fail2ban / nftables shield integration
│   └── blueprints/
│       ├── dashboard.py        # / and /dashboard routes
│       ├── security.py         # /security live firewall & ban inspector
│       ├── reports.py          # /pages, /referrers, /countries, /visitors
│       ├── analytics.py        # /journey, /retention, /cohorts, /funnels, /events
│       ├── settings.py         # /settings view & database inspector
│       └── api.py              # REST & AJAX endpoints (/api/*)
├── templates/                  # Dark-themed responsive Jinja2 templates (zero external assets)
└── tests/                      # 30 unit and integration tests (100% passing)
```

---

## 🛡️ Production Deployment (Systemd & Gunicorn)

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

Restart and check status:
```bash
sudo systemctl daemon-reload
sudo systemctl restart magnetar-sentinel.service
sudo systemctl status magnetar-sentinel.service
```

---

## 📜 Documentation

For full API endpoint documentation, database schema details, and advanced queries, see [**`DOCS.md`**](DOCS.md).

---

## 📄 License

MIT License. Open-source traffic intelligence & firewall defense suite.
