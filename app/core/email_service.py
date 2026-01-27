"""Email service for sending emails via AWS SES."""

import boto3
from botocore.exceptions import ClientError
from typing import Optional
import logging

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via AWS SES."""
    
    @staticmethod
    def _get_ses_client():
        """Get boto3 SES client."""
        return boto3.client(
            'ses',
            region_name=settings.AWS_SES_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
    
    @classmethod
    async def send_email(
        cls,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        """
        Send an email via AWS SES.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML version of email body
            text_body: Plain text version of email body
            
        Returns:
            True if email sent successfully, False otherwise
        """
        ses_client = cls._get_ses_client()
        
        try:
            response = ses_client.send_email(
                Source=f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
                Destination={
                    'ToAddresses': [to_email]
                },
                Message={
                    'Subject': {
                        'Data': subject,
                        'Charset': 'UTF-8'
                    },
                    'Body': {
                        'Text': {
                            'Data': text_body,
                            'Charset': 'UTF-8'
                        },
                        'Html': {
                            'Data': html_body,
                            'Charset': 'UTF-8'
                        }
                    }
                }
            )
            
            logger.info(f"Email sent successfully to {to_email}. MessageId: {response['MessageId']}")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"Failed to send email to {to_email}. Error: {error_code} - {error_message}")
            
            # Common errors:
            # - MessageRejected: Email address not verified (SES sandbox mode)
            # - InvalidParameterValue: Invalid email format
            # - ConfigurationSetDoesNotExist: Configuration set doesn't exist
            
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error sending email to {to_email}: {str(e)}")
            return False
    
    @classmethod
    async def send_password_reset_email(
        cls,
        to_email: str,
        user_name: str,
        reset_token: str
    ) -> bool:
        """
        Send password reset email with reset link.
        
        Args:
            to_email: User's email address
            user_name: User's name
            reset_token: Password reset token
            
        Returns:
            True if email sent successfully
        """
        from app.core.email_templates import get_password_reset_email
        
        reset_url = f"{settings.WEB_RESET_PASSWORD_URL}?token={reset_token}"
        
        html_body, text_body = get_password_reset_email(
            user_name=user_name,
            reset_url=reset_url
        )
        
        return await cls.send_email(
            to_email=to_email,
            subject="Reset Your Vatisha Password",
            html_body=html_body,
            text_body=text_body
        )
