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
from ...models import JudgeClusters, Judge, MapJudgeToCluster, MapContestToCluster, MapContestToOrganizer, MapScoresheetToTeamJudge, Scoresheet, MapClusterToTeam, MapUserToRole
from django.db import transaction
from ...serializers import JudgeClustersSerializer, JudgeSerializer, ClusterToJudgeSerializer

logger = logging.getLogger(__name__)


def _can_manage_cluster(user, cluster_id):
    if user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists():
        return True
    organizer_ids = list(MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
    ).values_list("relatedid", flat=True))
    contest_ids = set(MapContestToCluster.objects.filter(
        clusterid=cluster_id
    ).values_list("contestid", flat=True))
    if not organizer_ids or not contest_ids:
        return False
    managed_contest_ids = set(MapContestToOrganizer.objects.filter(
        contestid__in=contest_ids, organizerid__in=organizer_ids
    ).values_list("contestid", flat=True))
    return contest_ids.issubset(managed_contest_ids)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_cluster_judge_mapping(request):
    try:
        map_data = request.data
        cluster_id = map_data.get("clusterid")
        if not cluster_id:
            return Response({"detail": "clusterid is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not _can_manage_cluster(request.user, cluster_id):
            return Response({"detail": "You are not allowed to change this cluster."}, status=status.HTTP_403_FORBIDDEN)
        result = map_cluster_to_judge(map_data)
        return Response(result, status=status.HTTP_201_CREATED)

    except ValidationError as e:
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)

    except Exception:
        logger.exception("Unexpected error while assigning judge to cluster")
        return Response(
            {"detail": "Unable to save the judge assignment due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def judges_by_cluster_id(request, cluster_id):
    mappings = MapJudgeToCluster.objects.filter(clusterid=cluster_id)
    judge_ids = mappings.values_list('judgeid', flat=True)
    judges = Judge.objects.filter(id__in=judge_ids)

    serializer = JudgeSerializer(judges, many=True)
    judge_data = serializer.data

    assignment_map = {assignment.judgeid: assignment for assignment in mappings}

    for entry in judge_data:
        assignment = assignment_map.get(entry["id"])
        if assignment:
            entry["cluster_sheet_flags"] = {
                "presentation": assignment.presentation,
                "journal": assignment.journal,
                "mdo": assignment.mdo,
                "runpenalties": assignment.runpenalties,
                "otherpenalties": assignment.otherpenalties,
                "redesign": assignment.redesign,
                "championship": assignment.championship,
            }

    return Response({"Judges": judge_data}, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def cluster_by_judge_id(request, judge_id):
    try:
        
        # Get all cluster mappings for this judge (judge can be in multiple clusters)
        mappings = MapJudgeToCluster.objects.filter(judgeid=judge_id)
        
        if not mappings.exists():
            return Response({"error": "No clusters found for the given judge"}, status=status.HTTP_404_NOT_FOUND)
        
        # Get all clusters for this judge
        cluster_ids = mappings.values_list('clusterid', flat=True)
        clusters = JudgeClusters.objects.filter(id__in=cluster_ids)
        
        clusters = clusters.filter(is_active=True)
        
        # Return the first active cluster (for backward compatibility)
        if clusters.exists():
            cluster = clusters.first()
            serializer = JudgeClustersSerializer(instance=cluster)
            return Response({"Cluster": serializer.data}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "No active clusters found for the given judge"}, status=status.HTTP_404_NOT_FOUND)
            
    except Exception:
        logger.exception("Unexpected error while loading cluster for judge %s", judge_id)
        return Response(
            {"error": "Unable to load the judge's cluster due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def all_clusters_by_judge_id(request, judge_id):
    """Get all clusters for a judge across all contests"""
    try:
        
        mappings = list(MapJudgeToCluster.objects.filter(judgeid=judge_id))
        cluster_ids = [mapping.clusterid for mapping in mappings]
        clusters_by_id = {
            cluster.id: cluster
            for cluster in JudgeClusters.objects.filter(
                id__in=cluster_ids, is_active=True
            )
        }

        cluster_data = []
        for assignment in mappings:
            cluster = clusters_by_id.get(assignment.clusterid)
            if cluster is None:
                continue

            contest_ids = set(MapContestToCluster.objects.filter(
                clusterid=cluster.id
            ).values_list("contestid", flat=True))
            if assignment.contestid is not None:
                # A contest-specific judge assignment is authoritative. Ignore
                # stale mappings whose cluster is no longer linked to it.
                if assignment.contestid not in contest_ids:
                    continue
                contest_id = assignment.contestid
            elif len(contest_ids) == 1:
                # Legacy assignments are safe to infer only for a single-contest cluster.
                contest_id = next(iter(contest_ids))
            elif len(contest_ids) > 1:
                # An old assignment on a shared cluster cannot be attributed safely.
                continue
            else:
                contest_id = None

            cluster_payload = JudgeClustersSerializer(instance=cluster).data
            cluster_payload["contest_id"] = contest_id
            cluster_payload["sheet_flags"] = {
                "presentation": assignment.presentation,
                "journal": assignment.journal,
                "mdo": assignment.mdo,
                "runpenalties": assignment.runpenalties,
                "otherpenalties": assignment.otherpenalties,
                "redesign": assignment.redesign,
                "championship": assignment.championship,
            }
            cluster_data.append(cluster_payload)

        return Response({"Clusters": cluster_data}, status=status.HTTP_200_OK)
    except Exception:
        logger.exception("Unexpected error while loading clusters for judge %s", judge_id)
        return Response(
            {"error": "Unable to load judge clusters due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _delete_cluster_judge_mapping_and_scores(map_id: int):
    """Delete a MapJudgeToCluster mapping and all related judge->team scoresheets for that cluster.
    Also removes MapContestToJudge entry if judge is no longer in any clusters for that contest.
    
    For championship/redesign clusters, also cleans up old advanced scoresheets
    (types 6 and 7) for teams in this contest to prevent stale data when judges are moved
    between clusters."""
    with transaction.atomic():
        mapping = get_object_or_404(MapJudgeToCluster, id=map_id)
        judge_id = mapping.judgeid
        cluster_id = mapping.clusterid

        # Get the contest ID for this cluster (to check if judge should be removed from contest)
        from ...models import MapContestToCluster, MapContestToJudge, MapContestToTeam
        contest_ids = set(MapContestToCluster.objects.filter(
            clusterid=cluster_id
        ).values_list("contestid", flat=True))
        assignment_contest_id = mapping.contestid
        if assignment_contest_id not in contest_ids:
            assignment_contest_id = next(iter(contest_ids), None)

        # Get cluster type to determine if we need to clean up advanced scoresheets
        cluster = None
        cluster_type = None
        try:
            cluster = JudgeClusters.objects.get(id=cluster_id)
            cluster_type = getattr(cluster, 'cluster_type', None)
            is_advanced_cluster = (
                cluster_type in ['championship', 'redesign'] or
                'championship' in (cluster.cluster_name or '').lower() or
                'redesign' in (cluster.cluster_name or '').lower()
            )
        except JudgeClusters.DoesNotExist:
            is_advanced_cluster = False

        team_ids = list(MapClusterToTeam.objects.filter(clusterid=cluster_id).values_list('teamid', flat=True))
        if not team_ids and contest_ids:
            team_ids = list(MapContestToTeam.objects.filter(
                contestid__in=contest_ids
            ).values_list("teamid", flat=True))

        # Scoresheet mappings have no cluster/contest key. Keep mappings for
        # teams shared with another contest or another cluster for this judge.
        shared_team_ids = set(MapContestToTeam.objects.filter(
            teamid__in=team_ids
        ).exclude(contestid__in=contest_ids).values_list("teamid", flat=True))
        other_cluster_ids = MapJudgeToCluster.objects.filter(
            judgeid=judge_id
        ).exclude(clusterid=cluster_id).values_list("clusterid", flat=True)
        other_cluster_ids = list(other_cluster_ids)
        other_cluster_team_ids = set(MapClusterToTeam.objects.filter(
            clusterid__in=other_cluster_ids, teamid__in=team_ids
        ).values_list("teamid", flat=True))
        other_contest_ids = MapContestToCluster.objects.filter(
            clusterid__in=other_cluster_ids
        ).values_list("contestid", flat=True)
        other_cluster_team_ids.update(MapContestToTeam.objects.filter(
            contestid__in=other_contest_ids, teamid__in=team_ids
        ).values_list("teamid", flat=True))
        shared_team_ids.update(other_cluster_team_ids)
        team_ids_to_clean = [team_id for team_id in team_ids if team_id not in shared_team_ids]
        if team_ids:
            score_map_qs = MapScoresheetToTeamJudge.objects.filter(
                judgeid=judge_id, teamid__in=team_ids_to_clean
            )
            scoresheet_ids = list(score_map_qs.values_list('scoresheetid', flat=True))
            # Delete mappings first, then scoresheets
            score_map_qs.delete()
            if scoresheet_ids:
                still_referenced_ids = MapScoresheetToTeamJudge.objects.filter(
                    scoresheetid__in=scoresheet_ids
                ).values_list("scoresheetid", flat=True)
                Scoresheet.objects.filter(id__in=scoresheet_ids).exclude(
                    id__in=still_referenced_ids
                ).delete()
        
        # For championship/redesign clusters, delete advanced scoresheets (types 6 and 7)
        # for this judge and teams in this specific contest to prevent stale data when judges are moved between clusters
        if is_advanced_cluster and cluster and assignment_contest_id:
            # Get all teams in this contest
            contest_team_ids = list(
                MapContestToTeam.objects.filter(contestid__in=contest_ids).exclude(
                    teamid__in=shared_team_ids
                ).values_list('teamid', flat=True)
            )
            
            if contest_team_ids:
                # Determine which sheet types to delete based on cluster type
                cluster_name_lower = (cluster.cluster_name or '').lower()
                if cluster_type == 'redesign' or 'redesign' in cluster_name_lower:
                    # Delete all redesign scoresheets (type 6) for this judge and teams in this contest
                    old_advanced_sheets = MapScoresheetToTeamJudge.objects.filter(
                        judgeid=judge_id,
                        teamid__in=contest_team_ids,
                        sheetType=6  # Redesign only
                    )
                elif cluster_type == 'championship' or 'championship' in cluster_name_lower:
                    # Delete all championship scoresheets (type 7) for this judge and teams in this contest
                    old_advanced_sheets = MapScoresheetToTeamJudge.objects.filter(
                        judgeid=judge_id,
                        teamid__in=contest_team_ids,
                        sheetType=7  # Championship only
                    )
                else:
                    # Fallback: delete both types if cluster type is unclear
                    old_advanced_sheets = MapScoresheetToTeamJudge.objects.filter(
                        judgeid=judge_id,
                        teamid__in=contest_team_ids,
                        sheetType__in=[6, 7]  # Both redesign and championship
                    )
                
                old_scoresheet_ids = list(old_advanced_sheets.values_list('scoresheetid', flat=True))
                old_advanced_sheets.delete()
                if old_scoresheet_ids:
                    still_referenced_ids = MapScoresheetToTeamJudge.objects.filter(
                        scoresheetid__in=old_scoresheet_ids
                    ).values_list("scoresheetid", flat=True)
                    Scoresheet.objects.filter(id__in=old_scoresheet_ids).exclude(
                        id__in=still_referenced_ids
                    ).delete()

        # Delete the judge<->cluster mapping
        mapping.delete()
        
        # Check if judge is still in any other clusters for this contest
        # If not, remove the contest-judge mapping
        if contest_ids:
            # Get all clusters for this contest
            contest_cluster_ids = MapContestToCluster.objects.filter(
                contestid__in=contest_ids
            ).values_list('clusterid', flat=True)
            
            # Check if judge is still in any of those clusters
            remaining_cluster_mappings = MapJudgeToCluster.objects.filter(
                judgeid=judge_id,
                clusterid__in=contest_cluster_ids
            ).exists()
            
            # If judge is not in any clusters for this contest, remove contest-judge mapping
            if not remaining_cluster_mappings:
                MapContestToJudge.objects.filter(
                    judgeid=judge_id,
                    contestid__in=contest_ids
                ).delete()


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_cluster_judge_mapping_by_id(request, map_id):
    mapping = get_object_or_404(MapJudgeToCluster, id=map_id)
    if not _can_manage_cluster(request.user, mapping.clusterid):
        return Response({"detail": "You are not allowed to change this cluster."}, status=status.HTTP_403_FORBIDDEN)
    _delete_cluster_judge_mapping_and_scores(map_id)
    return Response({"detail": "Cluster To Judge Mapping deleted successfully."}, status=status.HTTP_200_OK)


def map_cluster_to_judge(map_data):
    judgeid = map_data["judgeid"]
    clusterid = map_data["clusterid"]
    contestid = map_data.get("contestid")
    if isinstance(contestid, bool):
        raise ValidationError({"contestid": "contestid must be a positive integer."})
    if contestid is not None:
        try:
            contestid = int(contestid)
        except (TypeError, ValueError):
            raise ValidationError({"contestid": "contestid must be a positive integer."})
        if contestid <= 0:
            raise ValidationError({"contestid": "contestid must be a positive integer."})
    cluster_contest_ids = set(
        MapContestToCluster.objects.filter(clusterid=clusterid)
        .values_list("contestid", flat=True)
    )

    if contestid is None:
        if len(cluster_contest_ids) > 1:
            raise ValidationError(
                {"contestid": "contestid is required when the cluster belongs to multiple contests."}
            )
        contestid = next(iter(cluster_contest_ids), None)
    elif cluster_contest_ids and contestid not in cluster_contest_ids:
        raise ValidationError(
            {"contestid": "The selected contest does not use this cluster."}
        )

    defaults = {
        "contestid": contestid,
        "presentation": map_data.get("presentation", False),
        "journal": map_data.get("journal", False),
        "mdo": map_data.get("mdo", False),
        "runpenalties": map_data.get("runpenalties", False),
        "otherpenalties": map_data.get("otherpenalties", False),
        "redesign": map_data.get("redesign", False),
        "championship": map_data.get("championship", False),
    }

    assignment, created = MapJudgeToCluster.objects.get_or_create(
        judgeid=judgeid,
        clusterid=clusterid,
        defaults=defaults
    )

    if not created:
        if (
            assignment.contestid is not None
            and contestid is not None
            and assignment.contestid != contestid
        ):
            raise ValidationError(
                {"contestid": "This judge is already assigned to this cluster for another contest."}
            )
        for field, value in defaults.items():
            setattr(assignment, field, value)
        assignment.save()

    serializer = ClusterToJudgeSerializer(instance=assignment)
    return serializer.data
    

def delete_cluster_judge_mapping(cluster_id: int, judge_id: int):
    """
    Deletes the judge<->cluster mapping (by cluster_id + judge_id) and
    cascades delete of related judge->team scoresheets for that cluster.
    Returns a dict you can send in a Response.
    """
    mapping = MapJudgeToCluster.objects.filter(
        clusterid=cluster_id,
        judgeid=judge_id
    ).first()

    if not mapping:
        # Reuse DRF ValidationError already imported at top
        raise ValidationError("Mapping not found for the given cluster_id and judge_id.")

    _delete_cluster_judge_mapping_and_scores(mapping.id)
    return {"detail": "Cluster To Judge Mapping deleted successfully.", "deleted": 1}
