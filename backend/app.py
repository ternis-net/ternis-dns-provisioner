import os
import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pdns_client import PowerDNSClient
from hetzner_client import HetznerDNSClient, HETZNER_DEFAULT_NAMESERVERS
from dkim_generator import get_or_generate_dkim

import socket
from urllib.parse import urlparse

# Environment configurations
POWERDNS_ADMIN_BASE_URL = os.getenv("POWERDNS_ADMIN_BASE_URL", "")
POWERDNS_ADMIN_API_KEY = os.getenv("POWERDNS_ADMIN_API_KEY", "")
HETZNER_API_KEY = os.getenv("HETZNER_API_KEY", "") or os.getenv("HETZNER_API_TOKEN", "")

def get_primary_ip() -> str:
    """
    Returns the primary nameserver IP for Hetzner secondary AXFR transfer.
    Falls back to resolving the host from POWERDNS_ADMIN_BASE_URL if not explicitly specified.
    """
    explicit = os.getenv("PRIMARY_IP") or os.getenv("primary_ip") or os.getenv("PRIMARY_NAMESERVER_IP")
    if explicit and explicit.strip():
        return explicit.strip()

    pdns_url = (os.getenv("POWERDNS_ADMIN_BASE_URL") or os.getenv("powerdns_admin_base_url") or "").strip()
    if pdns_url:
        try:
            parsed = urlparse(pdns_url if "://" in pdns_url else f"http://{pdns_url}")
            host = parsed.hostname
            if host:
                resolved = socket.gethostbyname(host)
                if resolved and not resolved.startswith("127."):
                    return resolved
        except Exception:
            pass

    return "134.255.225.220"

PRIMARY_NAMESERVER_IP = get_primary_ip()
PRIMARY_NAMESERVER_PORT = int(os.getenv("PRIMARY_PORT") or os.getenv("primary_port") or os.getenv("PRIMARY_NAMESERVER_PORT", "53"))
PRIMARY_NAMESERVER_TSIG_KEY = os.getenv("TSIG_KEY") or os.getenv("tsig_key") or os.getenv("PRIMARY_NAMESERVER_TSIG_KEY", "")
PRIMARY_NAMESERVER_TSIG_ALGORITHM = os.getenv("TSIG_ALGORITHM") or os.getenv("tsig_algorithm") or os.getenv("PRIMARY_NAMESERVER_TSIG_ALGORITHM", "hmac-sha256")

MAIN_NAMESERVERS = [ns.strip() for ns in (os.getenv("MAIN_NAMESERVERS") or os.getenv("main_nameservers") or "ns1.ternis.net.").split(",") if ns.strip()]
HETZNER_NAMESERVERS = [ns["name"] for ns in HETZNER_DEFAULT_NAMESERVERS]

MAIL_HOST = os.getenv("MAIL_HOST", "one.mx.ternis.net")
MAIL_IP = os.getenv("MAIL_IP", "134.255.225.220")
MAIL_SPF = os.getenv("MAIL_SPF", f"v=spf1 ip4:{MAIL_IP} mx -all")
MAIL_DMARC = os.getenv("MAIL_DMARC", "v=DMARC1; p=quarantine; sp=quarantine; pct=100")

TERNIS_MAIL_MANAGER_URL = os.getenv("TERNIS_MAIL_MANAGER_URL", "https://one.mx.ternis.net/app-accounts/")

app = FastAPI(
    title="Ternis DNS Zone Provisioner",
    description="Automated DNS zone creation via PowerDNS-Admin and Hetzner Cloud Secondary DNS, with pre-configured mail server records.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pdns = PowerDNSClient(POWERDNS_ADMIN_BASE_URL, POWERDNS_ADMIN_API_KEY)
hetzner = HetznerDNSClient(HETZNER_API_KEY)

# --- Models ---
class InspectRequest(BaseModel):
    domain: str = Field(..., example="example.com")

class ProvisionRequest(BaseModel):
    domain: str = Field(..., example="example.com")
    mode: str = Field("auto", description="'auto', 'apex', 'subdomain_parent', or 'subdomain_dedicated'")
    main_nameservers: Optional[List[str]] = None
    hetzner_nameservers: Optional[List[str]] = None
    primary_ip: Optional[str] = None
    primary_port: Optional[int] = None
    tsig_key: Optional[str] = None
    tsig_algorithm: Optional[str] = None
    mail_host: Optional[str] = None
    mail_ip: Optional[str] = None
    postmaster_email: Optional[str] = None
    include_mail_records: bool = True

def split_domain(domain: str) -> Dict[str, Any]:
    clean = domain.strip().lower().rstrip(".")
    parts = clean.split(".")
    if len(parts) <= 2:
        return {
            "domain": clean,
            "is_subdomain": False,
            "apex_domain": clean,
            "parent_domain": None,
            "subdomain_prefix": None
        }
    else:
        # e.g. cloud.example.com -> parent: example.com, prefix: cloud
        parent = ".".join(parts[1:])
        prefix = parts[0]
        return {
            "domain": clean,
            "is_subdomain": True,
            "apex_domain": ".".join(parts[-2:]),
            "parent_domain": parent,
            "subdomain_prefix": prefix
        }

# --- Routes ---

@app.get("/api/v1/health")
def health_check():
    pdns_status = pdns.check_connection()
    hetzner_status = hetzner.check_connection()
    return {
        "status": "ok",
        "service": "ternis-dns-provisioner",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "powerdns": pdns_status,
        "hetzner": hetzner_status,
        "configured": {
            "powerdns_configured": bool(pdns.base_url and pdns.api_key),
            "hetzner_configured": bool(hetzner.api_key),
            "mail_host": MAIL_HOST,
            "mail_ip": MAIL_IP,
            "primary_ip": PRIMARY_NAMESERVER_IP,
            "mail_manager_url": TERNIS_MAIL_MANAGER_URL
        }
    }

@app.get("/api/v1/config")
def get_config():
    return {
        "main_nameservers": MAIN_NAMESERVERS,
        "hetzner_nameservers": HETZNER_DEFAULT_NAMESERVERS,
        "primary_nameserver_ip": PRIMARY_NAMESERVER_IP,
        "primary_nameserver_port": PRIMARY_NAMESERVER_PORT,
        "primary_nameserver_tsig_key": PRIMARY_NAMESERVER_TSIG_KEY,
        "primary_nameserver_tsig_algorithm": PRIMARY_NAMESERVER_TSIG_ALGORITHM,
        "mail_host": MAIL_HOST,
        "mail_ip": MAIL_IP,
        "mail_spf": MAIL_SPF,
        "mail_dmarc": MAIL_DMARC,
        "mail_manager_url": TERNIS_MAIL_MANAGER_URL
    }

@app.post("/api/v1/domain/inspect")
def inspect_domain(req: InspectRequest):
    clean = req.domain.strip().lower().rstrip(".")
    if not clean or "." not in clean:
        raise HTTPException(status_code=400, detail="Invalid domain name format.")

    dom_info = split_domain(clean)

    pdns_exists = False
    parent_pdns_exists = False
    try:
        zone = pdns.get_zone(clean)
        pdns_exists = zone is not None
    except Exception:
        pass

    if dom_info["is_subdomain"] and dom_info["parent_domain"]:
        try:
            parent_zone = pdns.get_zone(dom_info["parent_domain"])
            parent_pdns_exists = parent_zone is not None
        except Exception:
            pass

    hetzner_exists = False
    try:
        hz = hetzner.find_zone_by_name(clean)
        hetzner_exists = hz is not None
    except Exception:
        pass

    recommended_mode = "apex"
    if dom_info["is_subdomain"]:
        if parent_pdns_exists:
            recommended_mode = "subdomain_parent"
        else:
            recommended_mode = "subdomain_dedicated"

    return {
        "domain_info": dom_info,
        "pdns_zone_exists": pdns_exists,
        "parent_pdns_exists": parent_pdns_exists,
        "hetzner_zone_exists": hetzner_exists,
        "recommended_mode": recommended_mode,
        "available_modes": [
            {
                "id": "apex",
                "label": "Apex Domain",
                "desc": "Creates Master Zone in PowerDNS, NS records (Main + Hetzner), Secondary Zone in Hetzner Cloud, and mail records."
            },
            {
                "id": "subdomain_parent",
                "label": "Subdomain in Parent Zone",
                "desc": f"Injects mail records for '{clean}' directly into existing parent zone '{dom_info.get('parent_domain')}'. No separate Hetzner zone needed."
            },
            {
                "id": "subdomain_dedicated",
                "label": "Dedicated Subdomain Zone",
                "desc": "Creates a distinct Master Zone in PowerDNS, delegates from parent, and sets up a secondary zone in Hetzner Cloud."
            }
        ]
    }

@app.post("/api/v1/provision")
def provision_zone(req: ProvisionRequest):
    clean_domain = req.domain.strip().lower().rstrip(".")
    if not clean_domain or "." not in clean_domain:
        raise HTTPException(status_code=400, detail="Invalid domain name format.")

    dom_info = split_domain(clean_domain)

    # Determine execution mode
    mode = req.mode
    if mode == "auto":
        if dom_info["is_subdomain"]:
            try:
                p_zone = pdns.get_zone(dom_info["parent_domain"])
                mode = "subdomain_parent" if p_zone else "subdomain_dedicated"
            except Exception:
                mode = "subdomain_dedicated"
        else:
            mode = "apex"

    main_ns = req.main_nameservers if req.main_nameservers is not None else MAIN_NAMESERVERS
    h_ns = req.hetzner_nameservers if req.hetzner_nameservers is not None else HETZNER_NAMESERVERS
    all_ns = list(dict.fromkeys(main_ns + h_ns))  # deduplicate preserving order

    primary_ip = req.primary_ip or PRIMARY_NAMESERVER_IP
    primary_port = req.primary_port or PRIMARY_NAMESERVER_PORT
    tsig_key = req.tsig_key if req.tsig_key is not None else PRIMARY_NAMESERVER_TSIG_KEY
    tsig_algo = req.tsig_algorithm or PRIMARY_NAMESERVER_TSIG_ALGORITHM

    m_host = req.mail_host or MAIL_HOST
    m_ip = req.mail_ip or MAIL_IP
    spf_val = f"v=spf1 ip4:{m_ip} mx -all"
    dmarc_val = MAIL_DMARC

    # Generate or fetch DKIM key
    dkim_txt, dkim_status = get_or_generate_dkim(clean_domain, selector="mail")

    steps: List[str] = []
    created_records: List[Dict[str, Any]] = []
    pdns_result: Dict[str, Any] = {}
    hetzner_result: Dict[str, Any] = {}

    try:
        # === CASE 1: Subdomain inside existing parent zone ===
        if mode == "subdomain_parent":
            parent = dom_info["parent_domain"]
            if not parent:
                raise HTTPException(status_code=400, detail="Parent domain not detected for subdomain.")

            steps.append(f"Targeting parent zone '{parent}' in PowerDNS")

            # Prepare subdomain mail records
            sub_canonical = f"{clean_domain}."
            rrsets = []

            if req.include_mail_records:
                # MX
                rrsets.append({
                    "name": sub_canonical,
                    "type": "MX",
                    "ttl": 3600,
                    "records": [{"content": f"10 {m_host}."}]
                })
                created_records.append({"type": "MX", "name": clean_domain, "value": f"10 {m_host}."})

                # SPF
                rrsets.append({
                    "name": sub_canonical,
                    "type": "TXT",
                    "ttl": 3600,
                    "records": [{"content": spf_val}]
                })
                created_records.append({"type": "TXT", "name": clean_domain, "value": spf_val})

                # DKIM
                rrsets.append({
                    "name": f"mail._domainkey.{sub_canonical}",
                    "type": "TXT",
                    "ttl": 3600,
                    "records": [{"content": dkim_txt}]
                })
                created_records.append({"type": "TXT", "name": f"mail._domainkey.{clean_domain}", "value": dkim_txt})

                # DMARC
                rrsets.append({
                    "name": f"_dmarc.{sub_canonical}",
                    "type": "TXT",
                    "ttl": 3600,
                    "records": [{"content": dmarc_val}]
                })
                created_records.append({"type": "TXT", "name": f"_dmarc.{clean_domain}", "value": dmarc_val})

                # Autoconfig & Autodiscover
                rrsets.append({
                    "name": f"autoconfig.{sub_canonical}",
                    "type": "CNAME",
                    "ttl": 3600,
                    "records": [{"content": f"{m_host}."}]
                })
                created_records.append({"type": "CNAME", "name": f"autoconfig.{clean_domain}", "value": f"{m_host}."})

                rrsets.append({
                    "name": f"autodiscover.{sub_canonical}",
                    "type": "CNAME",
                    "ttl": 3600,
                    "records": [{"content": f"{m_host}."}]
                })
                created_records.append({"type": "CNAME", "name": f"autodiscover.{clean_domain}", "value": f"{m_host}."})

                # Custom Postmaster
                if req.postmaster_email:
                    rrsets.append({
                        "name": f"_postmaster.{sub_canonical}",
                        "type": "TXT",
                        "ttl": 3600,
                        "records": [{"content": req.postmaster_email.strip()}]
                    })
                    created_records.append({"type": "TXT", "name": f"_postmaster.{clean_domain}", "value": req.postmaster_email.strip()})

            pdns.patch_rrsets(parent, rrsets)
            steps.append(f"Successfully injected {len(rrsets)} mail records into PowerDNS zone '{parent}'")
            steps.append(f"Zone changes will automatically propagate to Hetzner secondary nameservers via AXFR")

            pdns_result = {"parent_zone": parent, "status": "updated", "records_added": len(rrsets)}
            hetzner_result = {"status": "inherited", "message": f"Covered by existing secondary zone for '{parent}'"}

        # === CASE 2 & 3: Apex Domain OR Dedicated Subdomain Zone ===
        else:
            canonical = f"{clean_domain}."

            # 1. Create Zone in PowerDNS
            steps.append(f"Creating Master Zone '{clean_domain}' in PowerDNS with {len(all_ns)} nameservers")
            pdns_result = pdns.create_zone(clean_domain, all_ns)
            steps.append(f"PowerDNS zone initialized with NS: {', '.join(all_ns)}")

            # 2. If dedicated subdomain and parent exists, add NS delegation in parent
            if mode == "subdomain_dedicated" and dom_info.get("parent_domain"):
                parent = dom_info["parent_domain"]
                try:
                    p_zone = pdns.get_zone(parent)
                    if p_zone:
                        ns_records = [{"content": ns} for ns in all_ns]
                        pdns.patch_rrsets(parent, [{
                            "name": canonical,
                            "type": "NS",
                            "ttl": 86400,
                            "records": ns_records
                        }])
                        steps.append(f"Added NS delegation records for '{clean_domain}' into parent zone '{parent}'")
                except Exception as ex:
                    steps.append(f"Note: Could not delegate in parent zone '{parent}': {str(ex)}")

            # 3. Create Secondary Zone in Hetzner Cloud
            if hetzner.api_key:
                steps.append(f"Registering secondary zone '{clean_domain}' in Hetzner Cloud (Primary: {primary_ip}:{primary_port})")
                try:
                    hetzner_result = hetzner.create_secondary_zone(
                        domain=clean_domain,
                        primary_ip=primary_ip,
                        primary_port=primary_port,
                        tsig_key=tsig_key,
                        tsig_algorithm=tsig_algo
                    )
                    steps.append(f"Hetzner Cloud secondary zone created successfully")
                except Exception as ex:
                    hetzner_result = {"status": "error", "error": str(ex)}
                    steps.append(f"Warning: Hetzner Cloud API call failed: {str(ex)}")
            else:
                hetzner_result = {"status": "skipped", "message": "HETZNER_API_KEY is not configured"}
                steps.append("Hetzner Cloud registration skipped (no API key configured)")

            # 4. Inject Mail Records into new Zone
            if req.include_mail_records:
                rrsets = [
                    {
                        "name": canonical,
                        "type": "MX",
                        "ttl": 3600,
                        "records": [{"content": f"10 {m_host}."}]
                    },
                    {
                        "name": canonical,
                        "type": "TXT",
                        "ttl": 3600,
                        "records": [{"content": spf_val}]
                    },
                    {
                        "name": f"mail._domainkey.{canonical}",
                        "type": "TXT",
                        "ttl": 3600,
                        "records": [{"content": dkim_txt}]
                    },
                    {
                        "name": f"_dmarc.{canonical}",
                        "type": "TXT",
                        "ttl": 3600,
                        "records": [{"content": dmarc_val}]
                    },
                    {
                        "name": f"autoconfig.{canonical}",
                        "type": "CNAME",
                        "ttl": 3600,
                        "records": [{"content": f"{m_host}."}]
                    },
                    {
                        "name": f"autodiscover.{canonical}",
                        "type": "CNAME",
                        "ttl": 3600,
                        "records": [{"content": f"{m_host}."}]
                    }
                ]

                created_records = [
                    {"type": "MX", "name": "@", "value": f"10 {m_host}."},
                    {"type": "TXT", "name": "@", "value": spf_val},
                    {"type": "TXT", "name": "mail._domainkey", "value": dkim_txt},
                    {"type": "TXT", "name": "_dmarc", "value": dmarc_val},
                    {"type": "CNAME", "name": "autoconfig", "value": f"{m_host}."},
                    {"type": "CNAME", "name": "autodiscover", "value": f"{m_host}."}
                ]

                if req.postmaster_email:
                    rrsets.append({
                        "name": f"_postmaster.{canonical}",
                        "type": "TXT",
                        "ttl": 3600,
                        "records": [{"content": req.postmaster_email.strip()}]
                    })
                    created_records.append({"type": "TXT", "name": "_postmaster", "value": req.postmaster_email.strip()})

                pdns.patch_rrsets(clean_domain, rrsets)
                steps.append(f"Seeded mail server records (MX, SPF, DKIM, DMARC, Autoconfig, Autodiscover)")

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Provisioning error: {str(e)}"
        )

    mail_manager_link = f"{TERNIS_MAIL_MANAGER_URL}?domain={clean_domain}"

    return {
        "status": "success",
        "domain": clean_domain,
        "mode": mode,
        "dkim_status": dkim_status,
        "nameservers": all_ns,
        "records": created_records,
        "steps_completed": steps,
        "powerdns_result": pdns_result,
        "hetzner_result": hetzner_result,
        "mail_manager_url": mail_manager_link
    }

@app.get("/api/v1/zones")
def list_all_zones():
    zones_pdns = []
    zones_hetzner = []
    try:
        zones_pdns = pdns.list_zones()
    except Exception as e:
        zones_pdns = [{"error": str(e)}]

    try:
        zones_hetzner = hetzner.list_zones()
    except Exception as e:
        zones_hetzner = [{"error": str(e)}]

    return {
        "powerdns_zones": zones_pdns,
        "hetzner_zones": zones_hetzner
    }
