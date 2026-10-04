# backend/emdcbackend/emdcbackend/auth/views.py
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError

# --- Added for password reset flow ---
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator

# --- Session-based login/logout ---
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.contrib.auth import authenticate, login as dj_login, logout as dj_logout
from django.contrib.auth.hashers import check_password
from ..models import MapUserToRole, RoleSharedPassword

from .serializers import UserSerializer

# --- Added utility for sending set-password emails ---
from .password_utils import send_set_password_email

# If you use role lookups elsewhere, keep your import the same:
from ..views.Maps.MapUserToRole import get_role



# -----------------------
# Session-based login/logout (HttpOnly cookies)
# -----------------------

def parse_body(request):
    if request.content_type == "application/json":
        import json
        return json.loads(request.body.decode("utf-8") or "{}")
    return request.POST



@csrf_exempt  # CSRF is handled via credentials here; also enables cross-domain frontend login
@ensure_csrf_cookie
@require_POST
def login_view(request):
    body = parse_body(request)
    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return JsonResponse({"detail": "username and password are required."}, status=400)

    user = None
    shared_password_checked = False

    # For Organizer (2) and Judge (3), check shared password FIRST
    # If shared password exists, ONLY use it (ignore individual passwords completely)
    try:
        fallback_user = User.objects.get(username=username)
        role_map = MapUserToRole.objects.filter(uuid=fallback_user.id).first()
        if role_map and role_map.role in [2, 3]:  # Organizer or Judge
            role_value = int(role_map.role)
            try:
                shared = RoleSharedPassword.objects.get(role=role_value)
                shared_password_checked = True
                password_matches = check_password(password, shared.password_hash)
                if password_matches:
                    user = fallback_user
                else:
                    # Shared password exists but doesn't match
                    return JsonResponse({
                        "detail": "Invalid credentials. Please use the shared password for your role."
                    }, status=401)
            except RoleSharedPassword.DoesNotExist:
                # Shared password not set yet - judges/organizers can't login until admin sets it
                role_name = "Organizer" if role_value == 2 else "Judge"
                return JsonResponse({
                    "detail": f"Shared password for {role_name}s has not been set yet. Please contact an administrator."
                }, status=401)
    except User.DoesNotExist:
        pass

    # For non-Organizer/Judge roles (Admin, Coach), use regular authentication
    # For Organizer/Judge: if shared password doesn't exist, login fails (they can't use individual passwords)
    # If shared_password_checked is True, we've already checked the shared password and it failed,
    # so we should NOT check individual passwords - login should fail.
    if not user and not shared_password_checked:
        user = authenticate(request, username=username, password=password)

    if not user:
        return JsonResponse({"detail": "Invalid credentials"}, status=401)

    try:
        role = get_role(user.id)
    except ValidationError:
        # Accounts without an EMDC role cannot use a dashboard. Return a clear
        # response rather than turning this data-integrity issue into a 500.
        return JsonResponse({
            "detail": "This account has not been assigned a contest role. Please contact an administrator."
        }, status=403)

    dj_login(request, user)  # sets the Django session HttpOnly cookie

    return JsonResponse({"user": {"id": user.id, "username": user.username}, "role": role})

@ensure_csrf_cookie
@require_POST
def logout_view(request):
    dj_logout(request)  # clears the session
    return JsonResponse({"detail": "logged out"})

@csrf_exempt
def csrf_view(request):
    from django.middleware.csrf import get_token
    from django.http import JsonResponse

    # Get the CSRF token (this sets it if not present)
    token = get_token(request)

    response = JsonResponse({"detail": "ok", "csrfToken": token})
    # Ensure the CSRF cookie is set
    response.set_cookie('csrftoken', token)
    return response


# -----------------------
# User queries / auth
# -----------------------

def _can_manage_user(request_user, target_user_id):
    """Return whether a user may view or change the requested account."""
    return (
        request_user.is_superuser
        or request_user.id == target_user_id
        or MapUserToRole.objects.filter(uuid=request_user.id, role=1).exists()
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def user_by_id(request, user_id):
    if not _can_manage_user(request.user, user_id):
        return Response(
            {"detail": "You do not have permission to view this user."},
            status=status.HTTP_403_FORBIDDEN,
        )
    user = get_object_or_404(User, id=user_id)
    serializer = UserSerializer(instance=user)
    return Response({"user": serializer.data}, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def signup(request):
    """
    Create an account from an authenticated administrator session.

    Public self-registration cannot assign an EMDC role and therefore creates an
    unusable account. Staff accounts should normally be created through the role
    management endpoints, which create the account and role together.
    """
    if not _can_manage_user(request.user, -1):
        return Response(
            {"detail": "Administrator access required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    try:
        user_data = request.data
        username = user_data.get("username")
        if not username:
            return Response({"detail": "username is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Do not return another account's details from an account-creation request.
        existing = User.objects.filter(username__iexact=username).first()
        if existing:
            return Response(
                {"detail": "An account with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = create_user(user_data, send_email=True, enforce_unusable_password=False)
        return Response(result, status=status.HTTP_201_CREATED)
    except ValidationError as e:
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_user_by_id(request, user_id):
    if not _can_manage_user(request.user, user_id):
        return Response(
            {"detail": "You do not have permission to delete this user."},
            status=status.HTTP_403_FORBIDDEN,
        )
    delete_user(user_id)
    return Response({"detail": "User deleted successfully."}, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_user(request):
    """
    Allows changing username (email) and/or password for the current user.
    Adds STRICT email validation on username change.
    """
    user_id = request.data.get("id")
    if user_id is None:
        return Response({"detail": "id is required."}, status=status.HTTP_400_BAD_REQUEST)

    user = get_object_or_404(User, id=user_id)
    if not _can_manage_user(request.user, user.id):
        return Response(
            {"detail": "You do not have permission to edit this user."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Update username (email) with strict validation
    new_username = request.data.get("username")
    if new_username and new_username != user.username:
        try:
            validate_email(new_username)  # STRICT format check
        except DjangoValidationError:
            return Response({"detail": "Enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username__iexact=new_username).exclude(id=user.id).exists():
            return Response({"detail": "Email already taken."}, status=status.HTTP_400_BAD_REQUEST)
        user.username = new_username

    # Update password (only if provided)
    new_password = request.data.get("password")
    if new_password:
        from django.contrib.auth.password_validation import validate_password
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response(
                {"password": list(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)

    user.save()
    serializer = UserSerializer(instance=user)
    return Response({"user": serializer.data})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def test_token(request):
    return Response({"passed for {}".format(request.user.username)})


# -----------------------
# Creation / deletion helpers
# -----------------------

def create_user(user_data, send_email: bool = True, enforce_unusable_password: bool = False):
    """
    Shared helper used by admin/organizer/judge creation and public signup.

    Preserves your original behavior:
      - If a user with username exists, return existing user data.

    Uses session-based authentication (no tokens returned).
    Adds STRICT email validation + optional set-password email.
    """
    username = user_data.get("username")
    password = user_data.get("password")

    # Strict email format
    if not username:
        raise ValidationError("Username (email) is required.")
    try:
        validate_email(username)
    except DjangoValidationError:
        raise ValidationError("Enter a valid email address.")

    # Preserve original: if existing user, return data instead of error
    existing_user = User.objects.filter(username=username).first()
    if existing_user:
        serializer = UserSerializer(instance=existing_user)
        return {"user": serializer.data}

    serializer = UserSerializer(data={"username": username, "password": password})
    if serializer.is_valid():
        with transaction.atomic():
            user = serializer.save()

            if enforce_unusable_password:
                user.set_unusable_password()
            else:
                if password:
                    # Validate password using Django's password validators
                    from django.contrib.auth.password_validation import validate_password
                    try:
                        validate_password(password, user=user)  # Uses AUTH_PASSWORD_VALIDATORS from settings
                    except Exception as e:
                        # Extract error messages from validation
                        error_messages = []
                        if hasattr(e, 'messages'):
                            error_messages = e.messages
                        elif hasattr(e, 'error_list'):
                            error_messages = [str(err) for err in e.error_list]
                        else:
                            error_messages = [str(e)]
                        raise ValidationError({"password": error_messages})
                    user.set_password(password)
                else:
                    user.set_unusable_password()

            user.save()
            if send_email:
                try:
                    send_set_password_email(user)
                except Exception as e:
                    # Do not fail creation if email fails (useful in dev)
                    print(f"[WARN] Failed to send set-password email: {e}")

            # Return serialized new user (match original return structure)
            return {"user": UserSerializer(instance=user).data}

    raise ValidationError(serializer.errors)


def delete_user(uuid):
    user_to_delete = get_object_or_404(User, id=uuid)
    user_to_delete.delete()


# -----------------------
# Password reset endpoints
# -----------------------
# NOTE: The main forgot password endpoint is in password_views.py (request_password_reset)
# This function is kept for backwards compatibility but is not used in URL routing.
# Use request_password_reset from password_views.py instead.

@api_view(["POST"])
def forgot_password(request):
    """
    DEPRECATED: Use request_password_reset from password_views.py instead.
    This endpoint is not registered in URLs and kept only for backwards compatibility.
    Only admins can reset their password. Other users must contact an administrator.
    """
    email = request.data.get("email")
    if not email:
        return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

    # Validate format strictly, but still avoid enumeration
    try:
        validate_email(email)
    except DjangoValidationError:
        return Response({"detail": "If this email exists, a reset link has been sent."},
                        status=status.HTTP_200_OK)

    try:
        user = User.objects.get(username=email)
        # Check if user is an admin (role = 1)
        try:
            user_role_mapping = MapUserToRole.objects.get(uuid=user.id)
            if user_role_mapping.role != 1:  # 1 = ADMIN
                return Response({
                    "detail": "Password reset is only available for administrators. Please contact an administrator for assistance.",
                    "error": "Only admins can reset passwords."
                }, status=status.HTTP_403_FORBIDDEN)
        except MapUserToRole.DoesNotExist:
            return Response({
                "detail": "Password reset is only available for administrators. Please contact an administrator for assistance.",
                "error": "User role not found."
            }, status=status.HTTP_403_FORBIDDEN)
        
        # User is an admin - send reset email
        send_set_password_email(user)
    except User.DoesNotExist:
        pass

    return Response({"detail": "If this email exists, a reset link has been sent."}, status=status.HTTP_200_OK)


@api_view(["POST"])
def password_reset_confirm(request):
    """
    Finalizes setting a new password.
    Payload:
      { "uid": "<base64 user id>", "token": "<token from email>", "new_password": "<new password>" }
    """
    uidb64 = request.data.get("uid")
    token = request.data.get("token")
    new_password = request.data.get("new_password")

    if not uidb64 or not token or not new_password:
        return Response({"detail": "uid, token and new_password are required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        return Response({"detail": "Invalid link."}, status=status.HTTP_400_BAD_REQUEST)

    if not default_token_generator.check_token(user, token):
        return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save()
    return Response({"detail": "Password has been set successfully."}, status=status.HTTP_200_OK)
