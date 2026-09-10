from abc import ABC, abstractmethod
from typing import List, Optional
from src.app.schemas.email import EmailMessageSchema, EmailFilterParams, EmailDraftReply


class EmailProvider(ABC):
    """
    Abstract Base Class for Email Providers (IMAP, Gmail API, Microsoft Graph, Mock).
    Ensures Email Service logic is completely decoupled from low-level email server protocols.
    """

    @abstractmethod
    async def fetch_emails(
        self,
        account_type: str,
        filter_params: Optional[EmailFilterParams] = None
    ) -> List[EmailMessageSchema]:
        """
        Fetch and filter emails for a given account ('personal' or 'unitbv').
        """
        pass

    @abstractmethod
    async def get_email_by_id(
        self,
        account_type: str,
        message_id: str
    ) -> Optional[EmailMessageSchema]:
        """
        Retrieve a specific email message by its message_id.
        """
        pass

    @abstractmethod
    async def send_email(
        self,
        account_type: str,
        draft: EmailDraftReply
    ) -> bool:
        """
        Send an email message via SMTP/Graph API after human approval.
        """
        pass
