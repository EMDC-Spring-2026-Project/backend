from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.hashers import make_password
from django.db import transaction
from ..models import RoleSharedPassword
from ..permissions import is_admin_user

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def set_shared_password(request):
    """
    Admin sets/overwrites the GLOBAL shared password for a role.
    Body:
      {
        "role": 2 or 3,   # 2=Organizer, 3=Judge
        "password": "new-shared-pass"
      }
    """
    if not is_admin_user(request.user):
        return Response({"error": "Only admins can set shared passwords."}, status=403)
    
    role = request.data.get("role")
    password = request.data.get("password")

    # Ensure role is an integer
    try:
        role = int(role)
    except (TypeError, ValueError):
        return Response({"error": "role must be 2 (Organizer) or 3 (Judge)."}, status=400)

    if role not in [2, 3]:
        return Response({"error": "role must be 2 (Organizer) or 3 (Judge)."}, status=400)
    if not password:
        return Response({"error": "password is required."}, status=400)

    # Validate password using Django's password validators
    try:
        from django.contrib.auth.password_validation import validate_password
        validate_password(password)  # Uses AUTH_PASSWORD_VALIDATORS from settings
    except Exception as e:
        # Extract error messages from validation
        error_messages = []
        if hasattr(e, 'messages'):
            error_messages = e.messages
        elif hasattr(e, 'error_list'):
            error_messages = [str(err) for err in e.error_list]
        else:
            error_messages = [str(e)]
        
        return Response({
            "error": "Password does not meet requirements.",
            "detail": error_messages[0] if error_messages else "Password validation failed."
        }, status=400)

    # Use database transaction to ensure atomic replacement
    with transaction.atomic():
        # Get existing entry if it exists
        existing = RoleSharedPassword.objects.filter(role=role).first()
        
        # Create new password hash
        hashed = make_password(password)
        
        if existing:
            # Update existing entry - this ensures old password is immediately invalidated
            existing.password_hash = hashed
            existing.save()  # This updates updated_at timestamp automatically
        else:
            # Create new entry if none exists
            RoleSharedPassword.objects.create(
                role=role,
                password_hash=hashed
            )
        
        # Verify only one entry exists for this role
        count = RoleSharedPassword.objects.filter(role=role).count()
        if count != 1:
            return Response({
                "error": f"Database inconsistency: found {count} entries for role {role}",
                "detail": "Please contact support."
            }, status=500)
        
        # Double-check: Verify the password hash was actually updated
        updated_entry = RoleSharedPassword.objects.get(role=role)
        from django.contrib.auth.hashers import check_password
        if not check_password(password, updated_entry.password_hash):
            return Response({
                "error": "Password was not set correctly. Please try again.",
                "detail": "Please contact support."
            }, status=500)
    
    return Response({
        "success": True,
        "role": role,
        "message": "Shared password set successfully."
    }, status=200)
