# backend/emdcbackend/emdcbackend/auth/password_views.py
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
import os

from .password_utils import build_set_password_url
from .utils import send_email_via_resend


# 1) Admin-only re-sends a set-password email (auth required)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def request_set_password(request):
    """
    Body: { "username": "<email>" }
    Sends a set-password link to the user's email. Typically used for first-time users.
    Only admins (role 1) can use this endpoint.
    """
    # Check if user is an admin (role = 1)
    from ..models import MapUserToRole
    try:
        user_role_mapping = MapUserToRole.objects.get(uuid=request.user.id)
        if user_role_mapping.role != 1:  # 1 = ADMIN
            return Response({
                "detail": "Only administrators can resend password emails.",
                "error": "Permission denied."
            }, status=status.HTTP_403_FORBIDDEN)
    except MapUserToRole.DoesNotExist:
        return Response({
            "detail": "Only administrators can resend password emails.",
            "error": "User role not found."
        }, status=status.HTTP_403_FORBIDDEN)
    
    username = request.data.get("username")
    if not username:
        return Response({"detail": "username (email) is required."}, status=status.HTTP_400_BAD_REQUEST)

    user = get_object_or_404(User, username=username)

    url = build_set_password_url(user)
    subject = "Set your password - EMDC Contest"
    timeout_minutes = getattr(settings, 'PASSWORD_RESET_TIMEOUT', 3600) // 60
    
    # Plain text version
    text_content = f"""Hello,

Please click the link below to set your password:

{url}

This link will expire in {timeout_minutes} minutes.

If you did not request this, you can safely ignore this email.

---
EMDC Contest Management System
"""
    
    # Professional HTML version
    html_content = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #2563eb;">Set Your Password</h2>
    
    <p>Hello,</p>
    
    <p>Please click the button below to set your password:</p>
    
    <div style="margin: 30px 0;">
        <a href="{url}" 
           style="background-color: #2563eb; 
                  color: white; 
                  padding: 12px 24px; 
                  text-decoration: none; 
                  border-radius: 5px;
                  display: inline-block;
                  font-weight: bold;">
            Set Password
        </a>
    </div>
    
    <p>Or copy and paste this link into your browser:</p>
    <p style="background-color: #f3f4f6; padding: 10px; border-radius: 5px; word-break: break-all; font-family: monospace; font-size: 12px;">
        {url}
    </p>
    
    <p style="color: #dc2626; margin-top: 30px; font-weight: bold;">
        ⏰ This link will expire in {timeout_minutes} minutes.
    </p>
    
    <p style="color: #6b7280;">
        If you did not request this, you can safely ignore this email.
    </p>
    
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
    
    <p style="color: #9ca3af; font-size: 12px;">
        EMDC Contest Management System<br>
        This is an automated email, please do not reply.
    </p>
</div>
"""
    
    # Use Resend SDK to send email
    try:
        send_email_via_resend(
            to_email=user.username,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
    except Exception as e:
        # Log the error but don't expose internal details to user
        print(f"[ERROR] Failed to send set-password email: {e}")
        return Response({
            "detail": "Failed to send set-password email. Please check your email configuration or contact support.",
            "error": "Email sending failed."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({"detail": "Set-password email sent."}, status=status.HTTP_200_OK)


# 2) Public "Forgot Password" - Admin and Coach only
# Note: In production, add rate limiting to prevent abuse
@api_view(["POST"])
@permission_classes([AllowAny])
def request_password_reset(request):
    """
    Body: { "username": "<email>" }
    Only admins (role 1) and coaches (role 4) can reset their password. Other users must contact an administrator.
    """
    username = request.data.get("username")
    if not username:
        return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        # Return generic message to avoid user enumeration
        return Response({
            "detail": "If this email belongs to an admin or coach, a reset link has been sent."
        }, status=status.HTTP_200_OK)
    
    # Check if user is an admin (role = 1) or coach (role = 4)
    from ..models import MapUserToRole
    try:
        user_role_mapping = MapUserToRole.objects.get(uuid=user.id)
        if user_role_mapping.role not in [1, 4]:  # 1 = ADMIN, 4 = COACH
            return Response({
                "detail": "If this email belongs to an admin or coach, a reset link has been sent."
            }, status=status.HTTP_200_OK)
    except MapUserToRole.DoesNotExist:
        # Use the same response as an unknown address so this public endpoint does
        # not reveal which email addresses have accounts.
        return Response({
            "detail": "If this email belongs to an admin or coach, a reset link has been sent."
        }, status=status.HTTP_200_OK)
    
    # User is an admin or coach - send reset email
    url = build_set_password_url(user)
    subject = "Reset your password - EMDC Contest"
    timeout_minutes = getattr(settings, 'PASSWORD_RESET_TIMEOUT', 3600) // 60
    
    # Plain text version
    text_content = f"""Hello,

Please click the link below to reset your password:

{url}

This link will expire in {timeout_minutes} minutes.

If you did not request a password reset, you can safely ignore this email.

---
EMDC Contest Management System
"""
    
    # Professional HTML version
    html_content = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #2563eb;">Reset Your Password</h2>
    
    <p>Hello,</p>
    
    <p>We received a request to reset your password. Click the button below to continue:</p>
    
    <div style="margin: 30px 0;">
        <a href="{url}" 
           style="background-color: #2563eb; 
                  color: white; 
                  padding: 12px 24px; 
                  text-decoration: none; 
                  border-radius: 5px;
                  display: inline-block;
                  font-weight: bold;">
            Reset Password
        </a>
    </div>
    
    <p>Or copy and paste this link into your browser:</p>
    <p style="background-color: #f3f4f6; padding: 10px; border-radius: 5px; word-break: break-all; font-family: monospace; font-size: 12px;">
        {url}
    </p>
    
    <p style="color: #dc2626; margin-top: 30px; font-weight: bold;">
        ⏰ This link will expire in {timeout_minutes} minutes.
    </p>
    
    <p style="color: #6b7280;">
        If you did not request a password reset, you can safely ignore this email.
    </p>
    
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
    
    <p style="color: #9ca3af; font-size: 12px;">
        EMDC Contest Management System<br>
        This is an automated email, please do not reply.
    </p>
</div>
"""
    
    # Use Resend SDK to send email
    try:
        send_email_via_resend(
            to_email=user.username,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
    except Exception as e:
        # Log the error but don't expose internal details to user
        print(f"[ERROR] Failed to send password reset email: {e}")
        return Response({
            "detail": "Failed to send password reset email. Please check your email configuration or contact support.",
            "error": "Email sending failed."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response({"detail": "If this email belongs to an admin or coach, a reset link has been sent."}, status=status.HTTP_200_OK)


# 3) Frontend can validate token before showing the set-password form
@api_view(["POST"])
@permission_classes([AllowAny])
def validate_password_token(request):
    """
    Body: { "uid": "<uidb64>", "token": "<token>" }
    """
    uidb64 = request.data.get("uid")
    token = request.data.get("token")
    if not uidb64 or not token:
        return Response({"detail": "uid and token are required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)

    if default_token_generator.check_token(user, token):
        return Response({"detail": "Token valid."}, status=status.HTTP_200_OK)
    return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)


# 4) Complete password set/reset
@api_view(["POST"])
@permission_classes([AllowAny])
def complete_password_set(request):
    """
    Body: { "uid": "<uidb64>", "token": "<token>", "password": "<new_password>" }
    Enforces Django's password validators.
    """
    uidb64 = request.data.get("uid")
    token = request.data.get("token")
    password = request.data.get("password")

    if not uidb64 or not token or not password:
        return Response({"detail": "uid, token, and password are required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)

    if not default_token_generator.check_token(user, token):
        return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        from django.contrib.auth.password_validation import validate_password
        validate_password(password, user=user)  # uses AUTH_PASSWORD_VALIDATORS
    except Exception as e:
        return Response({"password": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(password)
    user.save()
    
    # Note: In production, consider invalidating the token after use to prevent reuse
    # Django's default_token_generator tokens are single-use by design (they change when password changes)
    # But if you want explicit invalidation, you could store used tokens in cache/db
    
    return Response({"detail": "Password has been set."}, status=status.HTTP_200_OK)
