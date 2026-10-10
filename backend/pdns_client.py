import os
import requests
from typing import List, Dict, Any, Optional

class PowerDNSClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or os.getenv("POWERDNS_ADMIN_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("POWERDNS_ADMIN_API_KEY", "")

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_api_prefix(self) -> str:
        if self.base_url.endswith("/api/v1"):
            return self.base_url
        return f"{self.base_url}/api/v1"

    def list_zones(self) -> List[Dict[str, Any]]:
        url = f"{self._get_api_prefix()}/servers/localhost/zones"
        resp = requests.get(url, headers=self._headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json()
        resp.raise_for_status()
        return []

    def get_zone(self, domain: str) -> Optional[Dict[str, Any]]:
        canonical = domain.strip().rstrip(".") + "."
        url = f"{self._get_api_prefix()}/servers/localhost/zones/{canonical}"
        resp = requests.get(url, headers=self._headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return None

    def create_zone(self, domain: str, nameservers: List[str]) -> Dict[str, Any]:
        canonical = domain.strip().rstrip(".") + "."
        clean_ns = [ns.strip().rstrip(".") + "." for ns in nameservers if ns.strip()]

        url = f"{self._get_api_prefix()}/servers/localhost/zones"
        payload = {
            "name": canonical,
            "kind": "Master",
            "masters": [],
            "nameservers": clean_ns
        }

        resp = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        if resp.status_code in (200, 201):
            return resp.json() if resp.text else {"name": canonical, "status": "created"}
        
        # If already exists, return existing or raise
        if resp.status_code == 422 and "already exists" in resp.text.lower():
            existing = self.get_zone(canonical)
            if existing:
                return existing

        resp.raise_for_status()
        return {"name": canonical, "status": "created"}

    def patch_rrsets(self, domain: str, rrsets: List[Dict[str, Any]]) -> Dict[str, Any]:
        canonical = domain.strip().rstrip(".") + "."
        url = f"{self._get_api_prefix()}/servers/localhost/zones/{canonical}"

        # Ensure all RRSet names end with dot and TXT contents are double quoted
        formatted_rrsets = []
        for rset in rrsets:
            r_name = rset["name"].strip().rstrip(".") + "."
            r_type = rset["type"].upper()
            r_ttl = rset.get("ttl", 3600)
            changetype = rset.get("changetype", "REPLACE")

            records = []
            for rec in rset.get("records", []):
                content = str(rec.get("content", "")).strip()
                if r_type == "TXT":
                    if not (content.startswith('"') and content.endswith('"')):
                        content = f'"{content}"'
                elif r_type in ("CNAME", "MX", "NS", "PTR"):
                    if r_type == "MX":
                        parts = content.split(None, 1)
                        if len(parts) == 2 and not parts[1].endswith("."):
                            content = f"{parts[0]} {parts[1]}."
                    else:
                        if not content.endswith("."):
                            content = f"{content}."

                records.append({
                    "content": content,
                    "disabled": rec.get("disabled", False)
                })

            formatted_rrsets.append({
                "name": r_name,
                "type": r_type,
                "ttl": r_ttl,
                "changetype": changetype,
                "records": records
            })

        payload = {"rrsets": formatted_rrsets}
        resp = requests.patch(url, json=payload, headers=self._headers(), timeout=15)
        if resp.status_code in (200, 204):
            return {"status": "ok", "patched_rrsets": len(formatted_rrsets)}
        resp.raise_for_status()
        return {"status": "ok"}

    def check_connection(self) -> Dict[str, Any]:
        if not self.base_url:
            return {"connected": False, "error": "POWERDNS_ADMIN_BASE_URL is not set"}
        try:
            url = f"{self._get_api_prefix()}/servers/localhost"
            resp = requests.get(url, headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "connected": True,
                    "version": data.get("version", "unknown"),
                    "daemon_type": data.get("daemon_type", "authoritative")
                }
            return {"connected": False, "status_code": resp.status_code, "error": resp.text[:200]}
        except Exception as e:
            return {"connected": False, "error": str(e)}
