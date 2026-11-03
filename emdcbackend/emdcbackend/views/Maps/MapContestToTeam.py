import logging

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
from ...models import MapContestToTeam, Contest, Teams, MapContestToOrganizer, MapUserToRole
from ...serializers import MapContestToTeamSerializer, ContestSerializer, TeamSerializer

logger = logging.getLogger(__name__)


def _can_manage_contest(user, contest_id):
  if user.is_superuser or MapUserToRole.objects.filter(
      uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
  ).exists():
      return True
  organizer_ids = MapUserToRole.objects.filter(
      uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
  ).values_list("relatedid", flat=True)
  return MapContestToOrganizer.objects.filter(
      contestid=contest_id, organizerid__in=organizer_ids
  ).exists()

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_contest_team_mapping(request):
  if not _can_manage_contest(request.user, request.data.get("contestid")):
      return Response({"detail": "You cannot manage this contest."}, status=status.HTTP_403_FORBIDDEN)
  serializer = MapContestToTeamSerializer(data=request.data)
  if serializer.is_valid():
      serializer.save()
      return Response({"mapping": serializer.data},status=status.HTTP_200_OK)
  return Response(
      serializer.errors, status=status.HTTP_400_BAD_REQUEST
  )

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
def get_teams_by_contest_id(request, contest_id):
    contest = get_object_or_404(Contest, id=contest_id)
    try:
        results_are_final = contest.results_published

        # Finalized scores are calculated when the organizer closes the contest.
        # Keep this public read endpoint fast; recalculating every score and rank
        # on each results-page visit can time out for larger contests.

        mappings = MapContestToTeam.objects.filter(contestid=contest_id)
        team_ids = mappings.values_list("teamid", flat=True)
        teams = Teams.objects.filter(id__in=team_ids).order_by("team_rank")
        serializer = TeamSerializer(teams, many=True)
        team_data = serializer.data
        if not results_are_final:
            score_fields = (
                "journal_score",
                "presentation_score",
                "machinedesign_score",
                "penalties_score",
                "redesign_score",
                "total_score",
                "championship_score",
                "preliminary_presentation_score",
                "preliminary_journal_score",
                "preliminary_machinedesign_score",
                "preliminary_penalties_score",
                "preliminary_total_score",
                "championship_presentation_score",
                "championship_machinedesign_score",
                "championship_penalties_score",
                "championship_general_penalties_score",
                "championship_run_penalties_score",
            )
            rank_fields = ("team_rank", "cluster_rank", "championship_rank")
            for team in team_data:
                for field in score_fields:
                    team[field] = 0
                for field in rank_fields:
                    team[field] = None
                team["advanced_to_championship"] = False
                team["judge_disqualified"] = False
                team["organizer_disqualified"] = False

        return Response(team_data, status=status.HTTP_200_OK)
    except Exception:
        logger.exception("Failed to load results for contest %s", contest_id)
        return Response(
            {"error": "Unable to load contest results."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_contest_id_by_team_id(request,team_id):
  try:
    contest_ids = MapContestToTeam.objects.filter(
      teamid=team_id
    ).values_list("contestid", flat=True).distinct()
    contests = Contest.objects.filter(id__in=contest_ids).order_by("id")
    contest_data = ContestSerializer(contests, many=True).data
    if not contest_data:
      return Response({"error": "No Contest Found for given Team"}, status=status.HTTP_404_NOT_FOUND)
    # Keep the legacy singular field while also returning every contest for
    # teams that participate in more than one contest.
    return Response(
      {"Contest": contest_data[0], "Contests": contest_data},
      status=status.HTTP_200_OK,
    )
  except MapContestToTeam.DoesNotExist:
    return Response({"error": "No Contest Found for given Team"}, status=status.HTTP_404_NOT_FOUND)
  except Exception:
    logger.exception("Unexpected error while loading contest for team %s", team_id)
    return Response(
        {"error": "Unable to load the team's contest due to a server error."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_contests_by_team_ids(request):
    if not isinstance(request.data, list) or not all(
        isinstance(team, dict) and isinstance(team.get("id"), int) and team["id"] > 0
        for team in request.data
    ):
        return Response(
            {"detail": "Request body must be a list of teams with positive integer id values."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        team_ids = [team["id"] for team in request.data]

        # Fetch mappings for the specified team IDs
        mappings = MapContestToTeam.objects.filter(teamid__in=team_ids)

        # Gather unique contest IDs from the mappings
        contest_ids = set(mapping.contestid for mapping in mappings)

        # Fetch the Contest objects based on these contest IDs
        contests = Contest.objects.filter(id__in=contest_ids)
        contest_data = {contest.id: ContestSerializer(contest).data for contest in contests}

        # Map each team ID to its contest data based on the mappings
        result = {
            mapping.teamid: contest_data.get(mapping.contestid)
            for mapping in mappings
        }

        return Response(result, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Unexpected error while loading contests for teams")
        return Response(
            {"error": "Unable to load team contests due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_contest_team_mapping_by_id(request, map_id):
    map_to_delete = get_object_or_404(MapContestToTeam, id=map_id)
    if not _can_manage_contest(request.user, map_to_delete.contestid):
        return Response({"detail": "You cannot manage this contest."}, status=status.HTTP_403_FORBIDDEN)
    map_to_delete.delete()
    return Response({"detail": "Contest To Team Mapping deleted successfully."}, status=status.HTTP_200_OK)


def create_team_to_contest_map(map_data):
  serializer = MapContestToTeamSerializer(data=map_data)
  if serializer.is_valid():
    serializer.save()
    return serializer.data
  else:
    raise ValidationError(serializer.errors)
