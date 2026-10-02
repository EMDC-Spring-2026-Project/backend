from django.core.exceptions import FieldError
from django.shortcuts import get_object_or_404
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
from ...models import (
    SpecialAward, MapUserToRole, MapContestToOrganizer, MapContestToJudge,
    MapContestToTeam,
)
from ...serializers import SpecialAwardSerializer
# FILE OVERVIEW: This file contains all views associated with the special awards URLs


def _role_ids(user, role):
    return MapUserToRole.objects.filter(
        uuid=user.id, role=role
    ).values_list("relatedid", flat=True)


def _is_admin(user):
    return user.is_superuser or _role_ids(
        user, MapUserToRole.RoleEnum.ADMIN
    ).exists()


def _is_organizer(user):
    return _role_ids(user, MapUserToRole.RoleEnum.ORGANIZER).exists()


def _organizer_can_manage_team(user, team_id):
    if team_id == 0:
        return _is_organizer(user)
    contest_ids = set(MapContestToTeam.objects.filter(
        teamid=team_id
    ).values_list("contestid", flat=True))
    if not contest_ids:
        return False
    managed_contest_ids = set(MapContestToOrganizer.objects.filter(
        contestid__in=contest_ids,
        organizerid__in=_role_ids(user, MapUserToRole.RoleEnum.ORGANIZER),
    ).values_list("contestid", flat=True))
    return contest_ids.issubset(managed_contest_ids)


def _judge_can_assign_award(user, award, new_data):
    if not award.isJudge:
        return False
    if new_data.get("award_name", award.award_name) != award.award_name:
        return False
    if new_data.get("isJudge", award.isJudge) is not True:
        return False
    team_id = new_data.get("teamid", award.teamid)
    if not team_id:
        return False
    judge_contest_ids = set(MapContestToJudge.objects.filter(
        judgeid__in=_role_ids(user, MapUserToRole.RoleEnum.JUDGE)
    ).values_list("contestid", flat=True))
    team_contest_ids = set(MapContestToTeam.objects.filter(
        teamid=team_id
    ).values_list("contestid", flat=True))
    return bool(team_contest_ids) and team_contest_ids.issubset(judge_contest_ids)

# POST request to create a new award team map
# Accepts JSON data if data is valid create map if not return 400/500 error 
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_award_team_mapping(request):
    team_id = request.data.get("teamid", 0)
    if not (
        _is_admin(request.user)
        or (_is_organizer(request.user) and _organizer_can_manage_team(request.user, team_id))
    ):
        return Response(
            {"detail": "Administrator or organizer access required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    try:
        serializer = SpecialAwardSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# GET request to get award_id by team_id
# Gets all award maps associated with a given team_id.
# Results should be visible even if the viewer isn't logged in, so we allow any.
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
def get_award_id_by_team_id(request, team_id):
    try:
        awards = SpecialAward.objects.filter(teamid=team_id)
        serializer = SpecialAwardSerializer(awards, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Delete award map by team_ID and award_name accepts these as URL params
# If it deletes properly 204 if not 404/500 code 
@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_award_team_mapping_by_id(request, team_id, award_name):
    try:
        award = SpecialAward.objects.get(teamid=team_id, award_name=award_name)
        if not (
            _is_admin(request.user)
            or _organizer_can_manage_team(request.user, award.teamid)
        ):
            return Response(
                {"detail": "You are not allowed to delete this award."},
                status=status.HTTP_403_FORBIDDEN,
            )
        award.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    except SpecialAward.DoesNotExist:
        return Response({"error": "Award not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# PUT request for updating an award map
# accepts team_id and award_name as url params
# If valid 200 if not 400/404/500 code 
@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def update_award_team_mapping(request, team_id, award_name):
    try:
        award = SpecialAward.objects.get(teamid=team_id, award_name=award_name)
        target_team_id = request.data.get("teamid", award.teamid)
        can_manage = (
            _is_admin(request.user)
            or _organizer_can_manage_team(request.user, target_team_id)
            or _judge_can_assign_award(request.user, award, request.data)
        )
        if not can_manage:
            return Response(
                {"detail": "You are not allowed to update this award."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = SpecialAwardSerializer(award, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except SpecialAward.DoesNotExist:
        return Response({"error": "Award not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
# GET request that returns all awards
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_all_awards(request):
    try:
        award = SpecialAward.objects.all()
        serializer = SpecialAwardSerializer(award, many=True)
        return Response({"awards": serializer.data}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
# Get request to get get all awards based on isJudge boolean
# used in frontend pages for organizers and judge only show their respective awards
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_awards_by_role(request, isJudge):
    try:
        is_judge = isJudge.lower() == 'true'
        awards = SpecialAward.objects.filter(isJudge=is_judge)
        serializer = SpecialAwardSerializer(awards, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
