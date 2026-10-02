from .Maps.MapClusterToContest import get_all_teams_cluster
from ..models import Teams, Scoresheet, MapScoresheetToTeamJudge, MapContestToTeam, MapClusterToTeam, \
    MapCoachToTeam, MapUserToRole, Coach, Judge, MapJudgeToCluster
from .coach import create_coach, create_user_and_coach, get_coach
from ..serializers import TeamSerializer, ScoresheetSerializer, CoachSerializer
from .scoresheets import create_score_sheets_for_team, make_sheets_for_team
from .Maps.MapUserToRole import get_role_mapping, create_user_role_map
from .Maps.MapCoachToTeam import create_coach_to_team_map
from .Maps.MapContestToTeam import create_team_to_contest_map
from .Maps.MapClusterToTeam import create_team_to_cluster_map

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
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db import transaction


def _can_manage_team(user, team_id):
    contest_ids = list(MapContestToTeam.objects.filter(
        teamid=team_id
    ).values_list("contestid", flat=True))
    # Editing or deleting a team changes the shared team record and related data
    # for every contest. An organizer must therefore manage every linked contest.
    return bool(contest_ids) and all(
        _can_manage_contest(user, contest_id) for contest_id in contest_ids
    )


def _can_manage_contest(user, contest_id):
    if user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists():
        return True
    organizer_ids = MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
    ).values_list("relatedid", flat=True)
    from ..models import MapContestToOrganizer
    return MapContestToOrganizer.objects.filter(
        contestid=contest_id, organizerid__in=organizer_ids
    ).exists()

# Get team by ID
@api_view(["GET"])
def team_by_id(request, team_id):
    team = get_object_or_404(Teams, id=team_id)
    serializer = TeamSerializer(instance=team)
    return Response({"Team": serializer.data}, status=status.HTTP_200_OK)


# Create a new team with coach and assign to contest/cluster
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_team(request):
    try:
        with transaction.atomic():
            # Validate required fields
            if "username" not in request.data:
                raise ValidationError({"username": "Username is required."})
            if "contestid" not in request.data:
                raise ValidationError({"contestid": "Contest ID is required."})
            if "clusterid" not in request.data:
                raise ValidationError({"clusterid": "Cluster ID is required."})
            if not _can_manage_contest(request.user, request.data["contestid"]):
                return Response({"detail": "You cannot manage this contest."}, status=status.HTTP_403_FORBIDDEN)
            
            # Step 1: Create team object
            team_response = make_team(request.data)

            try:
                # Step 2: Retrieve user and create coach if necessary
                # Try to get existing user by email
                user = User.objects.get(username=request.data["username"])

                role_mapping_response = get_role_mapping(user.id)
                if role_mapping_response.get("id"):
                    if role_mapping_response.get("role") == 4:
                        # EXISTING COACH - Just update coach name, NO email sent
                        # This coach already has a password set, so don't spam them with emails
                        coach = Coach.objects.get(id=role_mapping_response.get("relatedid"))
                        coach.first_name = request.data["first_name"]
                        coach.last_name = request.data.get("last_name", "") or ""
                        coach.save()
                        coach_response = get_coach(coach.id)
    
                        coach_response['username'] = user.username
                    else:
                        raise ValidationError({"detail": "This user is already mapped to a role."})
                else:
                    coach_response = create_coach(request.data)
                    coach_response['username'] = user.username
                    role_mapping_response = create_user_role_map({
                        "uuid": user.id,
                        "role": 4,
                        "relatedid": coach_response.get("id")
                    })
            except User.DoesNotExist:
                # NEW COACH - Create user and coach, SEND set-password email
                # This is a brand new coach account, so they need the email to set their password
                user_response, coach_response = create_user_and_coach(request.data)
                coach_response['username'] = user_response.get("user").get("username")
                role_mapping_response = create_user_role_map({
                    "uuid": user_response.get("user").get("id"),
                    "role": 4,
                    "relatedid": coach_response.get("id")
                })

            # Step 3: Create mapping responses
            responses = []

            # Create coach to team map
            coach_to_team_response = create_coach_to_team_map({
                "teamid": team_response.get("id"),
                "coachid": coach_response.get("id")
            })
            if isinstance(coach_to_team_response, Response):
                return coach_to_team_response
            responses.append(coach_to_team_response)

            # Create team to contest map
            team_to_contest_response = create_team_to_contest_map({
                "contestid": request.data["contestid"],
                "teamid": team_response.get("id")
            })
            if isinstance(team_to_contest_response, Response):
                return team_to_contest_response
            responses.append(team_to_contest_response)

            # Step 4: Map team to the "All Teams" cluster (default cluster)
            all_teams_cluster_id = get_all_teams_cluster(request.data["contestid"])
            # Handle case where get_all_teams_cluster returns error tuple
            if isinstance(all_teams_cluster_id, tuple):
                error_dict, _ = all_teams_cluster_id
                # Log error but continue - team creation should still succeed
                all_teams_cluster_id = None
            if all_teams_cluster_id and isinstance(all_teams_cluster_id, int):
                create_team_to_cluster_map({
                    "clusterid": all_teams_cluster_id,
                    "teamid": team_response.get("id")
                })

            # Step 5: Check if the provided clusterid is not the "All Teams" cluster
            if all_teams_cluster_id and isinstance(all_teams_cluster_id, int) and request.data["clusterid"] != all_teams_cluster_id:
                # Map team to the other provided cluster
                other_cluster_mapping_response = create_team_to_cluster_map({
                    "clusterid": request.data["clusterid"],
                    "teamid": team_response.get("id")
                })
                if isinstance(other_cluster_mapping_response, Response):
                    return other_cluster_mapping_response
                responses.append(other_cluster_mapping_response)

            # Step 6: Create scoresheets for all judges in the cluster
            try:
                make_sheets_for_team(team_response.get("id"), request.data["clusterid"])
            except Exception as e:
                # Don't fail the team creation if scoresheet creation fails
                # Just log the error and continue
                pass
            
            # Step 7: Check responses and return
            return Response({
                "team": team_response,
                "coach": coach_response,
                "coach_to_team_map": responses[0],
                "team_to_contest_map": responses[1],
                "team_to_all_teams_cluster_map": responses[2] if len(responses) > 2 else None,
                "team_to_cluster_map": responses[3] if len(responses) > 3 else None
            }, status=status.HTTP_201_CREATED)

    except ValidationError as e:
        # Specific error handling for validation errors
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        # General error handling
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_team(request):
    try:
        with transaction.atomic():
            # Retrieve team, coach, and user details
            team = get_object_or_404(Teams, id=request.data["id"])
            if not _can_manage_team(request.user, team.id):
                return Response({"detail": "You cannot manage this team."}, status=status.HTTP_403_FORBIDDEN)
            coach_team_mapping = get_object_or_404(MapCoachToTeam, teamid=team.id)
            coach = get_object_or_404(Coach, id=coach_team_mapping.coachid)
            try:
                mapping = MapUserToRole.objects.get(relatedid=coach.id, role=4)
                uuid = mapping.uuid
                user = get_object_or_404(User, id=uuid)
            except MapUserToRole.DoesNotExist:
                raise ValidationError({"detail": "Team does not have a valid coach mapping."})

            # Update team name if provided and necessary
            if "team_name" in request.data:
                new_team_name = request.data["team_name"].strip()
                if not new_team_name:
                    raise ValidationError({"team_name": "Team name cannot be empty or whitespace only."})
                if new_team_name != team.team_name:
                    team.team_name = new_team_name
            # Update school name if provided
            if "school_name" in request.data and request.data["school_name"] != team.__dict__.get("school_name", "NA"):
                team.school_name = request.data.get("school_name") or "MNSU"

            # Track if coach_response was set 
            coach_response = None
            
            # Update coach and user mappings if username has changed
            if "username" in request.data and request.data["username"] != user.username:
                # Coach email has changed - need to switch to different coach
                # Remove old mapping, create or fetch the user and coach, and map them to the team
                MapCoachToTeam.objects.get(teamid=team.id, coachid=coach.id).delete()
                try:
                    # Try to find existing user with the new email
                    user = User.objects.get(username=request.data["username"])
                    role_mapping_response = get_role_mapping(user.id)
                    if role_mapping_response.get("id") and role_mapping_response.get("role") == 4:
                        # EXISTING COACH - Just reassign to this team, NO email sent
                        # This coach already exists and has their password, so don't send another email
                        existing_coach = Coach.objects.get(id=role_mapping_response.get("relatedid"))
                        existing_coach.first_name = request.data["first_name"]
                        existing_coach.last_name = request.data.get("last_name", "") or ""
                        existing_coach.save()
                        coach = existing_coach  # Update local coach variable
                        coach_response = get_coach(existing_coach.id)
                        coach_response['username'] = user.username
                    else:
                        raise ValidationError({"detail": "This user is already mapped to a role."})
                except User.DoesNotExist:
                    # NEW COACH - Create new user and coach account, SEND set-password email
                    # This is a brand new coach with a new email, so they need the email to set password
                    user_response, coach_response = create_user_and_coach(request.data)
                    coach_response['username'] = user_response.get("user").get("username")
                    create_user_role_map({
                        "uuid": user_response.get("user").get("id"),
                        "role": 4,
                        "relatedid": coach_response.get("id")
                    })
                create_coach_to_team_map({"teamid": team.id, "coachid": coach_response.get("id")})
            else:
                # Username hasn't changed - update coach details if changed
        
                coach_updated = False
                if request.data["first_name"] != coach.first_name:
                    coach.first_name = request.data["first_name"]
                    coach_updated = True
                if request.data["last_name"] != coach.last_name:
                    coach.last_name = request.data["last_name"]
                    coach_updated = True
                if coach_updated:
                    coach.save()

            # Update coach details if changed
            if "first_name" in request.data and request.data["first_name"] != coach.first_name:
                coach.first_name = request.data["first_name"]
                coach.save()
            if "last_name" in request.data and request.data["last_name"] != coach.last_name:
                coach.last_name = request.data["last_name"]
                coach.save()

            # Update cluster and score sheets only if contestid and clusterid are provided
            if "contestid" in request.data and "clusterid" in request.data:
                all_teams_cluster = get_all_teams_cluster(request.data["contestid"])
                # Handle case where get_all_teams_cluster returns error tuple
                if isinstance(all_teams_cluster, tuple):
                    error_dict, _ = all_teams_cluster
                    # If we can't get the "All Teams" cluster, skip cluster updates
                    all_teams_cluster = None
                
                # Only proceed with cluster updates if we have a valid all_teams_cluster ID
                if all_teams_cluster and isinstance(all_teams_cluster, int):
                    new_cluster_is_all_teams = request.data["clusterid"] == all_teams_cluster

                    non_all_teams_cluster_mapping = MapClusterToTeam.objects.filter(
                        teamid=team.id
                    ).exclude(clusterid=all_teams_cluster)

                    judges_in_all_teams = MapJudgeToCluster.objects.filter(clusterid=all_teams_cluster)
                    all_score_sheets_assigned_to_team = MapScoresheetToTeamJudge.objects.filter(teamid=team.id)
                    non_all_teams_score_sheets = all_score_sheets_assigned_to_team.exclude(judgeid__in=judges_in_all_teams)

                    if new_cluster_is_all_teams and non_all_teams_cluster_mapping:
                        # New Cluster is all teams and team was assigned to other clusters previously
                        non_all_teams_cluster_mapping.delete()
                        scoresheets_to_delete_ids = non_all_teams_score_sheets.values_list('scoresheetid', flat=True)
                        MapScoresheetToTeamJudge.objects.filter(scoresheetid__in=scoresheets_to_delete_ids).delete()
                        Scoresheet.objects.filter(id__in=scoresheets_to_delete_ids).delete()
                    elif not new_cluster_is_all_teams and not non_all_teams_cluster_mapping:
                        # New cluster is not all teams and team wasn't assigned to other clusters previously
                        create_team_to_cluster_map({"clusterid": request.data["clusterid"], "teamid": team.id})
                        judge_ids = MapJudgeToCluster.objects.filter(clusterid=request.data["clusterid"]).values_list('judgeid', flat=True)
                        judges = Judge.objects.filter(id__in=judge_ids)
                        create_score_sheets_for_team(team, judges)
                    elif not new_cluster_is_all_teams and non_all_teams_cluster_mapping:
                        # New cluster is not all teams and team was assigned to other clusters previously
                        non_all_teams_cluster_mapping.delete()
                        create_team_to_cluster_map({"clusterid": request.data["clusterid"], "teamid": team.id})
                        scoresheets_to_delete_ids = non_all_teams_score_sheets.values_list('scoresheetid', flat=True)
                        MapScoresheetToTeamJudge.objects.filter(scoresheetid__in=scoresheets_to_delete_ids).delete()
                        Scoresheet.objects.filter(id__in=scoresheets_to_delete_ids).delete()
                        judge_ids = MapJudgeToCluster.objects.filter(clusterid=request.data["clusterid"]).values_list('judgeid',flat=True)
                        judges = Judge.objects.filter(id__in=judge_ids)
                        create_score_sheets_for_team(team, judges)

            team.save()
            serializer = TeamSerializer(instance=team)
            
            # Prepare coach data for response
            # If username changed, coach_response was already set with username
            # Otherwise, serialize the current coach and add username
            if coach_response:
                coach_data = coach_response
            else:
                coach_serializer = CoachSerializer(instance=coach)
                coach_data = coach_serializer.data
                coach_data['username'] = user.username

            score_sheet_ids = MapScoresheetToTeamJudge.objects.filter(teamid=team.id).values_list('scoresheetid', flat=True)
            score_sheets = Scoresheet.objects.filter(id__in=score_sheet_ids)
            score_sheets_data = ScoresheetSerializer(score_sheets, many=True).data

    except ValidationError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": "An error occurred: " + str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({"Team": serializer.data, "ScoreSheets": score_sheets_data, "Coach": coach_data}, status=status.HTTP_200_OK)

# delete team
@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_team_by_id(request, team_id):
    """
    deletion of a team and every related mapping/scoresheet record that might
    prevent FK integrity on delete.
    """
    team = get_object_or_404(Teams, id=team_id)
    if not _can_manage_team(request.user, team.id):
        return Response({"detail": "You cannot manage this team."}, status=status.HTTP_403_FORBIDDEN)
    try:
        with transaction.atomic():
            # Import here to avoid circulars at module import time
            from ..models import (
                MapContestToTeam,
                MapClusterToTeam,
                MapCoachToTeam,
                MapScoresheetToTeamJudge,
                Scoresheet,
            )
            
            # Try to import MapAwardToTeam if it exists (optional model)
            MapAwardToTeam = None
            try:
                from ..models import MapAwardToTeam
            except ImportError:
                # MapAwardToTeam doesn't exist in this deployment, skip it
                pass

            # 1) Delete score sheet mappings first and collect score sheet ids
            scoresheet_ids = list(
                MapScoresheetToTeamJudge.objects.filter(teamid=team_id)
                .values_list("scoresheetid", flat=True)
            )
            MapScoresheetToTeamJudge.objects.filter(teamid=team_id).delete()

            # 2) Delete explicit score sheets linked to this team
            # Some schemas keep a direct team FK; others only via mapping ids
            try:
                if scoresheet_ids:
                    Scoresheet.objects.filter(id__in=scoresheet_ids).delete()
            except Exception:
                # Ignore if schema differs
                pass
            try:
                # In case Scoresheet has teamid FK
                Scoresheet.objects.filter(teamid=team_id).delete()
            except Exception:
                pass

            # 3) Delete all other mapping tables that reference this team
            MapContestToTeam.objects.filter(teamid=team_id).delete()
            MapClusterToTeam.objects.filter(teamid=team_id).delete()
            MapCoachToTeam.objects.filter(teamid=team_id).delete()

            # Only try to delete MapAwardToTeam if the model exists
            if MapAwardToTeam is not None:
                try:
                    MapAwardToTeam.objects.filter(teamid=team_id).delete()
                except Exception:
                    # Award mapping may not exist in some deployments
                    pass

            # 4) Finally delete the team
            team.delete()

        return Response(
            {"detail": "Team and all related mappings deleted successfully."},
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        # Return exact error to aid debugging of any remaining FK blockers
        return Response(
            {"detail": f"{type(e).__name__}: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

def make_team_instance(team_data):
    serializer = TeamSerializer(data=team_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    raise ValidationError(serializer.errors)

def make_team(data):
    # Validate team_name is not empty or whitespace-only
    team_name = data.get("team_name", "").strip()
    if not team_name:
        raise ValidationError({"team_name": "Team name cannot be empty or whitespace only."})
    
    team_data = {
        "team_name": team_name,
        "school_name": data.get("school_name", "MNSU"),
        # Initialize all score fields to 0.0 to prevent None values
        "journal_score": 0.0,
        "presentation_score": 0.0,
        "machinedesign_score": 0.0,
        "penalties_score": 0.0,
        "redesign_score": 0.0,
        "championship_score": 0.0,
        "total_score": 0.0,
        # Initialize preliminary scores
        "preliminary_presentation_score": 0.0,
        "preliminary_journal_score": 0.0,
        "preliminary_machinedesign_score": 0.0,
        "preliminary_penalties_score": 0.0,
        "preliminary_total_score": 0.0,
        # Initialize championship scores
        "championship_presentation_score": 0.0,
        "championship_machinedesign_score": 0.0,
        "championship_penalties_score": 0.0,
        "championship_general_penalties_score": 0.0,
        "championship_run_penalties_score": 0.0,
    }
    team_response = make_team_instance(team_data)
    if not team_response.get('id'):
        raise ValidationError('Team creation failed.')
    return team_response

@api_view(["GET"])
@authentication_classes([SessionAuthentication]) 
@permission_classes([IsAuthenticated])
def get_teams_by_team_rank(request):
    try:
        contestid = int(request.query_params.get("contestid", ""))
        if contestid <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"detail": "contestid must be a positive integer"}, status=status.HTTP_400_BAD_REQUEST)
    mappings = MapContestToTeam.objects.filter(contestid=contestid)
    teams = Teams.objects.filter(id__in=mappings.values_list('teamid', flat=True,),team_rank__isnull=False).order_by('team_rank')
    serializer = TeamSerializer(teams, many=True)
    return Response({"Teams": serializer.data}, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_team_after_judge(request):
  try:
    with transaction.atomic():
      # create team object.
      team_response = make_team(request.data)
      
      try:
        # Try to get existing user by email
        user = User.objects.get(username=request.data["username"])
        
        role_mapping_response = get_role_mapping(user.id)
        if role_mapping_response.get("id"):
          # if we have the mapping and it matches, we get the coach from the mapping
          if role_mapping_response.get("role") == 4:
            # EXISTING COACH - Reuse existing coach, NO email sent
            coach_response = get_coach(role_mapping_response.get("relatedid"))
          else:
            raise ValidationError({"detail": "This user is already mapped to a role."})
        else:
          coach_response = create_coach(request.data)
          role_mapping_response = create_user_role_map({
            "uuid": user.id,
            "role": 4,
            "relatedid": coach_response.get("id")
            })
      except User.DoesNotExist:
        # NEW COACH - Create user and coach, SEND set-password email
        user_response, coach_response = create_user_and_coach(request.data)
        role_mapping_response = create_user_role_map({
            "uuid": user_response.get("user").get("id"),
            "role": 4,
            "relatedid": coach_response.get("id")
            })
        
      responses = [
        # map team to coach, map team to contest, map team to cluster, create score sheets for team
        create_coach_to_team_map({
          "teamid": team_response.get("id"),
          "coachid": coach_response.get("id")
        }),
        create_team_to_contest_map({
          "contestid": request.data["contestid"],
          "teamid": team_response.get("id")
        }),
        create_team_to_cluster_map({
          "clusterid": request.data["clusterid"],
          "teamid": team_response.get("id")
        }),
        make_sheets_for_team(  # create score sheets for all judges in cluster and map them
          teamid=team_response.get("id"),
          clusterid=request.data["clusterid"]
        )
      ]

      for response in responses:
        if isinstance(response, Response):
          return response
        
      return Response({
        "team":team_response,
        "coach":coach_response,
        "coach to team map": responses[0],
        "team to contest map": responses[1],
        "team to cluster map": responses[2],
        "score sheets": responses[3],
      },status=status.HTTP_201_CREATED)
    
  except ValidationError as e:  # Catching ValidationErrors specifically
    return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
  
  except Exception as e:
    return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def is_team_disqualified(request):
    team = get_object_or_404(Teams, id=request.data["teamid"])
    return Response({"is disqualified": team.organizer_disqualified}, status=status.HTTP_200_OK)

# GET request that returns all teams
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_all_teams(request):
    try:
        teams = Teams.objects.all()
        serializer = TeamSerializer(teams, many=True)
        return Response({"teams": serializer.data}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
