from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from ...models import (
    MapCoachToTeam, Coach, Teams, MapUserToRole, Contest, MapContestToTeam,
    MapContestToOrganizer,
)
from ...serializers import CoachToTeamSerializer, CoachSerializer, TeamSerializer


def _can_manage_team(user, team_id):
    if user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists():
        return True
    organizer_ids = list(MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
    ).values_list("relatedid", flat=True))
    contest_ids = list(MapContestToTeam.objects.filter(
        teamid=team_id
    ).values_list("contestid", flat=True))
    if not organizer_ids or not contest_ids:
        return False
    managed_contest_ids = set(MapContestToOrganizer.objects.filter(
        contestid__in=contest_ids, organizerid__in=organizer_ids
    ).values_list("contestid", flat=True))
    return set(contest_ids).issubset(managed_contest_ids)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_coach_team_mapping(request):
    team_id = request.data.get("teamid")
    if team_id is None:
        return Response(
            {"detail": "teamid is required."}, status=status.HTTP_400_BAD_REQUEST
        )
    if not _can_manage_team(request.user, team_id):
        return Response(
            {"detail": "You are not allowed to change this team's coach."},
            status=status.HTTP_403_FORBIDDEN,
        )
    serializer = CoachToTeamSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"mapping": serializer.data},status=status.HTTP_200_OK)
    return Response(
        serializer.errors, status=status.HTTP_400_BAD_REQUEST
    )

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def teams_by_coach_id(request, coach_id):
    mappings = MapCoachToTeam.objects.filter(coachid=coach_id)
    team_ids = mappings.values_list('teamid', flat=True)
    teams = Teams.objects.filter(id__in=team_ids).order_by('-id')
    
    # Get contests for these teams and check if results should be hidden
    team_contest_map = {}
    for team in teams:
        contest_mapping = MapContestToTeam.objects.filter(teamid=team.id).first()
        if contest_mapping:
            team_contest_map[team.id] = contest_mapping.contestid
    
    team_data = []
    for team in teams:
        team_dict = TeamSerializer(instance=team).data
        contest_id = team_contest_map.get(team.id)
        if contest_id:
            try:
                contest = Contest.objects.get(id=contest_id)
                # Hide scores if contest is open or not tabulated
                if getattr(contest, 'is_open', False) or not getattr(contest, 'is_tabulated', False):
                    # Clear all score fields
                    team_dict['journal_score'] = 0
                    team_dict['presentation_score'] = 0
                    team_dict['machinedesign_score'] = 0
                    team_dict['penalties_score'] = 0
                    team_dict['redesign_score'] = 0
                    team_dict['championship_score'] = 0
                    team_dict['total_score'] = 0
                    team_dict['team_rank'] = None
            except Contest.DoesNotExist:
                pass
        team_data.append(team_dict)
    
    return Response({"Teams": team_data}, status=status.HTTP_200_OK)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def coach_by_team_id(request, team_id):
    try:
        mapping = MapCoachToTeam.objects.get(teamid=team_id)
        coach_id = mapping.coachid
        coach = Coach.objects.get(id=coach_id)
        serializer = CoachSerializer(instance=coach)
        return Response({"Coach": serializer.data}, status=status.HTTP_200_OK)
    except MapCoachToTeam.DoesNotExist:
        return Response({"error": "No coach found for the given team"}, status=status.HTTP_404_NOT_FOUND)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
def coaches_by_teams(request):
    teams = request.data  # Expecting a list of team data objects
    response_data = {}

    for team in teams:
        team_id = team.get("id")

        try:
            # Retrieve coach-team mapping
            mapping_coach_team = MapCoachToTeam.objects.get(teamid=team_id)
            coach = Coach.objects.get(id=mapping_coach_team.coachid)
            mapping_user_role = MapUserToRole.objects.get(relatedid=coach.id, role=4)
            uuid = mapping_user_role.uuid
            user = get_object_or_404(User, id=uuid)

            # Add to response dictionary with team ID as key
            response_data[team_id] = {
                "id": coach.id,
                "first_name": coach.first_name,
                "last_name": coach.last_name,
                "username": user.username
            }

        except MapCoachToTeam.DoesNotExist:
            response_data[team_id] = {"error": "No coach assigned to this team"}
        except User.DoesNotExist:
            response_data[team_id] = {"error": "User not found for coach"}

    return Response(response_data, status=status.HTTP_200_OK)
    
@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_coach_team_mapping_by_id(request, map_id):
    map_to_delete = get_object_or_404(MapCoachToTeam, id=map_id)
    if not _can_manage_team(request.user, map_to_delete.teamid):
        return Response(
            {"detail": "You are not allowed to change this team's coach."},
            status=status.HTTP_403_FORBIDDEN,
        )
    map_to_delete.delete()
    return Response({"detail": "Coach To Team Mapping deleted successfully."}, status=status.HTTP_200_OK)

def create_coach_to_team_map(map_data):
    serializer = CoachToTeamSerializer(data=map_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    else:
        raise ValidationError(serializer.errors)
