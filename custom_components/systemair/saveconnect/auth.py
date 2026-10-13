import logging
import time
from html.parser import HTMLParser

import httpx

_LOGGER = logging.getLogger(__name__)

SSO_URL = "https://sso.systemair.com/auth/realms/iot/protocol/openid-connect"
CLIENT_ID = "iot-application"
REDIRECT_URI = "https://homesolutions.systemair.com"

# Refresh when this fraction of the token lifetime has passed.
TOKEN_LIFETIME_USED = 0.8


class _LoginFormAction(HTMLParser):
    """Finds the action URL of the Keycloak login form (<form id="kc-form-login">)."""

    def __init__(self):
        super().__init__()
        self.action: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "kc-form-login" and self.action is None:
            self.action = attrs.get("action")


def login_form_action(html: str) -> str | None:
    parser = _LoginFormAction()
    parser.feed(html)
    return parser.action


class SaveConnectAuth:

    def __init__(self, api, http: httpx.AsyncClient | None = None):
        self._owns_http = http is None
        if http is None:
            http = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(retries=api.http_retries))
        self._http: httpx.AsyncClient = http
        self._oidc_token: dict = {}
        self._token_expiry = 0.0

    async def auth(self, email, password) -> bool:
        """Log in with email and password through the Keycloak login form."""
        response = await self._http.get(
            f"{SSO_URL}/auth",
            params={
                "client_id": CLIENT_ID,
                "response_type": "code",
                "redirect_uri": REDIRECT_URI,
                "scope": "openid",
            },
            follow_redirects=True,
        )
        action = login_form_action(response.text)
        if not action:
            _LOGGER.error("Systemair login form not found (HTTP %s)", response.status_code)
            return False

        response = await self._http.post(action, data=dict(
            username=email,
            password=password,
            rememberMe="on",
            credentialId=""
        ), follow_redirects=True)
        code = response.url.params.get("code")
        if not code:
            _LOGGER.error("Systemair login rejected, check email and password")
            return False

        return await self._request_token({
            "grant_type": "authorization_code",
            "code": code,
        })

    async def refresh_token(self) -> bool:
        """Get a new access token with the refresh token."""
        if "refresh_token" not in self._oidc_token:
            return False
        return await self._request_token({
            "grant_type": "refresh_token",
            "refresh_token": self._oidc_token["refresh_token"],
        })

    async def _request_token(self, data) -> bool:
        try:
            response = await self._http.post(
                url=f"{SSO_URL}/token",
                data={"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, **data},
            )
        except httpx.HTTPError as e:
            _LOGGER.warning("Systemair token request failed: %s", e)
            return False

        token = response.json() if response.status_code == 200 else {}
        if "access_token" not in token:
            _LOGGER.warning("Systemair token request (%s) rejected: HTTP %s",
                            data["grant_type"], response.status_code)
            self._oidc_token = {}
            self._token_expiry = 0.0
            return False

        self._oidc_token = token
        self._token_expiry = time.time() + token["expires_in"] * TOKEN_LIFETIME_USED
        _LOGGER.debug("Systemair access token acquired (%s), valid for %ss",
                      data["grant_type"], token["expires_in"])
        return True

    def is_auth(self) -> bool:
        """True while the access token is present and not about to expire."""
        return bool(self._oidc_token) and time.time() < self._token_expiry

    @property
    def token(self):
        return self._oidc_token

    @property
    def access_token(self):
        return self._oidc_token.get("access_token")

    async def close(self):
        if self._owns_http:
            await self._http.aclose()
