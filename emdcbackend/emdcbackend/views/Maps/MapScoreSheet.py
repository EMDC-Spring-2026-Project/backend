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
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from ...models import (
    MapScoresheetToTeamJudge,
    Scoresheet,
    ScoresheetEnum,
    MapContestToJudge,
    MapJudgeToCluster,
    MapClusterToTeam,
    MapContestToCluster,
    MapContestToTeam,
    MapContestToOrganizer,
    JudgeClusters,
    MapUserToRole,
)
from ...serializers import MapScoreSheetToTeamJudgeSerializer, ScoresheetSerializer
from ...views.contest_utils import judge_cluster_assignments_for_contest

logger = logging.getLogger(__name__)


def _is_admin(user):
    return user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists()


def _can_manage_team(user, team_id):
    if _is_admin(user):
        return True

    organizer_ids = list(MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
    ).values_list("relatedid", flat=True))
    contest_ids = set(MapContestToTeam.objects.filter(
        teamid=team_id
    ).values_list("contestid", flat=True))
    if not organizer_ids or not contest_ids:
        return False

    managed_contest_ids = set(MapContestToOrganizer.objects.filter(
        contestid__in=contest_ids, organizerid__in=organizer_ids
    ).values_list("contestid", flat=True))
    return contest_ids.issubset(managed_contest_ids)


def _judge_role_matches(user, judge_id):
    return MapUserToRole.objects.filter(
        uuid=user.id,
        role=MapUserToRole.RoleEnum.JUDGE,
        relatedid=judge_id,
    ).exists()


def _can_manage_contest(user, contest_id):
    if _is_admin(user):
        return True
    organizer_ids = MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
    ).values_list("relatedid", flat=True)
    return MapContestToOrganizer.objects.filter(
        contestid=contest_id, organizerid__in=organizer_ids
    ).exists()


def _can_read_judge_mappings(user, judge_id, mappings):
    if _is_admin(user) or _judge_role_matches(user, judge_id):
        return True
    team_ids = set(mappings.values_list("teamid", flat=True))
    return bool(team_ids) and all(_can_manage_team(user, team_id) for team_id in team_ids)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_score_sheet_mapping(request):
    try:
        team_id = request.data.get("teamid")
        if team_id is None:
            return Response(
                {"detail": "teamid is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        if not _can_manage_team(request.user, team_id):
            return Response(
                {"detail": "You cannot create scoresheet mappings for this team."},
                status=status.HTTP_403_FORBIDDEN,
            )
        result = map_score_sheet(request.data)
        return Response(result, status=status.HTTP_201_CREATED)

    except ValidationError as e:
        return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

    except Exception:
        logger.exception("Unexpected error while creating a scoresheet mapping")
        return Response(
            {"detail": "Unable to create the scoresheet mapping."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def score_sheet_by_judge_team(request, judge_id, team_id, sheetType):
    try:
        if not (_judge_role_matches(request.user, judge_id) or _can_manage_team(request.user, team_id)):
            return Response(
                {"detail": "You cannot view this scoresheet."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Get all mappings for this specific team/judge/sheetType combination
        mappings = MapScoresheetToTeamJudge.objects.filter(
            judgeid=judge_id, 
            teamid=team_id, 
            sheetType=sheetType
        ).order_by('id')
        
        if not mappings.exists():
            return Response({"error": "No mapping found for the provided judge, team, and sheet type."},
                            status=status.HTTP_404_NOT_FOUND)
        
        # If multiple mappings exist, prioritize submitted scoresheets, then most recent
        if mappings.count() > 1:
            best_mapping = None
            
            for mapping in mappings:
                try:
                    scoresheet = Scoresheet.objects.get(id=mapping.scoresheetid)
                    is_submitted = scoresheet.isSubmitted
                    
                    if best_mapping is None:
                        best_mapping = mapping
                    else:
                        # Check if current mapping is submitted and existing is not
                        try:
                            existing_scoresheet = Scoresheet.objects.get(id=best_mapping.scoresheetid)
                            existing_submitted = existing_scoresheet.isSubmitted
                        except:
                            existing_submitted = False
                        
                        if is_submitted and not existing_submitted:
                            best_mapping = mapping
                        elif not is_submitted and existing_submitted:
                            pass  # Keep existing submitted mapping
                        elif mapping.id > best_mapping.id:
                            best_mapping = mapping
                            
                except Scoresheet.DoesNotExist:
                    continue
            
            if best_mapping is None:
                return Response({"error": "No valid scoresheet found for the provided judge, team, and sheet type."},
                                status=status.HTTP_404_NOT_FOUND)
            
            mapping = best_mapping
        else:
            mapping = mappings.first()
        
        sheet = Scoresheet.objects.get(id=mapping.scoresheetid)
        serializer = ScoresheetSerializer(instance=sheet)
        return Response({"ScoreSheet": serializer.data}, status=status.HTTP_200_OK)

    except MapScoresheetToTeamJudge.DoesNotExist:
        return Response({"error": "No mapping found for the provided judge, team, and sheet type."},
                        status=status.HTTP_404_NOT_FOUND)

    except Scoresheet.DoesNotExist:
        return Response({"error": "Scoresheet not found."}, status=status.HTTP_404_NOT_FOUND)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def score_sheets_by_judge(request, judge_id):
    try:
        # Fetch mappings for the given judge
        mappings = MapScoresheetToTeamJudge.objects.filter(judgeid=judge_id)

        if not _can_read_judge_mappings(request.user, judge_id, mappings):
            return Response(
                {"detail": "You cannot view scoresheets for this judge."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not mappings.exists():
            # Return empty list instead of 404 to simplify client handling
            return Response({"ScoreSheets": []}, status=status.HTTP_200_OK)

        # Prepare data to return mappings with scoresheets
        results = []
        for mapping in mappings:
            # Fetch the scoresheet by its ID
            try:
                score_sheet = Scoresheet.objects.get(id=mapping.scoresheetid)
                serializer = ScoresheetSerializer(score_sheet).data
                total_score = 0
                if mapping.sheetType == 4:
                    total_score = (serializer.get("field1") + serializer.get("field2") + serializer.get("field3") +
                           serializer.get("field4") + serializer.get("field5") + serializer.get("field6") +
                           serializer.get("field7") + serializer.get("field8") + serializer.get("field10") +
                           serializer.get("field11") + serializer.get("field12") + serializer.get("field13") +
                           serializer.get("field14") + serializer.get("field15") + serializer.get("field16") +
                           serializer.get("field17"))
                elif mapping.sheetType == 5:
                    total_score = (serializer.get("field1") + serializer.get("field2") + serializer.get("field3") +
                                   serializer.get("field4") + serializer.get("field5") + serializer.get("field6") +
                                   serializer.get("field7"))
                elif mapping.sheetType == 6:
                    total_score = (serializer.get("field1") + serializer.get("field2") + serializer.get("field3") +
                                   serializer.get("field4") + serializer.get("field5") + serializer.get("field6") +
                                   serializer.get("field7"))
                else:
                    total_score = (serializer.get("field1")+serializer.get("field2")+serializer.get("field3")+
                                  serializer.get("field4")+serializer.get("field5")+serializer.get("field6")+
                                  serializer.get("field7")+serializer.get("field8"))
                results.append({
                    "mapping": {
                        "teamid": mapping.teamid,
                        "judgeid": mapping.judgeid,
                        "scoresheetid": mapping.scoresheetid,
                        "sheetType": mapping.sheetType,
                    },
                    "scoresheet": serializer,  # Serialize the scoresheet
                    "total": total_score
                })
            except Scoresheet.DoesNotExist:
                results.append({
                    "mapping": {
                        "teamid": mapping.teamid,
                        "judgeid": mapping.judgeid,
                        "scoresheetid": mapping.scoresheetid,
                        "sheetType": mapping.sheetType,
                    },
                    "scoresheet": None  # Or handle this case as needed
                })

        return Response({"ScoreSheets": results}, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Unexpected error while loading judge/cluster scoresheets")
        return Response(
            {"error": "Unable to load the scoresheets."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def score_sheets_by_judge_and_cluster(request, judge_id, cluster_id):
    """
    Fetch scoresheets for a specific judge within a specific cluster.
    This is used to filter scoresheets by cluster type (championship/redesign).
    """
    try:
        # Get all teams in the cluster
        cluster_team_mappings = MapClusterToTeam.objects.filter(clusterid=cluster_id)
        team_ids = cluster_team_mappings.values_list('teamid', flat=True)
        
        # Fetch mappings for the judge and teams in this cluster only
        mappings = MapScoresheetToTeamJudge.objects.filter(
            judgeid=judge_id,
            teamid__in=team_ids
        )

        if not _can_read_judge_mappings(request.user, judge_id, mappings):
            return Response(
                {"detail": "You cannot view scoresheets for this judge."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not mappings.exists():
            # Return empty list instead of 404 to simplify client handling
            return Response({"ScoreSheets": []}, status=status.HTTP_200_OK)

        # Prepare data to return mappings with scoresheets
        results = []
        for mapping in mappings:
            # Fetch the scoresheet by its ID
            try:
                score_sheet = Scoresheet.objects.get(id=mapping.scoresheetid)
                serializer = ScoresheetSerializer(score_sheet).data
                total_score = 0
                if mapping.sheetType == 4:
                    total_score = (serializer.get('field1', 0) or 0) + (serializer.get('field2', 0) or 0) + (serializer.get('field3', 0) or 0) + (serializer.get('field4', 0) or 0) + (serializer.get('field5', 0) or 0) + (serializer.get('field6', 0) or 0) + (serializer.get('field7', 0) or 0) + (serializer.get('field8', 0) or 0) + (serializer.get('field10', 0) or 0) + (serializer.get('field11', 0) or 0) + (serializer.get('field12', 0) or 0) + (serializer.get('field13', 0) or 0) + (serializer.get('field14', 0) or 0) + (serializer.get('field15', 0) or 0) + (serializer.get('field16', 0) or 0) + (serializer.get('field17', 0) or 0)
                elif mapping.sheetType == 5:
                    total_score = (serializer.get('field1', 0) or 0) + (serializer.get('field2', 0) or 0) + (serializer.get('field3', 0) or 0) + (serializer.get('field4', 0) or 0) + (serializer.get('field5', 0) or 0) + (serializer.get('field6', 0) or 0) + (serializer.get('field7', 0) or 0)
                elif mapping.sheetType == 1:
                    total_score = (serializer.get('field1', 0) or 0) + (serializer.get('field2', 0) or 0) + (serializer.get('field3', 0) or 0) + (serializer.get('field4', 0) or 0) + (serializer.get('field5', 0) or 0) + (serializer.get('field6', 0) or 0) + (serializer.get('field7', 0) or 0) + (serializer.get('field8', 0) or 0)
                elif mapping.sheetType == 2:
                    total_score = (serializer.get('field1', 0) or 0) + (serializer.get('field2', 0) or 0) + (serializer.get('field3', 0) or 0) + (serializer.get('field4', 0) or 0) + (serializer.get('field5', 0) or 0) + (serializer.get('field6', 0) or 0) + (serializer.get('field7', 0) or 0) + (serializer.get('field8', 0) or 0)
                elif mapping.sheetType == 3:
                    total_score = (serializer.get('field1', 0) or 0) + (serializer.get('field2', 0) or 0) + (serializer.get('field3', 0) or 0) + (serializer.get('field4', 0) or 0) + (serializer.get('field5', 0) or 0) + (serializer.get('field6', 0) or 0) + (serializer.get('field7', 0) or 0) + (serializer.get('field8', 0) or 0)
                elif mapping.sheetType == 6:
                    total_score = (serializer.get('field1', 0) or 0) + (serializer.get('field2', 0) or 0) + (serializer.get('field3', 0) or 0) + (serializer.get('field4', 0) or 0) + (serializer.get('field5', 0) or 0) + (serializer.get('field6', 0) or 0) + (serializer.get('field7', 0) or 0) + (serializer.get('field8', 0) or 0)
                elif mapping.sheetType == 7:
                    total_score = (serializer.get('field1', 0) or 0) + (serializer.get('field2', 0) or 0) + (serializer.get('field3', 0) or 0) + (serializer.get('field4', 0) or 0) + (serializer.get('field5', 0) or 0) + (serializer.get('field6', 0) or 0) + (serializer.get('field7', 0) or 0) + (serializer.get('field8', 0) or 0) + (serializer.get('field9', 0) or 0)
                
                results.append({
                    "mapping": {
                        "id": mapping.id,
                        "teamid": mapping.teamid,
                        "judgeid": mapping.judgeid,
                        "scoresheetid": mapping.scoresheetid,
                        "sheetType": mapping.sheetType
                    },
                    "scoresheet": serializer,
                    "total": total_score
                })
            except Scoresheet.DoesNotExist:
                continue

        return Response({"ScoreSheets": results}, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Unexpected error while checking contest scoresheet submissions")
        return Response(
            {"error": "Unable to check scoresheet submission status."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def all_sheets_submitted_for_contests(request):
    contests = request.data
    results = {}

    if not isinstance(contests, list) or not all(
        isinstance(contest, dict)
        and isinstance(contest.get("id"), int)
        and contest["id"] > 0
        for contest in contests
    ):
        return Response(
            {"detail": "Request body must be a list of contests with positive integer id values."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        for contest in contests:
            contest_id = contest.get('id')
            if not _can_manage_contest(request.user, contest_id):
                return Response(
                    {"detail": "You cannot view submission status for this contest."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            
            # Keep this status scoped to the selected contest. Clusters and
            # teams can be shared, so looking up every assignment/team by
            # cluster ID alone can mix another contest's progress into this
            # response.
            cluster_ids = list(
                MapContestToCluster.objects.filter(contestid=contest_id)
                .values_list("clusterid", flat=True)
                .distinct()
            )
            
            if not cluster_ids:
                # No clusters in contest, so no judges to check
                results[contest_id] = True
                continue

            # Each contest has an internal "All Teams" roster group. It is
            # not a scoring cluster and has no judge assignments, so counting
            # it here would make an otherwise completed contest look pending.
            all_teams_cluster_ids = set(
                JudgeClusters.objects.filter(
                    id__in=cluster_ids,
                    cluster_name__iexact="All Teams",
                ).values_list("id", flat=True)
            )
            cluster_ids = [
                cluster_id for cluster_id in cluster_ids
                if cluster_id not in all_teams_cluster_ids
            ]
            if not cluster_ids:
                # A roster-only contest has no scored work to mark complete.
                results[contest_id] = False
                continue
            
            # New assignments record the contest explicitly. A legacy mapping
            # without contestid is only safe to use when its cluster belongs
            # to this one contest; on a shared cluster it is ambiguous.
            judge_cluster_mappings = list(
                judge_cluster_assignments_for_contest(contest_id, cluster_ids)
            )
            
            if not judge_cluster_mappings:
                # No judges assigned to clusters in this contest
                # Cannot say all sheets are submitted if there are no judges
                results[contest_id] = False
                continue
            
            # If contest-team links exist, use them to exclude teams belonging
            # only to another contest that happens to share the same cluster.
            contest_team_ids = set(
                MapContestToTeam.objects.filter(contestid=contest_id)
                .values_list("teamid", flat=True)
            )
            team_cluster_mappings = MapClusterToTeam.objects.filter(clusterid__in=cluster_ids)
            if contest_team_ids:
                team_cluster_mappings = team_cluster_mappings.filter(teamid__in=contest_team_ids)
            else:
                contests_by_cluster = {}
                for cluster_id, mapped_contest_id in MapContestToCluster.objects.filter(
                    clusterid__in=cluster_ids
                ).values_list("clusterid", "contestid"):
                    contests_by_cluster.setdefault(cluster_id, set()).add(mapped_contest_id)
                if any(
                    len(contests_by_cluster.get(cluster_id, set())) > 1
                    for cluster_id in cluster_ids
                ):
                    # Without contest-team links there is no reliable way to
                    # distinguish teams in a shared cluster, so fail closed.
                    results[contest_id] = False
                    continue
            teams_by_cluster = {}
            for cluster_id, team_id in team_cluster_mappings.values_list("clusterid", "teamid"):
                teams_by_cluster.setdefault(cluster_id, set()).add(team_id)
            team_ids = set().union(*teams_by_cluster.values()) if teams_by_cluster else set()
            
            if not team_ids:
                # No teams in clusters, so no score sheets to check
                # Cannot say all sheets are submitted if there are no teams
                results[contest_id] = False
                continue
            
            all_submitted = True
            assigned_cluster_ids = {
                assignment.clusterid for assignment in judge_cluster_mappings
            }
            if any(
                cluster_team_ids and cluster_id not in assigned_cluster_ids
                for cluster_id, cluster_team_ids in teams_by_cluster.items()
            ):
                all_submitted = False
            required_sheet_flags = (
                ("presentation", ScoresheetEnum.PRESENTATION),
                ("journal", ScoresheetEnum.JOURNAL),
                ("mdo", ScoresheetEnum.MACHINEDESIGN),
                ("runpenalties", ScoresheetEnum.RUNPENALTIES),
                ("otherpenalties", ScoresheetEnum.OTHERPENALTIES),
                ("redesign", ScoresheetEnum.REDESIGN),
                ("championship", ScoresheetEnum.CHAMPIONSHIP),
            )
            checked_assignment_team_pair = False
            for assignment in judge_cluster_mappings:
                if not all_submitted:
                    break
                cluster_team_ids = teams_by_cluster.get(assignment.clusterid, set())
                if not cluster_team_ids:
                    continue
                expected_types = [
                    sheet_type
                    for flag, sheet_type in required_sheet_flags
                    if getattr(assignment, flag)
                ]
                if not expected_types:
                    all_submitted = False
                    break

                for team_id in cluster_team_ids:
                    checked_assignment_team_pair = True
                    for sheet_type in expected_types:
                        score_sheet_mappings = MapScoresheetToTeamJudge.objects.filter(
                            judgeid=assignment.judgeid,
                            teamid=team_id,
                            sheetType=sheet_type,
                        )
                        if not score_sheet_mappings.exists():
                            all_submitted = False
                            break
                        scoresheet_ids = list(
                            score_sheet_mappings.values_list("scoresheetid", flat=True)
                        )
                        existing_scoresheets = Scoresheet.objects.filter(id__in=scoresheet_ids)
                        if (
                            existing_scoresheets.count() < len(scoresheet_ids)
                            or existing_scoresheets.filter(isSubmitted=False).exists()
                        ):
                            all_submitted = False
                            break
                    if not all_submitted:
                        break
                if not all_submitted:
                    break

            if not checked_assignment_team_pair:
                all_submitted = False
            
            results[contest_id] = all_submitted

        return Response(results, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Unexpected error while checking contest scoresheet submissions")
        return Response(
            {"error": "Unable to check scoresheet submission status."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def submit_all_penalty_sheets_for_judge(request):
    judge_id = request.data.get("judge_id")
    if judge_id is None:
        return Response(
            {"detail": "judge_id is required."}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        penalty_mappings = MapScoresheetToTeamJudge.objects.filter(judgeid=judge_id, sheetType=4)

        if not penalty_mappings.exists():
            return Response({"error": "No penalty score sheets found for the provided judge."},
                            status=status.HTTP_404_NOT_FOUND)

        team_ids = set(penalty_mappings.values_list("teamid", flat=True))
        can_submit = _is_admin(request.user) or _judge_role_matches(request.user, judge_id)
        if not can_submit:
            can_submit = all(_can_manage_team(request.user, team_id) for team_id in team_ids)
        if not can_submit:
            return Response(
                {"detail": "You cannot submit penalty scoresheets for this judge."},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            for mapping in penalty_mappings:
                scoresheet = get_object_or_404(Scoresheet, id=mapping.scoresheetid)
                scoresheet.isSubmitted = True
                scoresheet.save()

        return Response(status=status.HTTP_200_OK)

    except DjangoValidationError as e:
        details = e.message_dict if hasattr(e, "message_dict") else e.messages
        return Response({"errors": details}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("Unexpected error while submitting penalty scoresheets")
        return Response(
            {"error": "Unable to submit the penalty scoresheets."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_score_sheet_mapping_by_id(request, map_id):
    map_to_delete = get_object_or_404(MapScoresheetToTeamJudge, id=map_id)
    if not _can_manage_team(request.user, map_to_delete.teamid):
        return Response(
            {"detail": "You cannot delete scoresheet mappings for this team."},
            status=status.HTTP_403_FORBIDDEN,
        )
    map_to_delete.delete()
    return Response({"detail": "Mapping deleted successfully."}, status=status.HTTP_200_OK)


def delete_score_sheet_mapping(map_id):
    # python can't overload functions >:(
    map_to_delete = get_object_or_404(MapScoresheetToTeamJudge, id=map_id)
    map_to_delete.delete()
    return Response({"detail": "Mapping deleted successfully."}, status=status.HTTP_200_OK)


def map_score_sheet(map_data):
    serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data

    raise ValidationError(serializer.errors)


def map_score_sheets_for_team_in_cluster(team_id, cluster_id):
    # Fetch judges assigned to the cluster
    mappings = MapJudgeToCluster.objects.filter(clusterid=cluster_id)
    judge_ids = mappings.values_list('judgeid', flat=True)

    # Fetch scoresheets assigned to the team
    team_judge_mappings = MapScoresheetToTeamJudge.objects.filter(teamid=team_id, judgeid__in=judge_ids)
    scoresheet_ids = team_judge_mappings.values_list('scoresheetid', flat=True)

    # Fetch scoresheets for the team
    scoresheets = Scoresheet.objects.filter(id__in=scoresheet_ids)
    serializer = ScoresheetSerializer(scoresheets, many=True)

    return serializer.data


# Per-team submission status: how many assigned score sheets have been submitted
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def all_submitted_for_team(request, team_id: int):
    try:
        if not _can_manage_team(request.user, team_id):
            return Response(
                {"detail": "You cannot view submission status for this team."},
                status=status.HTTP_403_FORBIDDEN,
            )
        mappings = MapScoresheetToTeamJudge.objects.filter(teamid=team_id)
        total = mappings.count()
        if total == 0:
            return Response({
                "teamId": team_id,
                "submittedCount": 0,
                "totalCount": 0,
                "allSubmitted": False,
            }, status=status.HTTP_200_OK)

        sheet_ids = mappings.values_list("scoresheetid", flat=True)
        submitted_count = Scoresheet.objects.filter(id__in=sheet_ids, isSubmitted=True).count()

        return Response({
            "teamId": team_id,
            "submittedCount": submitted_count,
            "totalCount": total,
            "allSubmitted": submitted_count == total,
        }, status=status.HTTP_200_OK)
    except Exception:
        logger.exception("Unexpected error while checking score sheet submission status")
        return Response(
            {"error": "Unable to load submission status due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
