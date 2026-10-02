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
from django.db import models
from django.shortcuts import get_object_or_404
from ...models import JudgeClusters, Judge, MapJudgeToCluster, MapContestToCluster, MapContestToOrganizer, MapScoresheetToTeamJudge, Scoresheet, MapClusterToTeam, MapUserToRole
from django.db import transaction
from ...serializers import JudgeClustersSerializer, JudgeSerializer, ClusterToJudgeSerializer


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

    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        
        # Filter by active status if the field exists
        try:
            test_cluster = clusters.first()
            if test_cluster and hasattr(test_cluster, 'is_active'):
                clusters = clusters.filter(
                    models.Q(is_active=True) | models.Q(is_active__isnull=True)
                )
            else:
                pass
        except Exception as filter_error:
            pass
        
        # Return the first active cluster (for backward compatibility)
        if clusters.exists():
            cluster = clusters.first()
            serializer = JudgeClustersSerializer(instance=cluster)
            return Response({"Cluster": serializer.data}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "No active clusters found for the given judge"}, status=status.HTTP_404_NOT_FOUND)
            
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def all_clusters_by_judge_id(request, judge_id):
    """Get all clusters for a judge across all contests"""
    try:
        
        mappings = MapJudgeToCluster.objects.filter(judgeid=judge_id)
        cluster_ids = mappings.values_list('clusterid', flat=True)
        
        # Get all clusters for this judge
        clusters = JudgeClusters.objects.filter(id__in=cluster_ids)
        
        # Filter by is_active status (now that field exists)
        clusters = clusters.filter(is_active=True)
        
        serializer = JudgeClustersSerializer(clusters, many=True)
        cluster_data = serializer.data

        assignment_map = {
            (assignment.clusterid): assignment
            for assignment in MapJudgeToCluster.objects.filter(judgeid=judge_id, clusterid__in=cluster_ids)
        }

        # Add contest information and sheet flags to each cluster
        for cluster in cluster_data:
            try:
                contest_mapping = MapContestToCluster.objects.filter(clusterid=cluster['id']).first()
                cluster['contest_id'] = contest_mapping.contestid if contest_mapping else None
            except Exception:
                cluster['contest_id'] = None

            assignment = assignment_map.get(cluster["id"])
            if assignment:
                cluster["sheet_flags"] = {
                    "presentation": assignment.presentation,
                    "journal": assignment.journal,
                    "mdo": assignment.mdo,
                    "runpenalties": assignment.runpenalties,
                    "otherpenalties": assignment.otherpenalties,
                    "redesign": assignment.redesign,
                    "championship": assignment.championship,
                }

        return Response({"Clusters": cluster_data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
        contest_cluster_mapping = MapContestToCluster.objects.filter(clusterid=cluster_id).first()
        contest_id = contest_cluster_mapping.contestid if contest_cluster_mapping else None

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
        if team_ids:
            score_map_qs = MapScoresheetToTeamJudge.objects.filter(judgeid=judge_id, teamid__in=team_ids)
            scoresheet_ids = list(score_map_qs.values_list('scoresheetid', flat=True))
            # Delete mappings first, then scoresheets
            score_map_qs.delete()
            if scoresheet_ids:
                Scoresheet.objects.filter(id__in=scoresheet_ids).delete()
        
        # For championship/redesign clusters, delete advanced scoresheets (types 6 and 7)
        # for this judge and teams in this specific contest to prevent stale data when judges are moved between clusters
        if is_advanced_cluster and cluster and contest_id:
            # Get all teams in this contest
            contest_team_ids = list(
                MapContestToTeam.objects.filter(contestid=contest_id).values_list('teamid', flat=True)
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
                    Scoresheet.objects.filter(id__in=old_scoresheet_ids).delete()

        # Delete the judge<->cluster mapping
        mapping.delete()
        
        # Check if judge is still in any other clusters for this contest
        # If not, remove the contest-judge mapping
        if contest_id:
            # Get all clusters for this contest
            contest_cluster_ids = MapContestToCluster.objects.filter(
                contestid=contest_id
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
                    contestid=contest_id
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

    if contestid is None:
        contest_mapping = MapContestToCluster.objects.filter(clusterid=clusterid).first()
        contestid = contest_mapping.contestid if contest_mapping else None

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
