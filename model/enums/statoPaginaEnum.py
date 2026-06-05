from enum import Enum

class PageState(str, Enum):
    STANDARD_FORM   = "standard_form"
    OAUTH_SSO       = "oauth_sso"
    CAPTCHA_PRESENT = "captcha_present"
    MFA_OTP         = "mfa_otp"
    LOGGED_IN       = "logged_in"
    ERROR_PAGE      = "error_page"
    UNKNOWN         = "unknown"
