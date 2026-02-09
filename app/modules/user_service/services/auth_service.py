import logging

from app.exceptions.exceptions import (
    InvalidCredentialsException,
    ResourceAlreadyExistsException,
    ResourceNotFoundException,
    UnauthorizedAccessException,
    ValidationException,
)
from app.mail.service.resend_service import resend_email_service

from ..models.session_model import Session
from ..models.user_model import User
from ..repositories.session_repository import SessionRepository
from ..repositories.user_repository import UserRepository
from ..schema.user_schema import (
    ForgotPasswordSchema,
    GenericMessageSchema,
    RefreshTokenSchema,
    ResendVerificationSchema,
    ResetPasswordSchema,
    UserLoginSchema,
    UsernameAvailabilityResponseSchema,
    UserRegistrationResponseSchema,
    UserRegistrationSchema,
    UserSchema,
    VerifyUserResponseSchema,
    VerifyUserSchema,
)
from ..utils.auth_utils import JWTUtils, PasswordUtils, VerificationCodeUtils

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(
        self, user_repository: UserRepository, session_repository: SessionRepository
    ):
        self.user_repository = user_repository
        self.session_repository = session_repository

    async def check_username_availability(
        self, username: str
    ) -> tuple[int, UsernameAvailabilityResponseSchema]:
        """Check if a username is available"""
        logger.info(f"Checking availability for username: {username}")

        # Check if username exists
        existing_user = await self.user_repository.get_by_username(username)

        if existing_user:
            # Username is taken
            return 200, UsernameAvailabilityResponseSchema(
                available=False, username=username, message="Username is already taken"
            )

        # Username is available
        return 200, UsernameAvailabilityResponseSchema(
            available=True, username=username, message="Username is available"
        )

    async def register_user(
        self, user_data: UserRegistrationSchema
    ) -> tuple[int, UserRegistrationResponseSchema]:
        """Register a new user or update existing unverified user"""
        # Check for existing verified user by email
        existing_user = await self.user_repository.get_by_email(user_data.email)
        if existing_user and existing_user.is_verified:
            raise ResourceAlreadyExistsException(
                f"User already exists with this email {user_data.email}"
            )

        # Check for existing verified user by username
        existing_user_by_username = await self.user_repository.get_by_username(
            user_data.username
        )
        if existing_user_by_username and existing_user_by_username.is_verified:
            raise ResourceAlreadyExistsException(
                f"User already exists with username {user_data.username}"
            )
        # Hash password
        hashed_password = PasswordUtils.generate_password_hash(user_data.password)
        verification_code = VerificationCodeUtils.generate_verification_code()
        verification_expiry = VerificationCodeUtils.verification_code_expiry()

        if existing_user and not existing_user.is_verified:
            # Update existing unverified user
            updated_user = await self.user_repository.update_user(
                existing_user.id,
                name=user_data.name,
                username=user_data.username,
                password=hashed_password,
                verification_code=verification_code,
                verification_code_expiry=verification_expiry,
            )

            # Send verification email
            try:
                await resend_email_service.send_verification_email(
                    user_email=updated_user.email,
                    user_name=updated_user.name,
                    verification_code=verification_code,
                )
            except Exception as e:
                # Log error but don't fail registration
                logger.error(
                    f"Failed to send verification email to {updated_user.email}: {str(e)}"
                )

            user_schema = UserSchema.model_validate(updated_user)
            return 200, UserRegistrationResponseSchema(user=user_schema)
        else:
            # Create new user
            new_user = User(
                name=user_data.name,
                email=user_data.email,
                username=user_data.username,
                password=hashed_password,
                verification_code=verification_code,
                verification_code_expiry=verification_expiry,
            )
            created_user = await self.user_repository.create_user(new_user)

            # Send verification email
            try:
                await resend_email_service.send_verification_email(
                    user_email=created_user.email,
                    user_name=created_user.name,
                    verification_code=verification_code,
                )
            except Exception as e:
                # Log error but don't fail registration
                logger.error(
                    f"Failed to send verification email to {created_user.email}: {str(e)}"
                )

            user_schema = UserSchema.model_validate(created_user)
            return 201, UserRegistrationResponseSchema(user=user_schema)

    async def login_user(
        self,
        login_data: UserLoginSchema,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[int, str, str, int, UserSchema]:
        """Login user with email/username and password"""
        # Find user by email or username
        user = await self.user_repository.get_by_identifier(login_data.identifier)
        if not user:
            raise InvalidCredentialsException("Invalid email/username or password")

        # Check if user is verified
        if not user.is_verified:
            raise UnauthorizedAccessException(
                "Please verify your email before logging in"
            )

        # Verify password
        if not PasswordUtils.check_password_hash(user.password, login_data.password):
            raise InvalidCredentialsException("Invalid email/username or password")

        # Create tokens and session
        access_token, refresh_token, expires_in = await self._create_user_session(
            user, user_agent, ip_address
        )
        user_schema = UserSchema.model_validate(user)

        return 200, access_token, refresh_token, expires_in, user_schema

    async def verify_user(
        self,
        verify_data: VerifyUserSchema,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[int, VerifyUserResponseSchema]:
        """Verify user email and automatically log them in"""
        user = await self.user_repository.get_by_identifier(verify_data.identifier)
        if not user:
            raise ResourceNotFoundException("User not found")

        if user.is_verified:
            raise ValidationException("User is already verified")

        if (
            not user.verification_code
            or user.verification_code != verify_data.verification_code
        ):
            raise InvalidCredentialsException("Invalid verification code")

        if VerificationCodeUtils.is_verification_code_expired(
            user.verification_code_expiry
        ):
            raise ValidationException("Verification code has expired")

        # Verify user
        verified_user = await self.user_repository.update_user(
            user.id,
            is_verified=True,
            verification_code=None,
            verification_code_expiry=None,
        )

        # Send welcome email after successful verification
        try:
            await resend_email_service.send_welcome_email(
                user_email=verified_user.email, user_name=verified_user.name
            )
        except Exception as e:
            # Log error but don't fail verification
            logger.error(
                f"Failed to send welcome email to {verified_user.email}: {str(e)}"
            )

        # Create tokens and session (auto-login)
        access_token, refresh_token, expires_in = await self._create_user_session(
            verified_user, user_agent, ip_address
        )
        user_schema = UserSchema.model_validate(verified_user)

        # Create token response structure
        tokens = {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

        return 200, VerifyUserResponseSchema(user=user_schema, tokens=tokens)

    async def check_verification_code(
        self, identifier: str, verification_code: str
    ) -> tuple[int, GenericMessageSchema]:
        """Check if verification code is valid without verifying the user"""
        # Find user by email
        user = await self.user_repository.get_by_identifier(identifier)
        if not user:
            raise ResourceNotFoundException("User not found")

        # if user.is_verified:
        #     raise ValidationException("User is already verified")

        if not user.verification_code or user.verification_code != verification_code:
            raise InvalidCredentialsException("Invalid verification code")

        if VerificationCodeUtils.is_verification_code_expired(
            user.verification_code_expiry
        ):
            raise ValidationException("Verification code has expired")

        return 200, GenericMessageSchema(message="Verification code is valid")

    async def refresh_token(
        self, refresh_data: RefreshTokenSchema
    ) -> tuple[int, dict[str, str]]:
        """Refresh access token using refresh token"""
        # Verify refresh token
        if not JWTUtils.verify_refresh_token(refresh_data.refresh_token):
            raise UnauthorizedAccessException("Invalid refresh token")

        # Get session by refresh token
        session = await self.session_repository.get_session_by_refresh_token(
            refresh_data.refresh_token
        )
        if not session:
            raise UnauthorizedAccessException("Session not found")

        # Check if session is expired
        if not await self.session_repository.is_session_valid(
            refresh_data.refresh_token
        ):
            await self.session_repository.delete_session(session.id)
            raise UnauthorizedAccessException("Session expired")

        # Get user
        user = await self.user_repository.get_by_id(session.user_id)
        if not user:
            raise ResourceNotFoundException("User not found")

        # Generate new access token
        access_token = JWTUtils.create_access_token(
            {"sub": user.id, "email": user.email}
        )

        # Return both user and token information
        return 200, {
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_data.refresh_token,  # Keep same refresh token
        }

    async def forgot_password(
        self, forgot_data: ForgotPasswordSchema
    ) -> tuple[int, GenericMessageSchema]:
        """Request password reset"""
        user = await self.user_repository.get_by_identifier(forgot_data.identifier)
        if not user:
            # Don't reveal if email exists
            return 200, GenericMessageSchema(
                message="If the email exists, a password reset code has been sent"
            )

        # Generate verification code
        verification_code = VerificationCodeUtils.generate_verification_code()
        verification_expiry = VerificationCodeUtils.verification_code_expiry()

        await self.user_repository.update_user(
            user.id,
            verification_code=verification_code,
            verification_code_expiry=verification_expiry,
        )

        # Send password reset email
        try:
            await resend_email_service.send_password_reset_email(
                user_email=user.email,
                user_name=user.name,
                verification_code=verification_code,
            )
        except Exception as e:
            # Log error but don't fail the request
            logger.error(
                f"Failed to send password reset email to {user.email}: {str(e)}"
            )

        return 200, GenericMessageSchema(
            message="If the email exists, a password reset code has been sent"
        )

    async def reset_password(
        self, reset_data: ResetPasswordSchema
    ) -> tuple[int, GenericMessageSchema]:
        """Reset password using verification code"""
        user = await self.user_repository.get_by_identifier(reset_data.identifier)
        if not user:
            raise ResourceNotFoundException("User not found")

        if (
            not user.verification_code
            or user.verification_code != reset_data.verification_code
        ):
            raise InvalidCredentialsException("Invalid verification code")

        if VerificationCodeUtils.is_verification_code_expired(
            user.verification_code_expiry
        ):
            raise ValidationException("Verification code has expired")

        # Hash new password
        hashed_password = PasswordUtils.generate_password_hash(reset_data.new_password)

        # Update password and clear verification code
        await self.user_repository.update_user(
            user.id,
            password=hashed_password,
            verification_code=None,
            verification_code_expiry=None,
        )

        # Delete all user sessions for security
        await self.session_repository.delete_user_sessions(user.id)

        return 200, GenericMessageSchema(
            message="Password reset successfully. Please login with your new password"
        )

    async def resend_verification_code(
        self, resend_data: ResendVerificationSchema
    ) -> tuple[int, GenericMessageSchema]:
        """Resend verification code to user email"""
        user = await self.user_repository.get_by_identifier(resend_data.identifier)
        if not user:
            return 200, GenericMessageSchema(
                message="If the email exists, a verification code has been sent"
            )

        if user.is_verified:
            raise ValidationException("User is already verified")

        # Generate new verification code
        verification_code = VerificationCodeUtils.generate_verification_code()
        verification_expiry = VerificationCodeUtils.verification_code_expiry()

        await self.user_repository.update_user(
            user.id,
            verification_code=verification_code,
            verification_code_expiry=verification_expiry,
        )

        # Send verification email
        try:
            await resend_email_service.send_verification_email(
                user_email=user.email,
                user_name=user.name,
                verification_code=verification_code,
            )
        except Exception as e:
            # Log error but don't fail the request
            logger.error(f"Failed to send verification email to {user.email}: {str(e)}")

        return 200, GenericMessageSchema(
            message="If the email exists, a verification code has been sent"
        )

    async def logout_user(self, refresh_token: str) -> tuple[int, GenericMessageSchema]:
        """Logout user by deleting session"""
        session = await self.session_repository.get_session_by_refresh_token(
            refresh_token
        )
        if session:
            await self.session_repository.delete_session(session.id)

        return 200, GenericMessageSchema(message="Logged out successfully")

    async def logout_all_devices(
        self, user_id: str
    ) -> tuple[int, GenericMessageSchema]:
        """Logout user from all devices"""
        await self.session_repository.delete_user_sessions(user_id)
        return 200, GenericMessageSchema(
            message="Logged out from all devices successfully"
        )

    async def _create_user_session(
        self, user: User, user_agent: str | None = None, ip_address: str | None = None
    ) -> tuple[str, str, int]:
        """Create session and return tokens"""
        # Enforce session limit (delete oldest if needed)
        await self.session_repository.enforce_session_limit(user.id, max_sessions=4)

        # Create tokens
        access_token = JWTUtils.create_access_token(
            {"sub": user.id, "email": user.email}
        )
        refresh_token = JWTUtils.create_refresh_token(user.id)

        # Create session
        session = Session(
            user_id=user.id,
            refresh_token=refresh_token,
            expires_at=JWTUtils.get_refresh_token_expiry_time(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self.session_repository.create_session(session)

        # Return access token, refresh token, and expires_in (duration in seconds)
        expires_in = JWTUtils.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return access_token, refresh_token, expires_in
