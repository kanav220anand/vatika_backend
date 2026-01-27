"""Email templates for password reset and other emails."""


def get_password_reset_email(user_name: str, reset_url: str) -> tuple[str, str]:
    """
    Get HTML and plain text versions of password reset email.
    
    Args:
        user_name: Name of the user
        reset_url: Password reset URL with token
        
    Returns:
        Tuple of (html_body, text_body)
    """
    
    # HTML version with styling
    html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset Your Password</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 40px 20px;">
        <tr>
            <td align="center">
                <!-- Email Container -->
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow: hidden;">
                    
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); padding: 40px 40px 30px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600;">🌱 Vatisha</h1>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <h2 style="margin: 0 0 20px; color: #1f2937; font-size: 24px; font-weight: 600;">Reset Your Password</h2>
                            
                            <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                Hi {user_name},
                            </p>
                            
                            <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                We received a request to reset your password for your Vatisha account.
                            </p>
                            
                            <p style="margin: 0 0 30px; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                Click the button below to create a new password:
                            </p>
                            
                            <!-- Reset Button -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center" style="padding: 0 0 30px;">
                                        <a href="{reset_url}" style="display: inline-block; background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 12px; font-size: 16px; font-weight: 600; box-shadow: 0 4px 12px rgba(34, 197, 94, 0.3);">
                                            Reset Password
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Alternative Link -->
                            <p style="margin: 0 0 20px; color: #6b7280; font-size: 14px; line-height: 1.6;">
                                Or copy and paste this link into your browser:
                            </p>
                            <p style="margin: 0 0 30px; color: #22c55e; font-size: 14px; word-break: break-all;">
                                {reset_url}
                            </p>
                            
                            <!-- Expiration Notice -->
                            <div style="background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 16px; border-radius: 8px; margin-bottom: 30px;">
                                <p style="margin: 0; color: #92400e; font-size: 14px; line-height: 1.6;">
                                    ⏰ This link will expire in <strong>1 hour</strong> for security reasons.
                                </p>
                            </div>
                            
                            <p style="margin: 0 0 10px; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                If you didn't request this password reset, you can safely ignore this email.
                            </p>
                            
                            <p style="margin: 0; color: #4b5563; font-size: 16px; line-height: 1.6;">
                                Your password will remain unchanged until you create a new one.
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f9fafb; padding: 30px 40px; border-top: 1px solid #e5e7eb;">
                            <p style="margin: 0 0 10px; color: #6b7280; font-size: 14px; line-height: 1.6;">
                                Best regards,<br>
                                <strong>The Vatisha Team</strong> 🌿
                            </p>
                            
                            <p style="margin: 20px 0 0; color: #9ca3af; font-size: 12px; line-height: 1.6;">
                                Need help? Reply to this email or visit our support page.
                            </p>
                        </td>
                    </tr>
                    
                </table>
                
                <!-- Footer Text -->
                <p style="margin: 20px 0 0; color: #9ca3af; font-size: 12px; text-align: center;">
                    © 2026 Vatisha. Your personal plant care companion.
                </p>
            </td>
        </tr>
    </table>
</body>
</html>
    """
    
    # Plain text version
    text_body = f"""
Reset Your Password

Hi {user_name},

We received a request to reset your password for your Vatisha account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour for security reasons.

If you didn't request this password reset, you can safely ignore this email. Your password will remain unchanged until you create a new one.

Best regards,
The Vatisha Team 🌿

---
Need help? Reply to this email or visit our support page.

© 2026 Vatisha. Your personal plant care companion.
    """
    
    return (html_body.strip(), text_body.strip())
