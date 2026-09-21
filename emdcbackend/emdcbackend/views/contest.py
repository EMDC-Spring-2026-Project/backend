from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from ..models import Contest, MapContestToOrganizer, MapUserToRole
from ..serializers import ContestSerializer
from .clusters import make_cluster
from .Maps.MapClusterToContest import map_cluster_to_contest


def _is_admin(user):
  return user.is_superuser or MapUserToRole.objects.filter(
      uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
  ).exists()


def _is_admin_or_organizer(user):
  return user.is_superuser or MapUserToRole.objects.filter(
      uuid=user.id,
      role__in=[MapUserToRole.RoleEnum.ADMIN, MapUserToRole.RoleEnum.ORGANIZER],
  ).exists()


def _can_edit_contest(user, contest_id):
  if _is_admin(user):
    return True
  organizer_ids = MapUserToRole.objects.filter(
      uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
  ).values_list("relatedid", flat=True)
  return MapContestToOrganizer.objects.filter(
      contestid=contest_id, organizerid__in=organizer_ids
  ).exists()


@api_view(["GET"])
def contest_by_id(request, contest_id):
  contest = get_object_or_404(Contest, id = contest_id)
  serializer = ContestSerializer(instance=contest)
  return Response({"Contest": serializer.data}, status=status.HTTP_200_OK)

@api_view(["GET"])
def contest_get_all(request):
  from ..models import MapContestToOrganizer, Organizer

  contests = Contest.objects.all()

  contest_organizer_mappings = {}
  for mapping in MapContestToOrganizer.objects.values('contestid', 'organizerid'):
    contest_id = mapping['contestid']
    organizer_id = mapping['organizerid']
    if contest_id not in contest_organizer_mappings:
      contest_organizer_mappings[contest_id] = []
    contest_organizer_mappings[contest_id].append(organizer_id)

  organizers = {org.id: f"{org.first_name} {org.last_name}".strip()
                for org in Organizer.objects.all()}

  contest_data = []
  for contest in contests:
    serializer = ContestSerializer(instance=contest)
    contest_dict = serializer.data

    contest_organizer_ids = contest_organizer_mappings.get(contest.id, [])

    organizer_names = [
      organizers[org_id] for org_id in contest_organizer_ids
      if org_id in organizers
    ]
    contest_dict['organizers'] = organizer_names
    contest_data.append(contest_dict)

  return Response({"Contests": contest_data}, status=status.HTTP_200_OK)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_contest(request):
  if not _is_admin_or_organizer(request.user):
      return Response({"detail": "Administrator or organizer access required."}, status=status.HTTP_403_FORBIDDEN)
  try:
      with transaction.atomic():
        all_teams = make_cluster({"cluster_name": "All Teams"})
        contest = create_contest_instance({"name": request.data["name"], "date": request.data["date"], "is_open":False,"is_tabulated":False})
        responses = [
          map_cluster_to_contest({
              "contestid": contest.get("id"),
              "clusterid": all_teams.get("id")
          }), 
        ]
        for response in responses:
          if isinstance(response, Response):
              return response

        return Response({
          "contest": contest,
          "contest_map": responses[0],
      }, status=status.HTTP_201_CREATED)

  except ValidationError as e:  # Catching ValidationErrors specifically
      return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
  except Exception as e:
      return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
  
# Helper method to create contest
def create_contest_instance(contest_data):
  serializer = ContestSerializer(data=contest_data)
  if serializer.is_valid():
      serializer.save()
      return serializer.data
  raise ValidationError(serializer.errors)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_contest(request):
  contest = get_object_or_404(Contest, id=request.data["id"])
  if not _can_edit_contest(request.user, contest.id):
      return Response({"detail": "You cannot edit this contest."}, status=status.HTTP_403_FORBIDDEN)
  contest.name = request.data["name"]
  contest.date = request.data["date"]
  contest.is_open = request.data["is_open"]
  contest.is_tabulated = request.data["is_tabulated"]
  contest.save()
  serializer = ContestSerializer(instance=contest)
  return Response({"Contest":serializer.data}, status=status.HTTP_200_OK)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_contest(request, contest_id):
    """
    Delete a contest and ALL data exclusively tied to that contest.
    
    IMPORTANT: Only deletes data for this specific contest_id.
    Does NOT delete data from other contests.
    
    Deletes:
    1. All judge-contest mappings (MapContestToJudge)
    2. All judge-cluster mappings for clusters in this contest (MapJudgeToCluster)
    3. All team-contest mappings (MapContestToTeam)
    4. All cluster-contest mappings (MapContestToCluster)
    5. All cluster-team mappings for clusters in this contest (MapClusterToTeam)
    6. All scoresheets for teams in this contest (MapScoresheetToTeamJudge + Scoresheet)
    7. All organizer-contest mappings (MapContestToOrganizer)
    8. Teams that ONLY exist in this contest (Teams)
    9. Clusters that ONLY exist in this contest (JudgeClusters)
    """
    if not _is_admin(request.user):
        return Response({"detail": "Administrator access required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        with transaction.atomic():
            contest = get_object_or_404(Contest, id=contest_id)
            
            from ..models import (
                MapContestToJudge, MapContestToTeam, MapContestToOrganizer, MapContestToCluster,
                MapJudgeToCluster, MapClusterToTeam, MapScoresheetToTeamJudge, Scoresheet,
                Teams, JudgeClusters
            )
            
            # Step 1: Get all clusters in this contest
            cluster_ids = list(
                MapContestToCluster.objects.filter(contestid=contest_id)
                .values_list('clusterid', flat=True)
            )
            
            # Step 2: Get all teams in this contest
            team_ids = list(
                MapContestToTeam.objects.filter(contestid=contest_id)
                .values_list('teamid', flat=True)
            )
            
            # Step 3: Get all judges in this contest 
            judge_ids = list(
                MapContestToJudge.objects.filter(contestid=contest_id)
                .values_list('judgeid', flat=True)
            )
            
            # Step 4: Delete scoresheets for teams in this contest ONLY
            # Get scoresheet mappings for teams in this contest
            scoresheet_ids = []
            if team_ids:
                scoresheet_mappings = MapScoresheetToTeamJudge.objects.filter(
                    teamid__in=team_ids
                )
                # Get scoresheet IDs to delete
                scoresheet_ids = list(scoresheet_mappings.values_list('scoresheetid', flat=True).distinct())
                # Delete the mappings first
                scoresheet_mappings.delete()
                # Then delete the scoresheets themselves
                if scoresheet_ids:
                    Scoresheet.objects.filter(id__in=scoresheet_ids).delete()
            
            # Step 5: Delete judge-cluster mappings for clusters in this contest ONLY
            # Only delete mappings where the cluster belongs to this contest
            if cluster_ids:
                MapJudgeToCluster.objects.filter(clusterid__in=cluster_ids).delete()
            
            # Step 6: Delete cluster-team mappings for clusters in this contest ONLY
            # Only delete mappings where the cluster belongs to this contest
            if cluster_ids:
                MapClusterToTeam.objects.filter(clusterid__in=cluster_ids).delete()
            
            # Step 7: Delete teams that ONLY exist in this contest
            # A team should only be deleted if it's not in any other contest
            teams_deleted_count = 0
            if team_ids:
                for team_id in team_ids:
                    # Check if team exists in any other contest
                    other_contest_mappings = MapContestToTeam.objects.filter(
                        teamid=team_id
                    ).exclude(contestid=contest_id)
                    
                    # Only delete team if it's not in any other contest
                    if not other_contest_mappings.exists():
                        try:
                            team = Teams.objects.get(id=team_id)
                            team.delete()
                            teams_deleted_count += 1
                        except Teams.DoesNotExist:
                            pass
            
            # Step 8: Delete clusters that ONLY exist in this contest
            # A cluster should only be deleted if it's not in any other contest
            clusters_deleted_count = 0
            if cluster_ids:
                for cluster_id in cluster_ids:
                    # Check if cluster exists in any other contest
                    other_contest_mappings = MapContestToCluster.objects.filter(
                        clusterid=cluster_id
                    ).exclude(contestid=contest_id)
                    
                    # Only delete cluster if it's not in any other contest
                    if not other_contest_mappings.exists():
                        try:
                            cluster = JudgeClusters.objects.get(id=cluster_id)
                            cluster.delete()
                            clusters_deleted_count += 1
                        except JudgeClusters.DoesNotExist:
                            pass
            
            # Step 9: Delete all contest mappings 
            MapContestToJudge.objects.filter(contestid=contest_id).delete()
            MapContestToTeam.objects.filter(contestid=contest_id).delete()
            MapContestToOrganizer.objects.filter(contestid=contest_id).delete()
            MapContestToCluster.objects.filter(contestid=contest_id).delete()
            
            # Step 10: Finally, delete the contest itself
            contest.delete()
            
            return Response({
                "detail": "Contest and all associated data deleted successfully.",
                "deleted": {
                    "contest_id": contest_id,
                    "clusters_deleted": clusters_deleted_count,
                    "teams_deleted": teams_deleted_count,
                    "judges_removed": len(judge_ids),
                    "scoresheets_deleted": len(scoresheet_ids)
                }
            }, status=status.HTTP_200_OK)
            
    except Exception as e:
        return Response({
            "detail": f"Error deleting contest: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
