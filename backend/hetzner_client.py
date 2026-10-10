import os
import requests
from typing import List, Dict, Any, Optional

HETZNER_DEFAULT_NAMESERVERS = [
    {
        "name": "ns1.first-ns.de.",
        "ipv4": "213.239.242.238",
        "ipv6": "2a01:4f8:0:a101::a:1"
    },
    {
        "name": "robotns2.second-ns.de.",
        "ipv4": "213.133.100.103",
        "ipv6": "2a01:4f8:0:1::5ddc:2"
    },
    {
        "name": "robotns3.second-ns.com.",
        "ipv4": "193.47.99.3",
        "ipv6": "2001:67c:192c::add:a3"
    }
]

class HetznerDNSClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("HETZNER_API_KEY", "") or os.getenv("HETZNER_API_TOKEN", "")
        self.base_url = (base_url or os.getenv("HETZNER_API_BASE_URL", "https://api.hetzner.cloud/v1")).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def create_secondary_zone(
        self,
        domain: str,
        primary_ip: str,
        primary_port: int = 53,
        tsig_key: Optional[str] = None,
        tsig_algorithm: Optional[str] = None,
        ttl: int = 86400
    ) -> Dict[str, Any]:
        clean_domain = domain.strip().rstrip(".")

        primary_entry: Dict[str, Any] = {
            "address": primary_ip.strip(),
            "port": int(primary_port)
        }
        if tsig_key and tsig_key.strip():
            primary_entry["tsig_key"] = tsig_key.strip()
            if tsig_algorithm and tsig_algorithm.strip():
                primary_entry["tsig_algorithm"] = tsig_algorithm.strip()

        payload = {
            "name": clean_domain,
            "mode": "secondary",
            "primary_nameservers": [primary_entry],
            "ttl": ttl
        }

        url = f"{self.base_url}/zones"
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=15)

        if resp.status_code in (200, 201):
            return resp.json()

        # Handle zone already exists
        if resp.status_code in (409, 422):
            existing = self.find_zone_by_name(clean_domain)
            if existing:
                return {
                    "zone": existing,
                    "status": "already_exists",
                    "message": f"Secondary zone for '{clean_domain}' already exists in Hetzner Cloud."
                }

        resp.raise_for_status()
        return resp.json()

    def list_zones(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/zones"
        resp = requests.get(url, headers=self._headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json().get("zones", [])
        resp.raise_for_status()
        return []

    def find_zone_by_name(self, domain: str) -> Optional[Dict[str, Any]]:
        clean_domain = domain.strip().rstrip(".").lower()
        try:
            url = f"{self.base_url}/zones?name={clean_domain}"
            resp = requests.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                zones = resp.json().get("zones", [])
                for z in zones:
                    if z.get("name", "").lower() == clean_domain:
                        return z
        except Exception:
            pass
        return None

    def check_connection(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"connected": False, "error": "HETZNER_API_KEY is not set"}
        try:
            url = f"{self.base_url}/zones?per_page=1"
            resp = requests.get(url, headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                return {"connected": True}
            return {"connected": False, "status_code": resp.status_code, "error": resp.text[:200]}
        except Exception as e:
            return {"connected": False, "error": str(e)}
