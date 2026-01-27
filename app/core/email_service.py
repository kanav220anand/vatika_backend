"""Email service for sending emails via AWS SES."""

import asyncio
import boto3
from botocore.exceptions import ClientError
from typing import Optional
import logging
import traceback

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
    
    @staticmethod
    def _send_email_sync(
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Synchronous wrapper for sending email via AWS SES.
        
        Returns:
            Tuple of (success: bool, message_id: Optional[str], error_message: Optional[str])
        """
        ses_client = EmailService._get_ses_client()
        
        print(f"[DEBUG] SES client created. AWS_SES_REGION: {settings.AWS_SES_REGION}")
        print(f"[DEBUG] AWS_ACCESS_KEY_ID configured: {bool(settings.AWS_ACCESS_KEY_ID)}")
        print(f"[DEBUG] AWS_SECRET_ACCESS_KEY configured: {bool(settings.AWS_SECRET_ACCESS_KEY)}")
        print(f"[DEBUG] EMAIL_FROM_ADDRESS: {settings.EMAIL_FROM_ADDRESS}")
        
        try:
            print(f"[DEBUG] Calling boto3 ses_client.send_email...")
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
            
            message_id = response.get('MessageId')
            logger.info(f"Email sent successfully to {to_email}. MessageId: {message_id}")
            return True, message_id, None
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            error_details = f"{error_code} - {error_message}"
            logger.error(f"Failed to send email to {to_email}. Error: {error_details}")
            
            # Common errors:
            # - MessageRejected: Email address not verified (SES sandbox mode)
            # - InvalidParameterValue: Invalid email format
            # - ConfigurationSetDoesNotExist: Configuration set doesn't exist
            
            return False, None, error_details
            
        except Exception as e:
            error_msg = f"Unexpected error sending email to {to_email}: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return False, None, str(e)
    
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
        print(f"[DEBUG] EmailService.send_email called for {to_email}, subject: {subject}")
        logger.info(f"Attempting to send email to {to_email} with subject: {subject}")
        
        # Run the blocking boto3 call in a thread pool to avoid blocking the event loop
        try:
            print(f"[DEBUG] Calling _send_email_sync in thread pool...")
            success, message_id, error = await asyncio.to_thread(
                cls._send_email_sync,
                to_email,
                subject,
                html_body,
                text_body
            )
            
            print(f"[DEBUG] _send_email_sync returned: success={success}, message_id={message_id}, error={error}")
            if success:
                logger.info(f"Email sent successfully to {to_email}. MessageId: {message_id}")
                return True
            else:
                print(f"[DEBUG] Email sending failed: {error}")
                logger.error(f"Failed to send email to {to_email}. Error: {error}")
                return False
                
        except Exception as e:
            print(f"[DEBUG] Exception in send_email: {str(e)}")
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")
            logger.error(f"Exception in send_email for {to_email}: {str(e)}")
            logger.error(traceback.format_exc())
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
