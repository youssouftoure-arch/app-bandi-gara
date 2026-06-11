"""Enum degli esiti possibili del processo di login automatico."""

from enum import Enum

class LoginStatus(str, Enum):
    SUCCESS          = "success"           # Login riuscito, cookie salvati
    FAILED_CREDS     = "failed_creds"      # Credenziali errate
    FAILED_CAPTCHA   = "failed_captcha"    # Bloccato da CAPTCHA non risolvibile
    FAILED_MFA       = "failed_mfa"        # MFA richiesto, non gestibile
    FAILED_MANUAL    = "failed_manual"     # Richiede intervento umano
    FAILED_ERROR     = "failed_error"      # Errore tecnico generico
    SKIPPED_COOKIE   = "skipped_cookie"    # Sessione cookie ancora valida, skip login
