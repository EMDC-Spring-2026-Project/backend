from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.contrib.auth.models import User
from ..models import Organizer, Teams, Scoresheet, MapScoresheetToTeamJudge, MapContestToOrganizer, MapContestToTeam
from ..serializers import OrganizerSerializer, TeamSerializer
from ..auth.views import create_user, delete_user
from .Maps.MapUserToRole import create_user_role_map
from .Maps.MapContestToOrganizer import map_contest_to_organizer
from ..models import MapUserToRole
from ..auth.views import delete_user_by_id


from django.contrib.auth import get_user_model
from ..auth.password_utils import send_set_password_email
from django.contrib.sessions.models import Session


def _can_manage_team(user, team_id):
    if user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists():
        return True
    organizer_ids = MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
    ).values_list("relatedid", flat=True)
    contest_ids = MapContestToTeam.objects.filter(teamid=team_id).values_list("contestid", flat=True)
    return MapContestToOrganizer.objects.filter(
        contestid__in=contest_ids, organizerid__in=organizer_ids
    ).exists()

# get organizer by id
@api_view(["GET"])
def organizer_by_id(request, organizer_id):
    organizer = get_object_or_404(Organizer, id=organizer_id)
    serializer = OrganizerSerializer(instance=organizer)
    return Response({"organizer": serializer.data}, status=status.HTTP_200_OK)

# create an organizer
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_organizer(request):
    try:
        with transaction.atomic():
            user_response, organizer_response = create_user_and_organizer(request.data)  # creates user and organizer
            responses = [
                create_user_role_map({  # maps the newly-created user to the role of an organizer
                    "uuid": user_response.get("user").get("id"),
                    "role": 2,
                    "relatedid": organizer_response.get("id")
                }),
            ]
            for response in responses:
                if isinstance(response, Response):
                    return response
                
            return Response({
                "user": user_response,
                "organizer": organizer_response,
                "user_map": responses[0],
            }, status=status.HTTP_201_CREATED)

    except ValidationError as e:  # Catching ValidationErrors specifically
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
  
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def create_user_and_organizer(data):
    # IMPORTANT: Organizers use ONLY the shared organizer password (role=2)
    # (mirror behavior from your other file: no email; enforce unusable password flow)
    # Check for duplicate account before creating
    username = data.get("username")
    if username:
        existing_user = User.objects.filter(username=username).first()
        if existing_user:
            # Check if this user already has an organizer role mapping
            existing_organizer_mapping = MapUserToRole.objects.filter(
                uuid=existing_user.id,
                role=2  # Organizer role
            ).first()
            if existing_organizer_mapping:
                # Get organizer details for better error message
                try:
                    existing_organizer = Organizer.objects.get(id=existing_organizer_mapping.relatedid)
                    raise ValidationError({"detail": f'An account already exists under the name "{existing_organizer.first_name} {existing_organizer.last_name}" with username "{username}".'})
                except Organizer.DoesNotExist:
                    raise ValidationError({"detail": f'An account already exists with username "{username}".'})
    
    user_data = {"username": data["username"], "password": data["password"]}
    user_response = create_user(user_data, send_email=False, enforce_unusable_password=True)
    if not user_response.get('user'):
        raise ValidationError({"detail": "User creation failed."})
    
    # (Email intentionally NOT sent for organizers)
    organizer_data = {"first_name": data["first_name"], "last_name": data["last_name"]}
    organizer_response = make_organizer(organizer_data)
    if not organizer_response.get('id'):
        raise ValidationError('Organizer creation failed.')
    
    return user_response, organizer_response

def make_organizer(organizer_data):
    serializer = OrganizerSerializer(data=organizer_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    raise ValidationError(serializer.errors)

# edit an organizer
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_organizer(request):
    try:
        organizer = get_object_or_404(Organizer, id=request.data["id"])
        
        # Use filter().first() instead of get() to handle missing mappings gracefully
        organizer_mapping = MapUserToRole.objects.filter(
            role=MapUserToRole.RoleEnum.ORGANIZER, 
            relatedid=organizer.id
        ).first()
        
        # Update username if mapping exists
        if organizer_mapping:
            user_id = organizer_mapping.uuid
            try:
                user = User.objects.get(id=user_id)
                user.username = request.data["username"]
                user.save()
            except User.DoesNotExist:
                # User doesn't exist, skip username update
                pass
        
        # Update organizer details
        organizer.first_name = request.data["first_name"]
        organizer.last_name = request.data["last_name"]
        organizer.save()
        
        serializer = OrganizerSerializer(instance=organizer)
        return Response({"organizer": serializer.data}, status=status.HTTP_200_OK)
    
    except Organizer.DoesNotExist:
        return Response({"error": "Organizer not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
def delete_organizer(request, organizer_id):
    try:
        with transaction.atomic():
            # Fetch the organizer
            organizer = get_object_or_404(Organizer, id=organizer_id)

            # Delete the mappings between the organizer and contests
            MapContestToOrganizer.objects.filter(organizerid=organizer_id).delete()

            # Fetch and delete the organizer-user mapping
            organizer_mapping = MapUserToRole.objects.filter(role=MapUserToRole.RoleEnum.ORGANIZER, relatedid=organizer_id).first()
            if organizer_mapping:
                user_id = organizer_mapping.uuid
                organizer_mapping.delete()  # Delete the mapping
                
                # Invalidate all active sessions for this user before deleting user
                _delete_user_sessions(user_id)
                
                # Delete the user associated with the organizer (if it exists)
                try:
                    from django.contrib.auth.models import User
                    user = User.objects.get(id=user_id)
                    user.delete()
                except User.DoesNotExist:
                    # User doesn't exist, continue with deletion
                    pass
            
            organizer.delete()  # Delete the organizer

            return Response({"Detail": "Organizer and all related mappings deleted successfully."},
                            status=status.HTTP_200_OK)

    except Organizer.DoesNotExist:
        return Response({"error": "Organizer not found."}, status=status.HTTP_404_NOT_FOUND)
    except MapUserToRole.DoesNotExist:
        return Response({"error": "Organizer mapping not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# return all organizers
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_all_organizers(request):
    organizers = Organizer.objects.all()
    serializer = OrganizerSerializer(organizers, many=True)
    return Response({"organizers": serializer.data}, status=status.HTTP_200_OK)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def organizer_disqualify_team(request):
    team_id = request.data.get("teamid")
    if team_id is None or "organizer_disqualified" not in request.data:
        return Response({"detail": "teamid and organizer_disqualified are required."}, status=status.HTTP_400_BAD_REQUEST)
    team = get_object_or_404(Teams, id=team_id)
    if not _can_manage_team(request.user, team.id):
        return Response({"detail": "You are not allowed to disqualify this team."}, status=status.HTTP_403_FORBIDDEN)
    team.organizer_disqualified = request.data["organizer_disqualified"]
    if team.judge_disqualified == True and team.organizer_disqualified == True:
        team.cluster_rank = None
        team.team_rank = None
        scoresheetmappings = MapScoresheetToTeamJudge.objects.filter(teamid=team.id)
        for mapping in scoresheetmappings:
            scoresheet = Scoresheet.objects.get(id=mapping.scoresheetid)
            scoresheet.isSubmitted = True
            scoresheet.save()
    team.save()
    serializer = TeamSerializer(team)
    return Response({"team": serializer.data}, status=status.HTTP_200_OK)
