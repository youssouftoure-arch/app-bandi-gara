"""DTO del login: raccoglie esito, sessione, errori, MFA e selettori usati."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from model.enums.statoLoginEnum import LoginStatus


@dataclass
class LoginResult:
    portal_id:       str                        # ID univoco del portale
    url:             str                        # URL del portale
    status:          LoginStatus
    timestamp:       datetime = field(default_factory=datetime.utcnow)

    # Sessione
    cookies_path:    Optional[str]  = None      # Path al file cookie serializzato
    session_valid:   bool           = False

    # Classificazione vision
    page_state:      Optional[str]  = None      # PageState rilevato
    vision_model:    Optional[str]  = None      # Modello vision usato
    vision_notes:    Optional[str]  = None

    # MFA
    mfa_triggered:   bool           = False
    mfa_type:        Optional[str]  = None      # 'email_otp' | 'totp' | 'sms' | 'manual'
    mfa_resolved:    bool           = False

    # Errori e debug
    error_message:   Optional[str]  = None
    retry_count:     int            = 0

    # Selettori usati (per audit/debug)
    selectors_used:  Optional[dict] = None

    @property
    def is_success(self) -> bool:
        return self.status in (LoginStatus.SUCCESS, LoginStatus.SKIPPED_COOKIE)
