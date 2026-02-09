import logging
import os
from typing import Any

import resend

from app.config.settings import settings
from app.mail.template_renderer import email_template_renderer

logger = logging.getLogger(__name__)


class ResendEmailService:
    """
    Production-ready email service using Resend API
    Handles verification emails, welcome emails, password reset emails, etc.
    """

    def __init__(self, skip_validation: bool = False):
        """Initialize Resend client with API key from settings"""
        self.api_key = settings.resend_api_token

        if not self.api_key and not skip_validation:
            logger.error("Resend API token not configured in settings")
            raise ValueError("Resend API token not configured in settings")

        # Set the API key for resend if available
        if self.api_key:
            resend.api_key = self.api_key

        # Default sender information
        self.default_from_email = getattr(
            settings, "resend_from_email", "noreply@crypalgos.com"
        )
        self.default_from_name = getattr(
            settings, "resend_from_name", "CrypAlgos Platform"
        )

    async def validate_api_key(self) -> bool:
        """
        Validate the API key by making a test call to Resend
        Returns:
            bool: True if API key is valid, False otherwise
        """
        try:
            # Try to send a test email to a safe address (will fail but should give us authentication status)
            test_params = {
                "from": f"{self.default_from_name} <{self.default_from_email}>",
                "to": [
                    "test@example.com"
                ],  # This will fail but should authenticate first
                "subject": "Test API Key",
                "html": "<p>Test</p>",
            }

            # This will fail due to invalid recipient, but should authenticate first
            resend.Emails.send(test_params)
            return True

        except Exception as e:
            error_msg = str(e).lower()
            if "api key is invalid" in error_msg:
                return False
            elif "domain not verified" in error_msg:
                return True  # API key is valid, just domain issue
            else:
                # Other errors might indicate valid API but other issues
                return True

    async def _send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        from_email: str | None = None,
        from_name: str | None = None,
        reply_to: str | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> bool:
        """
        Send email using Resend API
        Args:
            to_email (str): Recipient email address
            to_name (str): Recipient name
            subject (str): Email subject
            html_content (str): HTML content of the email
            from_email (str, optional): Sender email
            from_name (str, optional): Sender name
            reply_to (str, optional): Reply-to email
            tags (list, optional): Email tags for tracking
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Prepare sender information
            sender_email = from_email or self.default_from_email
            sender_name = from_name or self.default_from_name
            sender = f"{sender_name} <{sender_email}>"

            # Prepare recipient
            recipient = f"{to_name} <{to_email}>"

            # Prepare email parameters
            params: resend.Emails.SendParams = {
                "from": sender,
                "to": [recipient],
                "subject": subject,
                "html": html_content,
            }

            # Add optional parameters
            if reply_to:
                params["reply_to"] = [reply_to]

            if tags:
                params["tags"] = tags

            # Send email
            email_response = resend.Emails.send(params)

            if email_response and "id" in email_response:
                return True
            else:
                logger.error(
                    f"Failed to send email to {to_email}. No email ID returned."
                )
                return False

        except Exception as e:
            # More specific error handling for Resend API errors
            error_message = str(e)

            # Check for specific Resend API errors and log appropriately
            if "API key is invalid" in error_message:
                logger.error(
                    "Resend API key is invalid. Please check RESEND_API_TOKEN in .env file"
                )
            elif "Domain not verified" in error_message:
                logger.error(
                    "Domain not verified in Resend. Please verify domain in Resend dashboard"
                )
            elif "rate limit" in error_message.lower():
                logger.error(
                    "Rate limit exceeded. Please wait before sending more emails"
                )
            else:
                logger.error(f"Error sending email to {to_email}: {error_message}")

            return False

    async def send_verification_email(
        self,
        user_email: str,
        user_name: str,
        verification_code: str,
        verification_link: str | None = None,
    ) -> bool:
        """
        Send email verification email to user
        Args:
            user_email (str): User's email address
            user_name (str): User's name
            verification_code (str): 6-digit verification code
            verification_link (str, optional): Direct verification link
        Returns:
            bool: True if email sent successfully
        """
        try:
            # Generate verification link if not provided
            if not verification_link:
                verification_link = f"https://crypalgos.com/verify?email={user_email}&code={verification_code}"

            # Render email template
            html_content = email_template_renderer.render_verification_email(
                user_name=user_name,
                user_email=user_email,
                verification_code=verification_code,
                verification_link=verification_link,
            )

            # Send email
            result = await self._send_email(
                to_email=user_email,
                to_name=user_name,
                subject="Verify Your CrypAlgos Account",
                html_content=html_content,
                tags=[
                    {"name": "category", "value": "verification"},
                    {"name": "user_action", "value": "registration"},
                ],
            )

            return result

        except Exception as e:
            logger.error(f"Error sending verification email to {user_email}: {str(e)}")
            return False

    async def send_welcome_email(
        self, user_email: str, user_name: str, dashboard_link: str | None = None
    ) -> bool:
        """
        Send welcome email after successful verification
        Args:
            user_email (str): User's email address
            user_name (str): User's name
            dashboard_link (str, optional): Link to user dashboard
        Returns:
            bool: True if email sent successfully
        """
        try:
            # Generate dashboard link if not provided
            if not dashboard_link:
                dashboard_link = "https://crypalgos.com/dashboard"

            # Render email template
            html_content = email_template_renderer.render_welcome_email(
                user_name=user_name,
                user_email=user_email,
                dashboard_link=dashboard_link,
            )

            # Send email
            return await self._send_email(
                to_email=user_email,
                to_name=user_name,
                subject="Welcome to CrypAlgos! 🎉",
                html_content=html_content,
                tags=[
                    {"name": "category", "value": "welcome"},
                    {"name": "user_action", "value": "onboarding"},
                ],
            )

        except Exception as e:
            logger.error(f"Error sending welcome email to {user_email}: {str(e)}")
            return False

    async def send_password_reset_email(
        self,
        user_email: str,
        user_name: str,
        verification_code: str,
        reset_link: str | None = None,
    ) -> bool:
        """
        Send password reset email
        Args:
            user_email (str): User's email address
            user_name (str): User's name
            verification_code (str): 6-digit verification code
            reset_link (str, optional): Direct reset link
        Returns:
            bool: True if email sent successfully
        """
        try:
            # Generate reset link if not provided
            if not reset_link:
                reset_link = f"https://crypalgos.com/reset-password?email={user_email}&code={verification_code}"

            # Render email template
            html_content = email_template_renderer.render_password_reset_email(
                user_name=user_name,
                user_email=user_email,
                verification_code=verification_code,
                reset_link=reset_link,
            )

            # Send email
            return await self._send_email(
                to_email=user_email,
                to_name=user_name,
                subject="Reset Your CrypAlgos Password",
                html_content=html_content,
                tags=[
                    {"name": "category", "value": "security"},
                    {"name": "user_action", "value": "password_reset"},
                ],
            )

        except Exception as e:
            logger.error(
                f"Error sending password reset email to {user_email}: {str(e)}"
            )
            return False

    async def resend_verification_email(
        self,
        user_email: str,
        user_name: str,
        verification_code: str,
        verification_link: str | None = None,
    ) -> bool:
        """
        Resend verification email (same as send_verification_email but with different tags)
        Args:
            user_email (str): User's email address
            user_name (str): User's name
            verification_code (str): 6-digit verification code
            verification_link (str, optional): Direct verification link
        Returns:
            bool: True if email sent successfully
        """
        try:
            # Generate verification link if not provided
            if not verification_link:
                verification_link = f"https://crypalgos.com/verify?email={user_email}&code={verification_code}"

            # Render email template
            html_content = email_template_renderer.render_verification_email(
                user_name=user_name,
                user_email=user_email,
                verification_code=verification_code,
                verification_link=verification_link,
            )

            # Send email with resend tags
            return await self._send_email(
                to_email=user_email,
                to_name=user_name,
                subject="CrypAlgos Account Verification (Resent)",
                html_content=html_content,
                tags=[
                    {"name": "category", "value": "verification"},
                    {"name": "user_action", "value": "resend_verification"},
                ],
            )

        except Exception as e:
            logger.error(
                f"Error resending verification email to {user_email}: {str(e)}"
            )
            return False

    async def send_custom_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        template_variables: dict[str, Any] | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> bool:
        """
        Send custom email with provided content
        Args:
            to_email (str): Recipient email
            to_name (str): Recipient name
            subject (str): Email subject
            html_content (str): HTML content or template
            template_variables (dict, optional): Variables to replace in content
            tags (list, optional): Email tags
        Returns:
            bool: True if email sent successfully
        """
        try:
            # Replace variables in content if provided
            if template_variables:
                for key, value in template_variables.items():
                    placeholder = f"{{{key}}}"
                    html_content = html_content.replace(placeholder, str(value))

            return await self._send_email(
                to_email=to_email,
                to_name=to_name,
                subject=subject,
                html_content=html_content,
                tags=tags or [{"name": "category", "value": "custom"}],
            )

        except Exception as e:
            logger.error(f"Error sending custom email to {to_email}: {str(e)}")
            return False


skip_validation = os.getenv("APP_ENV") == "testing" or os.getenv("ENV") == "testing"
resend_email_service = ResendEmailService(skip_validation=skip_validation)
