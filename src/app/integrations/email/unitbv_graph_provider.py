"""
Microsoft Graph API Email Provider for UNITBV (Cross-Tenant with Delegated Access).

Implements OAuth2 Authorization Code flow for delegated user access to UNITBV mailbox.
Uses /me endpoints which resolve to the authenticated user's resources.
"""

import asyncio
import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import httpx

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException, IntegrationException
from src.app.core.logging import logger
from src.app.core.practice_config import get_practice_keywords
from src.app.integrations.email.base import EmailProvider
from src.app.schemas.email import EmailDraftReply, EmailFilterParams, EmailMessageSchema


class UnitbvGraphProvider(EmailProvider):
    """
    Access UNITBV mailbox via Microsoft Graph API using delegated OAuth2 authorization.
    
    Flow:
    1. User initiates login → redirects to Microsoft login (tenantul UNITBV)
    2. User authenticates + grants consent
    3. Authorization code redirected back to app
    4. App exchanges code for access token + refresh token
    5. App uses access token to call Graph /me/mailFolders/inbox/messages
    
    Uses /me endpoints (authenticated user context) instead of /users/{email} (admin context).
    """

    def __init__(self, account_type: str = "unitbv"):
        self.account_type = account_type.lower()
        
        # Graph endpoint
        self.endpoint = settings.MICROSOFT_GRAPH_ENDPOINT.rstrip("/")
        
        # UNITBV tenant (cross-tenant authentication)
        self.unitbv_tenant_id = settings.UNITBV_MICROSOFT_TENANT_ID or settings.MICROSOFT_TENANT_ID
        
        # Application credentials (from tenantul tău personal, but used for UNITBV)
        self.client_id = settings.MICROSOFT_CLIENT_ID
        self.client_secret = settings.MICROSOFT_CLIENT_SECRET
        
        # Scopes for delegated access (user consent required)
        self.scopes = settings.UNITBV_MICROSOFT_SCOPES or "Mail.Read offline_access"
        
        # Redirect URI for OAuth callback
        self.redirect_uri = settings.UNITBV_MICROSOFT_REDIRECT_URI
        
        # Token storage (in production, store in secure backend storage, not memory)
        self.access_token = settings.UNITBV_MICROSOFT_ACCESS_TOKEN
        self.refresh_token = settings.UNITBV_MICROSOFT_REFRESH_TOKEN
        
        self._cached_access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_configured(self) -> bool:
        """Check if minimum required configuration exists."""
        required = [self.unitbv_tenant_id, self.client_id, self.client_secret, self.redirect_uri]
        return bool(all(required)) and not any(self._is_placeholder(f) for f in required)

    @staticmethod
    def _is_placeholder(val: Optional[str]) -> bool:
        if not val:
            return True
        val_lower = str(val).strip().lower()
        return (
            val_lower.startswith("your-")
            or val_lower.startswith("<")
            or val_lower.startswith("replace-")
            or "placeholder" in val_lower
        )

    def _require_configuration(self) -> None:
        if not self._is_configured():
            raise ConfigurationException(
                f"UNITBV Microsoft Graph settings are incomplete. Configure in .env:\n"
                "  UNITBV_MICROSOFT_TENANT_ID (tenantul UNITBV)\n"
                "  MICROSOFT_CLIENT_ID\n"
                "  MICROSOFT_CLIENT_SECRET\n"
                "  UNITBV_MICROSOFT_REDIRECT_URI\n"
                "And perform initial authorization to get:\n"
                "  UNITBV_MICROSOFT_ACCESS_TOKEN\n"
                "  UNITBV_MICROSOFT_REFRESH_TOKEN (for long-lived access)"
            )

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """
        Generate the URL for user authorization (first-time setup).
        
        User navigates to this URL, authenticates, and grants consent.
        Browser redirects to redirect_uri with authorization code.
        """
        auth_url = f"https://login.microsoftonline.com/{quote(self.unitbv_tenant_id)}/oauth2/v2.0/authorize"
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scopes,
            "state": state or "security_token",
            "prompt": "select_account",  # Force account selection (don't auto-sign-in)
        }
        
        return f"{auth_url}?{urlencode(params)}"

    async def exchange_authorization_code(self, auth_code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access + refresh tokens.
        
        Call this after user authorizes and is redirected back with auth_code.
        Returns tokens which should be saved to .env / secure storage.
        """
        token_url = f"https://login.microsoftonline.com/{quote(self.unitbv_tenant_id)}/oauth2/v2.0/token"
        
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "code": auth_code,
            "scope": self.scopes,
        }
        
        timeout = min(settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS, 30.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(token_url, data=payload)
        except Exception as exc:
            raise IntegrationException(f"Failed to exchange auth code: {type(exc).__name__}") from exc
        
        if resp.status_code != 200:
            error_info = "token exchange failed"
            try:
                err = resp.json()
                error_info = err.get("error_description", err.get("error", error_info))
            except Exception:
                pass
            raise IntegrationException(f"Authorization code exchange failed: {error_info}")
        
        token_data = resp.json()
        logger.info(
            "Successfully exchanged auth code for tokens. "
            "Add these to .env:\n"
            f"  UNITBV_MICROSOFT_ACCESS_TOKEN={token_data.get('access_token', 'N/A')[:50]}...\n"
            f"  UNITBV_MICROSOFT_REFRESH_TOKEN={token_data.get('refresh_token', 'N/A')[:50]}..."
        )
        return token_data

    async def _get_access_token(self) -> str:
        """
        Get or refresh access token.
        
        Priority:
        1. Use static token from .env (if provided and not expired)
        2. Use cached in-memory token
        3. Refresh token if refresh_token is available
        4. Fail if no token available
        """
        async with self._lock:
            now = time.time()
            
            # Check in-memory cache (with 60s buffer before actual expiry)
            if self._cached_access_token and now < (self._token_expires_at - 60):
                return self._cached_access_token
            
            # If static token provided via .env, use it
            if self.access_token and not self._is_placeholder(self.access_token):
                self._cached_access_token = self.access_token
                self._token_expires_at = now + 3600  # Assume 1 hour
                return self.access_token
            
            # Try to refresh using refresh token
            if self.refresh_token and not self._is_placeholder(self.refresh_token):
                token_data = await self._refresh_access_token()
                self._cached_access_token = token_data.get("access_token")
                expires_in = float(token_data.get("expires_in", 3600))
                self._token_expires_at = now + expires_in
                return self._cached_access_token
            
            # No token available
            raise IntegrationException(
                "No valid UNITBV Microsoft Graph access token available. "
                "Perform authorization first by calling get_authorization_url()."
            )

    async def _refresh_access_token(self) -> Dict[str, Any]:
        """Refresh access token using refresh token."""
        token_url = f"https://login.microsoftonline.com/{quote(self.unitbv_tenant_id)}/oauth2/v2.0/token"
        
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "scope": self.scopes,
        }
        
        timeout = min(settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS, 30.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(token_url, data=payload)
        except Exception as exc:
            raise IntegrationException(f"Token refresh failed: {type(exc).__name__}") from exc
        
        if resp.status_code != 200:
            error_info = "refresh failed"
            try:
                err = resp.json()
                error_info = err.get("error_description", err.get("error", error_info))
            except Exception:
                pass
            logger.warning(f"UNITBV access token refresh failed: {error_info}. User re-authorization may be needed.")
            raise IntegrationException(f"Failed to refresh access token: {error_info}")
        
        token_data = resp.json()
        logger.info("Refreshed UNITBV Microsoft Graph access token.")
        return token_data

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Perform authorized Graph request with retry and throttle handling."""
        attempts = max(1, settings.EXTERNAL_RETRY_ATTEMPTS + 1)
        timeout = settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS

        for attempt in range(1, attempts + 1):
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
            if json_data:
                headers["Content-Type"] = "application/json"

            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.request(method, url, headers=headers, params=params, json=json_data)
            except Exception as exc:
                if attempt == attempts:
                    raise IntegrationException(
                        f"Microsoft Graph request failed after {attempts} attempts: {type(exc).__name__}"
                    ) from exc
                await asyncio.sleep(0.5 * attempt)
                continue

            # Handle throttling
            if resp.status_code in (429, 503, 504):
                if attempt < attempts:
                    retry_after = resp.headers.get("Retry-After", str(1.0 * attempt))
                    try:
                        wait_seconds = float(retry_after)
                    except ValueError:
                        wait_seconds = 1.0 * attempt
                    wait_seconds = min(wait_seconds, 10.0)
                    logger.warning(
                        "Microsoft Graph throttled (HTTP %d). Retrying in %.1fs (attempt %d/%d).",
                        resp.status_code, wait_seconds, attempt, attempts
                    )
                    await asyncio.sleep(wait_seconds)
                    continue

            return resp

        raise IntegrationException(f"Microsoft Graph request exceeded max retries ({attempts}).")

    async def fetch_emails(
        self, account_type: str, filter_params: Optional[EmailFilterParams] = None
    ) -> List[EmailMessageSchema]:
        """Fetch emails from authenticated user's inbox using /me endpoint."""
        self._require_configuration()

        # Use /me instead of /users/{email} - resolves to authenticated user
        url = f"{self.endpoint}/me/mailFolders/inbox/messages"
        limit = min(max((filter_params.limit if filter_params else 10), 1), 100)

        query_params: Dict[str, str] = {
            "$top": str(limit),
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,bodyPreview,body,from,toRecipients,receivedDateTime,importance,isRead",
        }

        # Build filter
        filter_clauses = []
        if filter_params:
            if filter_params.is_important_only:
                filter_clauses.append("importance eq 'high'")
            if filter_params.sender:
                clean_sender = filter_params.sender.replace("'", "''")
                filter_clauses.append(f"from/emailAddress/address eq '{clean_sender}'")
            if filter_params.date_from:
                filter_clauses.append(
                    f"receivedDateTime ge {filter_params.date_from.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                )
            if filter_params.date_to:
                filter_clauses.append(
                    f"receivedDateTime le {filter_params.date_to.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                )

        if filter_clauses:
            query_params["$filter"] = " and ".join(filter_clauses)

        resp = await self._request_with_retry("GET", url, params=query_params)
        if resp.status_code != 200:
            err_msg = f"HTTP {resp.status_code}"
            try:
                err_data = resp.json()
                err_msg = err_data.get("error", {}).get("message", err_msg)
            except Exception:
                pass
            raise IntegrationException(f"Failed to fetch emails via Microsoft Graph API: {err_msg}")

        data = resp.json()
        messages_raw = data.get("value", [])

        results: List[EmailMessageSchema] = []
        for msg in messages_raw:
            parsed = self._parse_graph_message(msg)
            if filter_params and filter_params.keywords:
                content_lower = f"{parsed.subject} {parsed.body_text}".lower()
                if not any(kw.lower() in content_lower for kw in filter_params.keywords):
                    continue
            results.append(parsed)

        return results

    async def get_email_by_id(self, account_type: str, message_id: str) -> Optional[EmailMessageSchema]:
        """Fetch a specific email by ID."""
        self._require_configuration()

        url = f"{self.endpoint}/me/messages/{quote(message_id)}"
        query_params = {
            "$select": "id,subject,bodyPreview,body,from,toRecipients,receivedDateTime,importance,isRead",
        }

        resp = await self._request_with_retry("GET", url, params=query_params)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise IntegrationException(
                f"Microsoft Graph error retrieving email '{message_id}' (HTTP {resp.status_code})"
            )

        return self._parse_graph_message(resp.json())

    async def send_email(self, account_type: str, draft: EmailDraftReply) -> bool:
        """Send an email through /me/sendMail endpoint."""
        self._require_configuration()

        url = f"{self.endpoint}/me/sendMail"
        payload = {
            "message": {
                "subject": draft.subject,
                "body": {
                    "contentType": "Text",
                    "content": draft.body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": draft.recipient,
                        }
                    }
                ],
            },
            "saveToSentItems": True,
        }

        resp = await self._request_with_retry("POST", url, json_data=payload)
        if resp.status_code in (200, 202):
            logger.info("Sent email through Microsoft Graph API to %s.", draft.recipient)
            return True

        err_detail = f"HTTP {resp.status_code}"
        try:
            err_json = resp.json()
            err_detail = err_json.get("error", {}).get("message", err_detail)
        except Exception:
            pass
        raise IntegrationException(f"Failed to send email via Microsoft Graph API: {err_detail}")

    def _parse_graph_message(self, item: Dict[str, Any]) -> EmailMessageSchema:
        """Parse Microsoft Graph message into EmailMessageSchema."""
        from_data = item.get("from") or {}
        email_addr = from_data.get("emailAddress") or {}
        sender_address = email_addr.get("address", "")
        sender_name = email_addr.get("name", "")
        sender = f"{sender_name} <{sender_address}>" if sender_name and sender_address else (sender_address or sender_name or "unknown@unitbv.ro")

        recipients = []
        for to_item in item.get("toRecipients", []):
            to_addr = (to_item.get("emailAddress") or {}).get("address")
            if to_addr:
                recipients.append(to_addr)

        raw_date = item.get("receivedDateTime")
        received_at = self._parse_iso_date(raw_date)

        subject = item.get("subject") or "(Fără subiect)"
        preview = item.get("bodyPreview") or ""
        body_dict = item.get("body") or {}
        body_text = self._clean_body_text(body_dict, fallback_preview=preview)

        graph_importance = (item.get("importance") or "normal").lower()
        is_practice = self._detect_practice(subject, body_text)
        is_high = graph_importance == "high" or is_practice or ("important" in subject.lower())
        importance_str = "high" if is_high else ("low" if graph_importance == "low" else "medium")

        deadline = self._detect_deadline(body_text)

        return EmailMessageSchema(
            message_id=item.get("id", ""),
            account_type=self.account_type,
            sender=sender,
            recipients=recipients,
            subject=subject,
            body_text=body_text[:10000],
            received_at=received_at,
            importance=importance_str,
            summary=preview[:300] if preview else None,
            is_practice_related=is_practice,
            requires_action=bool(deadline or is_practice),
            detected_deadline=deadline,
        )

    @staticmethod
    def _parse_iso_date(raw_date: Optional[str]) -> datetime:
        if raw_date:
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _clean_body_text(body_dict: Dict[str, Any], fallback_preview: str = "") -> str:
        content = body_dict.get("content", "")
        content_type = (body_dict.get("contentType") or "text").lower()

        if content_type == "html" and content:
            clean = re.sub(r"<style[\s\S]*?</style>", "", content, flags=re.IGNORECASE)
            clean = re.sub(r"<script[\s\S]*?</script>", "", clean, flags=re.IGNORECASE)
            clean = re.sub(r"<br\s*/?>", "\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"</p>", "\n\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"</div>", "\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = html.unescape(clean)
            clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
            return clean or fallback_preview

        return content.strip() or fallback_preview

    @staticmethod
    def _detect_practice(subject: str, body: str) -> bool:
        """Detect practice-related emails."""
        import unicodedata
        import re

        text = f"{subject} {body}".lower()
        normalized = unicodedata.normalize('NFKD', text)
        normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
        tokens = set(re.findall(r"\b\w+\b", normalized))

        base_keywords = [
            "practică", "practica", "convenție", "conventie", "caiet",
            "adeverință", "adeverinta", "colocviu", "tutore",
        ]
        all_keywords = set(base_keywords + get_practice_keywords())
        kw_set = {''.join(ch for ch in unicodedata.normalize('NFKD', kw.lower()) if not unicodedata.combining(ch))
                  for kw in all_keywords}
        return bool(tokens.intersection(kw_set))

    @staticmethod
    def _detect_deadline(text: str) -> Optional[str]:
        patterns = [
            r"(?:până la|termen limită|pana la|termen)[:\s]+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
            r"(?:până la|pana la|termen)[:\s]+(\d{1,2}\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None
