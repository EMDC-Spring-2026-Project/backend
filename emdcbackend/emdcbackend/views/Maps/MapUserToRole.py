import logging

from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated

from ...auth.serializers import UserSerializer
from ...models import (
    MapUserToRole,
    Coach,
    Organizer,
    Judge,
    Admin,
    MapContestToJudge,
    MapContestToOrganizer,
)
from ...serializers import MapUserToRoleSerializer, CoachSerializer, OrganizerSerializer, JudgeSerializer, AdminSerializer
from django.shortcuts import get_object_or_404

logger = logging.getLogger(__name__)

#from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import SessionAuthentication
from django.shortcuts import get_object_or_404


def _is_admin(user):
    return user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists()


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_user_role_mapping(request):
    if not _is_admin(request.user):
        return Response(
            {"detail": "Administrator access required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    try:
        # Call the function that creates the user-role mapping
        mapping = create_user_role_map(request.data)  # This function can raise ValidationError
        return Response(mapping, status=status.HTTP_201_CREATED)  # If successful, return the mapping

    except ValidationError as e:
        # Handle validation errors and return a 400 response
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)

    except Exception:
        logger.exception("Unexpected error while creating user-role mapping")
        return Response(
            {"detail": "Unable to save the user role due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(['GET'])
def login_return(request, userid):
    return Response(get_role(userid), status=status.HTTP_200_OK)


def _can_view_role_account(user, relatedid, role_type):
    if _is_admin(user):
        return True

    current_role = MapUserToRole.objects.filter(uuid=user.id).first()
    if not current_role:
        return False

    # Users may view their own account identifier.
    if current_role.role == role_type and current_role.relatedid == relatedid:
        return True

    # Organizers need a judge's account identifier to manage that judge from
    # their contest dashboard. A judge can be shared across contests, so only
    # expose it when this organizer manages every contest assigned to them.
    if (
        role_type != MapUserToRole.RoleEnum.JUDGE
        or current_role.role != MapUserToRole.RoleEnum.ORGANIZER
    ):
        return False

    contest_ids = set(
        MapContestToJudge.objects.filter(judgeid=relatedid)
        .values_list("contestid", flat=True)
    )
    if not contest_ids:
        return False

    managed_contest_ids = set(
        MapContestToOrganizer.objects.filter(
            organizerid=current_role.relatedid,
            contestid__in=contest_ids,
        ).values_list("contestid", flat=True)
    )
    return contest_ids.issubset(managed_contest_ids)

@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_user_by_role(request, relatedid, roleType):
    try:
        if not _can_view_role_account(request.user, relatedid, roleType):
            return Response(
                {"detail": "You are not allowed to view this account."},
                status=status.HTTP_403_FORBIDDEN,
            )
        mapping = MapUserToRole.objects.get(relatedid=relatedid, role=roleType)
        uuid = mapping.uuid
        user = get_object_or_404(User, id=uuid)
        serializer = UserSerializer(instance=user)
        return Response({"User": serializer.data}, status=status.HTTP_200_OK)
    except MapUserToRole.DoesNotExist:
        # MapUserToRole should always exist, but handle gracefully if it doesn't
        return Response(
            {"error": f"User role mapping not found for relatedid={relatedid}, role={roleType}. This is a data integrity issue."},
            status=status.HTTP_404_NOT_FOUND
        )

@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_admin_by_user(request, userid):
    mapping = MapUserToRole.objects.get(uuid=userid)
    if mapping.role != 1:
        return Response("Error: Given User is Not an Admin", status=status.HTTP_404_NOT_FOUND)
    else:
        adminid = mapping.relatedid
        admin = Admin.objects.get(id=adminid)
        serializer = AdminSerializer(instance=admin)
        return Response({"Admin": serializer.data}, status=status.HTTP_200_OK)

@api_view(["delete"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_user_role_mapping(request, mapping_id):
    if not _is_admin(request.user):
        return Response(
            {"detail": "Administrator access required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    mapping = get_object_or_404(MapUserToRole, id=mapping_id)
    mapping.delete()
    return Response({"detail": "Mapping deleted successfully."}, status=status.HTTP_200_OK)

def get_role(user_id):
    try:
        mapping = MapUserToRole.objects.get(uuid=user_id)
    except MapUserToRole.DoesNotExist:
        # If no role mapping exists, this user has no assigned role
        # This could happen if role assignment failed during creation
        raise ValidationError(f"No role mapping found for user {user_id}. User may need role reassignment.")

    if mapping.role == 1:
        admin = Admin.objects.get(id=mapping.relatedid)
        roleSerializer = AdminSerializer(instance=admin)
        return {"user_type": mapping.role, "user": roleSerializer.data}

    elif mapping.role == 2:
        organizer = Organizer.objects.get(id=mapping.relatedid)
        roleSerializer = OrganizerSerializer(instance=organizer)
        return {"user_type": mapping.role, "user": roleSerializer.data}

    elif mapping.role == 3:
        judge = Judge.objects.get(id=mapping.relatedid)
        roleSerializer = JudgeSerializer(instance=judge)
        return {"user_type": mapping.role, "user": roleSerializer.data}

    elif mapping.role == 4:
        coach = Coach.objects.get(id=mapping.relatedid)
        roleSerializer = CoachSerializer(instance=coach)
        return {"user_type": mapping.role, "user": roleSerializer.data}

def create_user_role_map(mapData):
    # Check for existing mapping with same user and role
    existing_mapping = MapUserToRole.objects.filter(
        uuid=mapData.get("uuid"),
        role=mapData.get("role"),
        relatedid=mapData.get("relatedid")
    ).first()
    
    if existing_mapping:
        # Return existing mapping data instead of creating duplicate
        serializer = MapUserToRoleSerializer(existing_mapping)
        return serializer.data
    
    # Check if user has any other role mappings and clean them up
    # Users can only have one role, so we delete other mappings
    other_mappings = MapUserToRole.objects.filter(uuid=mapData.get("uuid"))
    if other_mappings.exists():
        other_mappings.delete()

    serializer = MapUserToRoleSerializer(data=mapData)
    if serializer.is_valid():
        serializer.save()
        return serializer.data

    raise ValidationError(serializer.errors)

def get_role_mapping(uuid):
    existing_mapping = MapUserToRole.objects.filter(uuid=uuid).first()
    serializer = MapUserToRoleSerializer(instance=existing_mapping)
    return serializer.data

def ensure_role_mappings():
    """
    Utility function to ensure all role entities have corresponding MapUserToRole entries.
    This can be called to fix data integrity issues.
    """
    issues_fixed = 0

    # Note: Removed debug prints for missing role mappings
    # If you need to check for missing mappings, re-add logic here

    return issues_fixed
