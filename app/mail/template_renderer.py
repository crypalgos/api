import sys
from pathlib import Path
from typing import Any

current_dir = Path(__file__).parent
src_dir = current_dir.parent
sys.path.insert(0, str(src_dir))


class EmailTemplateRenderer:
    """
    Handles loading and rendering of email templates with dynamic content
    Templates now have embedded CSS for simplicity and better linting support
    """

    def __init__(self):
        self.template_dir = Path(__file__).parent / "templates"
        self.html_dir = self.template_dir / "html"

    def _load_html_template(self, template_name: str) -> str:
        """Load HTML template from file"""
        template_path = self.html_dir / template_name
        try:
            with open(template_path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise ValueError(f"Email template not found: {template_name}") from None

    def render_template(self, template_name: str, variables: dict[str, Any]) -> str:
        """
        Render email template with provided variables
        Args:
            template_name (str): Name of the HTML template file
            variables (dict): Dictionary of variables to substitute in template
        Returns:
            str: Rendered HTML email content
        """
        # Load HTML template
        html_content = self._load_html_template(template_name)

        # Replace variables in template
        for key, value in variables.items():
            placeholder = f"{{{key}}}"
            html_content = html_content.replace(placeholder, str(value))

        return html_content

    def render_verification_email(
        self,
        user_name: str,
        user_email: str,
        verification_code: str,
        verification_link: str = "#",
    ) -> str:
        """Render email verification template"""
        variables = {
            "user_name": user_name,
            "user_email": user_email,
            "verification_code": verification_code,
            "verification_link": verification_link,
            "website_url": "https://crypalgos.com",
            "support_url": "https://crypalgos.com/support",
            "privacy_url": "https://crypalgos.com/privacy",
            "terms_url": "https://crypalgos.com/terms",
            "unsubscribe_url": f"https://crypalgos.com/unsubscribe?email={user_email}",
        }
        return self.render_template("verification_email.html", variables)

    def render_welcome_email(
        self, user_name: str, user_email: str, dashboard_link: str = "#"
    ) -> str:
        """Render welcome email template"""
        variables = {
            "user_name": user_name,
            "user_email": user_email,
            "dashboard_link": dashboard_link,
            "trading_guide_link": "https://crypalgos.com/guide",
            "website_url": "https://crypalgos.com",
            "support_url": "https://crypalgos.com/support",
            "privacy_url": "https://crypalgos.com/privacy",
            "terms_url": "https://crypalgos.com/terms",
            "twitter_url": "https://twitter.com/crypalgos",
            "linkedin_url": "https://linkedin.com/company/crypalgos",
            "telegram_url": "https://t.me/crypalgos",
            "discord_url": "https://discord.gg/crypalgos",
        }
        return self.render_template("welcome_email.html", variables)

    def render_password_reset_email(
        self,
        user_name: str,
        user_email: str,
        verification_code: str,
        reset_link: str = "#",
    ) -> str:
        """Render password reset email template"""
        variables = {
            "user_name": user_name,
            "user_email": user_email,
            "verification_code": verification_code,
            "reset_link": reset_link,
            "website_url": "https://crypalgos.com",
            "support_url": "https://crypalgos.com/support",
            "security_url": "https://crypalgos.com/security",
            "terms_url": "https://crypalgos.com/terms",
        }
        return self.render_template("password_reset_email.html", variables)


# Create singleton instance
email_template_renderer = EmailTemplateRenderer()
