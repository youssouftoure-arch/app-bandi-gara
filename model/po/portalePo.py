from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Portale:
    # Campi originali
    numero:   int
    cliente:  str
    gruppo:   str
    url:      str
    username: str
    password: str
    note:     Optional[str] = None

    # Tipo di login
    login_type:   str = "unknown"
    captcha_type: str = "none"

    # MFA / OTP
    mfa_type:       str           = "none"
    totp_secret:    Optional[str] = None
    otp_email:      Optional[str] = None
    otp_email_pass: Optional[str] = None

    # Cache selettori
    selectors_cached: Optional[dict] = None

    # Sessione
    cookies_path:  Optional[str]      = None
    last_login_ok: Optional[datetime] = None
    session_ttl_h: int                = 24

    # Flags
    requires_manual: bool = False
    is_active:       bool = True

    @property
    def has_valid_session(self) -> bool:
        if not self.last_login_ok or not self.cookies_path:
            return False
        from datetime import timezone
        now  = datetime.now(timezone.utc)
        last = self.last_login_ok
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds() / 3600 < self.session_ttl_h

    @property
    def needs_manual_intervention(self) -> bool:
        return (
            self.requires_manual
            or self.mfa_type     == "manual"
            or self.captcha_type not in ("none", "unknown")
            or self.login_type   in ("oauth", "saml")
        )

    @classmethod
    def from_dataframe_row(cls, row: dict) -> "Portale":
        """
        Mappa le colonne reali dell'Excel:
        n°, cliente, gruppo, link_http, user, psw, note
        """
        import math

        def str_or_none(val):
            if val is None:
                return None
            if isinstance(val, float) and math.isnan(val):
                return None
            return str(val).strip() or None

        numero_val = row.get("n°") or row.get("numero")
        if numero_val is None or (isinstance(numero_val, float) and math.isnan(numero_val)):
            raise ValueError("numero")
        
        url = str_or_none(row.get("link_http") or row.get("url"))
        if not url:
            raise ValueError("url mancante")

        username = str_or_none(row.get("user") or row.get("username"))
        password = str_or_none(row.get("psw")  or row.get("password"))

        if not username or not password:
            raise ValueError("credenziali mancanti")

        return cls(
            numero   = int(numero_val),
            cliente  = str_or_none(row.get("cliente")) or "",
            gruppo   = str_or_none(row.get("gruppo"))  or "",
            url      = url,
            username = username,
            password = password,
            note     = str_or_none(row.get("note")),
            login_type       = row.get("login_type",   "unknown") or "unknown",
            captcha_type     = row.get("captcha_type", "none")    or "none",
            mfa_type         = row.get("mfa_type",     "none")    or "none",
            totp_secret      = str_or_none(row.get("totp_secret")),
            otp_email        = str_or_none(row.get("otp_email")),
            otp_email_pass   = str_or_none(row.get("otp_email_pass")),
            selectors_cached = row.get("selectors_cached"),
            cookies_path     = str_or_none(row.get("cookies_path")),
            last_login_ok    = row.get("last_login_ok"),
            session_ttl_h    = int(row.get("session_ttl_h") or 24),
            requires_manual  = bool(row.get("requires_manual", False)),
            is_active        = bool(row.get("is_active", True)),
        )