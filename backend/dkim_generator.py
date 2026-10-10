import os
import re
import shutil
import subprocess
import base64
from typing import Optional, Tuple
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

DKIM_DIR = os.getenv("DKIM_DIR", "/var/lib/rspamd/dkim")

def get_or_generate_dkim(domain: str, selector: str = "mail", bits: int = 2048) -> Tuple[str, str]:
    """
    Returns (public_txt_value, private_key_status).
    Tries rspamadm dkim_keygen first (if on mailserver), else generates via cryptography.
    """
    clean_domain = domain.strip().lower()
    key_file = os.path.join(DKIM_DIR, f"{clean_domain}.{selector}.key")

    # If key already exists on disk
    if os.path.exists(key_file):
        pub = _extract_public_key_from_file(key_file)
        if pub:
            return pub, f"Existing key found at {key_file}"

    # Try rspamadm dkim_keygen
    if shutil.which("rspamadm"):
        os.makedirs(DKIM_DIR, exist_ok=True)
        try:
            cmd = ["rspamadm", "dkim_keygen", "-d", clean_domain, "-s", selector, "-b", str(bits), "-k", key_file]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = res.stdout

            # Fix permissions for rspamd if running as root
            try:
                import pwd
                import grp
                uid = pwd.getpwnam("_rspamd").pw_uid
                gid = grp.getgrnam("_rspamd").gr_gid
                os.chown(key_file, uid, gid)
                os.chmod(key_file, 0o640)
            except Exception:
                pass

            parts = re.findall(r'"([^"]*)"', output)
            if parts:
                return "".join(parts), f"Generated via rspamadm ({bits}-bit)"
        except Exception:
            pass

    # Fallback to cryptography library
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits
    )
    public_key = private_key.public_key()
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    b64_pub = base64.b64encode(der_bytes).decode('ascii')
    txt_record = f"v=DKIM1; k=rsa; p={b64_pub}"

    # Try to save private key if directory is writable
    status_msg = f"Generated via cryptography ({bits}-bit)"
    try:
        os.makedirs(DKIM_DIR, exist_ok=True)
        pem_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(key_file, "wb") as f:
            f.write(pem_bytes)
        try:
            import pwd
            import grp
            uid = pwd.getpwnam("_rspamd").pw_uid
            gid = grp.getgrnam("_rspamd").gr_gid
            os.chown(key_file, uid, gid)
            os.chmod(key_file, 0o640)
        except Exception:
            pass
        status_msg += f" (saved to {key_file})"
    except Exception:
        pass

    return txt_record, status_msg

def _extract_public_key_from_file(key_file: str) -> Optional[str]:
    try:
        with open(key_file, "rb") as f:
            key_data = f.read()
        priv = serialization.load_pem_private_key(key_data, password=None)
        pub = priv.public_key()
        der_bytes = pub.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        b64_pub = base64.b64encode(der_bytes).decode('ascii')
        return f"v=DKIM1; k=rsa; p={b64_pub}"
    except Exception:
        return None
