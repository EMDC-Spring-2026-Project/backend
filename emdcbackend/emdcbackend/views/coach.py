from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from ..auth.views import create_user
from ..models import Coach
from ..serializers import CoachSerializer
from ..models import MapUserToRole
from ..auth.views import User, delete_user
from ..auth.password_utils import send_set_password_email
from django.contrib.sessions.models import Session


def _is_admin(user):
    return user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists()


def _can_edit_coach(user, coach_id):
    return _is_admin(user) or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.COACH, relatedid=coach_id
    ).exists()

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def coach_by_id(request, coach_id):
  coach = get_object_or_404(Coach, id = coach_id)
  serializer = CoachSerializer(instance=coach)
  return Response({"Coach": serializer.data}, status=status.HTTP_200_OK)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def coach_get_all(request):
  coaches = Coach.objects.all()
  serializer = CoachSerializer(coaches, many=True)
  return Response({"Coaches":serializer.data}, status=status.HTTP_200_OK)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_coach(request):
    if not _is_admin(request.user):
        return Response({"detail": "Administrator access required."}, status=status.HTTP_403_FORBIDDEN)
    serializer = CoachSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"coach": serializer.data},status=status.HTTP_200_OK)
    return Response(
        serializer.errors, status=status.HTTP_400_BAD_REQUEST
    )

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_coach(request):
    coach = get_object_or_404(Coach, id=request.data["id"])
    if not _can_edit_coach(request.user, coach.id):
        return Response({"detail": "You cannot edit this coach profile."}, status=status.HTTP_403_FORBIDDEN)
    coach.first_name = request.data["first_name"]
    coach.last_name = request.data["last_name"]
    coach.school_name = request.data["school_name"]
    coach.save()

    serializer = CoachSerializer(instance=coach)
    return Response({"coach": serializer.data}, status=status.HTTP_200_OK)

def _delete_user_sessions(user_id: int) -> None:
    """
    Proactively invalidate all active sessions for the given user id.
    This ensures any existing session cookies become unusable immediately.
    """
    try:
        for session in Session.objects.all():
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) == str(user_id):
                session.delete()
    except Exception:
        pass


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_coach(request, coach_id):
    try:
        if not _is_admin(request.user):
            return Response({"detail": "Administrator access required."}, status=status.HTTP_403_FORBIDDEN)
        coach = get_object_or_404(Coach, id=coach_id)
        coach_mapping = MapUserToRole.objects.get(role=MapUserToRole.RoleEnum.COACH, relatedid=coach_id)
        user_id = coach_mapping.uuid
        
        # Invalidate all active sessions for this user before deleting user
        _delete_user_sessions(user_id)
        
        coach.delete()
        coach_mapping.delete()
        delete_user(user_id)
        return Response({"Detail": "Coach deleted successfully."}, status=status.HTTP_200_OK)
    except Coach.DoesNotExist:
        return Response({"error": "Coach not found."}, status=status.HTTP_404_NOT_FOUND)
    except MapUserToRole.DoesNotExist:
        return Response({"error": "Coach mapping not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def create_coach_instance(coach_data):
    serializer = CoachSerializer(data=coach_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    raise ValidationError("Coach creation failed")

def create_coach_only(data):
    coach_data = {
        "first_name": data["first_name"],
        "last_name": data.get("last_name", "") or ""  
    }
    coach_response = create_coach_instance(coach_data)
    if not coach_response.get('id'):
        raise ValidationError('Coach creation failed.')
    return coach_response

def create_user_and_coach(data):
    """
    Creates a new user account and coach profile.
    
    IMPORTANT: This function SENDS a set-password email to the coach.
    Only call this function when creating a BRAND NEW coach account.
    Do NOT call this for existing coaches to avoid sending duplicate emails.
    
    Args:
        data: Dictionary containing username, password, first_name, last_name
        
    Returns:
        Tuple of (user_response, coach_response)
    """
    user_data = {"username": data["username"], "password": data["password"]}
    # Create user with unusable password - coach will set it via email link
    user_response = create_user(user_data, send_email=False, enforce_unusable_password=True)
    if not user_response.get('user'):
        raise ValidationError('User creation failed.')
    
    coach_data = {
        "first_name": data["first_name"],
        "last_name": data.get("last_name", "") or "",  
    }
    coach_response = create_coach_instance(coach_data)
    if not coach_response.get('id'): 
        raise ValidationError('Coach creation failed.')
    
    # Send set-password email to the coach
    user_id = user_response.get("user", {}).get("id")
    if user_id:
        try:
            user = User.objects.get(id=user_id)
            print(f"[INFO] Sending set-password email to NEW coach: {user.username}")
            send_set_password_email(user, subject="Set your EMDC Coach account password")
            print(f"[SUCCESS] Set-password email sent successfully to: {user.username}")
        except Exception as e:
            # Log error but don't fail coach creation if email fails
            print(f"[ERROR] Failed to send set-password email to coach {user.username}: {e}")
    
    return user_response, coach_response

def get_coach(coach_id):
    coach = get_object_or_404(Coach, id = coach_id)
    serializer = CoachSerializer(instance=coach)
    return serializer.data
