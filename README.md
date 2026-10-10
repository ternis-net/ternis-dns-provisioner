# Ternis DNS Zone Provisioner

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![PowerDNS](https://img.shields.io/badge/DNS-PowerDNS--Admin-orange.svg)](https://www.powerdns.com/)
[![Hetzner Cloud](https://img.shields.io/badge/Secondary%20DNS-Hetzner%20Cloud-red.svg)](https://www.hetzner.com/)

**Ternis DNS Zone Provisioner** is an automated DNS provisioning tool and REST API that links **PowerDNS-Admin** (as the primary authoritative master) with **Hetzner Cloud DNS** (as authoritative secondary/slave nameservers) and automatically seeds complete mail gateway configurations (MX, SPF, 2048-bit DKIM, DMARC, Autoconfig, Autodiscover, and dynamic Postmaster routing).

It is designed to work in synergy with **[Ternis Mail Manager](https://github.com/ternis-net/ternis-mail-manager)**.

---

## Key Features

* ⚡ **Master & Secondary Provisioning in One Click:**
  * Creates primary Master Zone in PowerDNS via PowerDNS-Admin API.
  * Adds both Main Nameservers (e.g. `ns1.ternis.net.`) and Hetzner Secondary Nameservers (`ns1.first-ns.de.`, `robotns2.second-ns.de.`, `robotns3.second-ns.com.`).
  * Creates Secondary Zone in Hetzner Cloud API (`POST /v1/zones`, `mode: secondary`, `primary_nameservers`) with optional TSIG authentication.
* 🌐 **Smart Subdomain vs. Apex Procedures:**
  * **Apex Domains:** Creates full Master zone in PowerDNS + Secondary zone in Hetzner.
  * **Subdomains (in existing parent zone):** Injects subdomain records directly into the existing PowerDNS parent zone, avoiding redundant Hetzner secondary zones and replicating instantly via AXFR.
  * **Delegated Subdomain Zones:** Supports dedicated child master zones with NS delegation if preferred.
* ✉️ **Automated Mail Server Seeding:**
  * **MX**: `10 <mail_host>.`
  * **SPF (TXT)**: `v=spf1 ip4:<mail_ip> mx -all`
  * **DKIM (TXT)**: Generates 2048-bit RSA key pair via local `rspamadm dkim_keygen` (or cryptography library) and sets `mail._domainkey`.
  * **DMARC (TXT)**: `v=DMARC1; p=quarantine; sp=quarantine; pct=100`
  * **Autoconfig & Autodiscover (CNAME)**: Configures Thunderbird and Outlook autodiscovery.
  * **Postmaster Routing (TXT)**: Seeds optional `_postmaster` TXT record for zero-credential login code dispatching.
* 🔗 **Direct Deep-Link to Ternis Mail Manager:**
  * Once a zone is provisioned, generates a pre-filled direct link to **Ternis Mail Manager** (`https://one.mx.ternis.net/app-accounts/?domain=<domain>`) to immediately provision application accounts (Nextcloud, WordPress, Docker, GitLab).
* 🎨 **Minimalist Flat UI with Dark/Light Mode:**
  * Pure grayscale design, zero emojis, pure inline SVGs, zero `translateY()`, zero box-shadows.

---

## Hetzner Secondary Nameservers

The provisioner automatically includes Hetzner's secondary nameservers:

| Nameserver | IPv4 Address | IPv6 Address |
| :--- | :--- | :--- |
| `ns1.first-ns.de.` | `213.239.242.238` | `2a01:4f8:0:a101::a:1` |
| `robotns2.second-ns.de.` | `213.133.100.103` | `2a01:4f8:0:1::5ddc:2` |
| `robotns3.second-ns.com.` | `193.47.99.3` | `2001:67c:192c::add:a3` |

---

## Architecture & Workflow

```text
                  ┌─────────────────────────────────────────┐
                  │       Postmaster enters Domain          │
                  │        (Web UI or REST API)             │
                  └────────────────────┬────────────────────┘
                                       │
                        Inspect: Apex vs Subdomain?
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 │                                           │
          [Apex Domain]                           [Subdomain in Parent]
                 │                                           │
  1. POST /api/v1/servers/localhost/zones                    │
     - Master Zone in PowerDNS                               │
     - NS: Main NS + Hetzner NS                              │
                 │                                           │
  2. POST https://api.hetzner.cloud/v1/zones                 │
     - mode: "secondary"                                     │
     - primary_nameservers: [{address, port}]                │
                 │                                           │
                 └─────────────────────┬─────────────────────┘
                                       │
                                       ▼
                     3. Generate 2048-bit DKIM Key
                                       │
                                       ▼
                     4. Seed Mail Records in PowerDNS:
                        - MX, SPF, DKIM, DMARC
                        - autoconfig & autodiscover CNAME
                        - _postmaster TXT
                                       │
                                       ▼
                    5. AXFR Zone Transfer to Hetzner
                                       │
                                       ▼
                [Open in Ternis Mail Manager & Create Accounts]
```

---

## Configuration (`.env`)

```env
# PowerDNS-Admin API Configuration
POWERDNS_ADMIN_BASE_URL=https://pdns.example.com
POWERDNS_ADMIN_API_KEY=your_powerdns_admin_api_key_here

# Hetzner Cloud DNS API Configuration
HETZNER_API_KEY=your_hetzner_api_token_here
HETZNER_API_BASE_URL=https://api.hetzner.cloud/v1

# Primary Nameserver (The Master server IP that Hetzner secondary will AXFR from)
# PRIMARY_IP: IP address of primary DNS server (falls back to the IP resolved from POWERDNS_ADMIN_BASE_URL if left blank)
PRIMARY_IP=134.255.225.220
PRIMARY_PORT=53

# tsig_key / tsig_algorithm: Optional, but required if your primary server enforces TSIG authentication for AXFR/NOTIFY.
TSIG_KEY=
TSIG_ALGORITHM=hmac-sha256

# Main Authoritative Nameservers (your primary NS list, comma-separated)
MAIN_NAMESERVERS=ns1.ternis.net.

# Default Mail Server Settings (for auto-configuring mail records)
MAIL_HOST=one.mx.ternis.net
MAIL_IP=134.255.225.220
MAIL_SPF="v=spf1 ip4:134.255.225.220 mx -all"
MAIL_DMARC="v=DMARC1; p=quarantine; sp=quarantine; pct=100"

# Direct deep link to Ternis Mail Manager
TERNIS_MAIL_MANAGER_URL=https://one.mx.ternis.net/app-accounts/

# API Server Port
PORT=8089
```

---

## REST API Endpoints

* `GET /api/v1/health` — Service health & API connectivity diagnostics (PowerDNS & Hetzner).
* `GET /api/v1/config` — Retrieve pre-configured default settings and nameserver lists.
* `POST /api/v1/domain/inspect` — Analyze domain hierarchy (apex vs subdomain) and detect existing zones.
* `POST /api/v1/provision` — Provision zone in PowerDNS, secondary zone in Hetzner Cloud, and seed mail records.
* `GET /api/v1/zones` — List all active zones in PowerDNS and Hetzner Cloud.

---

## Deployment & Running

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Systemd Service
```bash
sudo cp deployment/ternis-dns-provisioner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ternis-dns-provisioner
```

### 3. Nginx Reverse Proxy
Add to your Nginx configuration:
```nginx
location /dns-provisioner/ {
    alias /var/www/one.mx.ternis.net/dns-provisioner/;
    index index.html;
    try_files $uri $uri/ /dns-provisioner/index.html;
}

location /dns-api/ {
    proxy_pass http://127.0.0.1:8089/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

---

## Open Source & Licensing

Released under the **[MIT License](LICENSE)**.

Developed by **Ternis** ([ternis.dev](https://ternis.dev) / [ternis.org](https://ternis.org) / [ternis.net](https://ternis.net)).
Repositories hosted at:
* **GitHub:** [github.com/ternis-net/ternis-dns-provisioner](https://github.com/ternis-net/ternis-dns-provisioner)
* **Codeberg:** [codeberg.org/ternis/ternis-dns-provisioner](https://codeberg.org/ternis/ternis-dns-provisioner)
