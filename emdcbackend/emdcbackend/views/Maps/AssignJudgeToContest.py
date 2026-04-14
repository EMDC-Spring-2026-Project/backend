"""
API endpoint to assign an existing judge to additional contests.
This allows the same judge to work on multiple contests.
"""

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

from ...models import MapContestToJudge, Judge, Contest, MapJudgeToCluster, MapContestToTeam, MapScoresheetToTeamJudge, Scoresheet, MapClusterToTeam
from ...serializers import JudgeSerializer
from .MapContestToJudge import create_contest_to_judge_map
from ...views.Maps.MapClusterToJudge import map_cluster_to_judge
from ..judge import sync_judge_sheet_flags


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def assign_judge_to_contest(request):
    """
    Assign an existing judge to an additional contest.
    
    Expected payload:
    {
        "judge_id": 123,
        "contest_id": 456,
        "cluster_id": 789,
        "presentation": true,
        "journal": false,
        "mdo": true,
        "runpenalties": false,
        "otherpenalties": true,
        "redesign": false,
        "championship": true
    }
    """
    try:
        judge_id = request.data.get("judge_id")
        contest_id = request.data.get("contest_id")
        cluster_id = request.data.get("cluster_id")
        
        if not all([judge_id, contest_id, cluster_id]):
            return Response(
                {"error": "judge_id, contest_id, and cluster_id are required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify judge exists
        judge = get_object_or_404(Judge, id=judge_id)
        
        # Verify contest exists
        contest = get_object_or_404(Contest, id=contest_id)
        
        # Check if judge is already assigned to this contest AND cluster combination
        existing_contest_mapping = MapContestToJudge.objects.filter(
            judgeid=judge_id, 
            contestid=contest_id
        ).first()
        
        existing_cluster_mapping = MapJudgeToCluster.objects.filter(
            judgeid=judge_id,
            clusterid=cluster_id
        ).first()
        
        if existing_contest_mapping and existing_cluster_mapping:
            return Response(
                {"error": f"Judge {judge.first_name} {judge.last_name} is already assigned to this contest and cluster combination"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get cluster information to determine if it's championship/redesign/preliminary
        from ...models import JudgeClusters
        try:
            cluster = JudgeClusters.objects.get(id=cluster_id)
            cluster_type = getattr(cluster, 'cluster_type', None)
            # Fallback to checking cluster name if cluster_type is not set
            if not cluster_type:
                if 'championship' in cluster.cluster_name.lower():
                    cluster_type = 'championship'
                elif 'redesign' in cluster.cluster_name.lower():
                    cluster_type = 'redesign'
                else:
                    cluster_type = 'preliminary'
            
            is_championship_cluster = cluster_type == 'championship'
            is_redesign_cluster = cluster_type == 'redesign'
            is_preliminary_cluster = cluster_type == 'preliminary'
        except JudgeClusters.DoesNotExist:
            return Response(
                {"error": f"Cluster {cluster_id} does not exist"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Judges can now be assigned to multiple clusters of any type
        # (previously there was a restriction limiting to 1 cluster per type per contest)

        # Create the contest-judge mapping (only if not already exists)
        if not existing_contest_mapping:
            mapping_data = {
                "contestid": contest_id,
                "judgeid": judge_id
            }
            mapping_result = create_contest_to_judge_map(mapping_data)
        else:
            mapping_result = {"message": "Judge already assigned to contest"}
        
        # Create score sheets for the judge in this contest's cluster
        from ...views.scoresheets import create_sheets_for_teams_in_cluster

        # Determine scoresheet flags for this assignment
        presentation = request.data.get("presentation", False)
        journal = request.data.get("journal", False)
        mdo = request.data.get("mdo", False)
        runpenalties = request.data.get("runpenalties", False)
        otherpenalties = request.data.get("otherpenalties", False)
        redesign = request.data.get("redesign", False)
        championship = request.data.get("championship", False)
        
        # Validate scoresheet combinations based on cluster type
        has_preliminary_sheets = presentation or journal or mdo or runpenalties or otherpenalties
        has_redesign_sheets = redesign
        has_championship_sheets = championship
        
        if is_championship_cluster and (has_preliminary_sheets or has_redesign_sheets):
            return Response(
                {"error": "Championship clusters can only have Championship scoresheets"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if is_redesign_cluster and (has_preliminary_sheets or has_championship_sheets):
            return Response(
                {"error": "Redesign clusters can only have Redesign scoresheets"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not is_championship_cluster and not is_redesign_cluster and (has_redesign_sheets or has_championship_sheets):
            return Response(
                {"error": "Preliminary clusters cannot have Redesign or Championship scoresheets"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Auto-set championship/redesign flags based on cluster type
        if is_championship_cluster:
            championship = True
            presentation = journal = mdo = runpenalties = otherpenalties = redesign = False
        elif is_redesign_cluster:
            redesign = True
            presentation = journal = mdo = runpenalties = otherpenalties = championship = False

        # Persist the cluster-level permissions
        cluster_mapping_data = {
            "judgeid": judge_id,
            "clusterid": cluster_id,
            "contestid": contest_id,
            "presentation": presentation,
            "journal": journal,
            "mdo": mdo,
            "runpenalties": runpenalties,
            "otherpenalties": otherpenalties,
            "redesign": redesign,
            "championship": championship,
        }

        try:
            cluster_mapping_result = map_cluster_to_judge(cluster_mapping_data)
        except Exception:
            cluster_mapping_result = {"message": "Cluster mapping failed"}

        sheets_result = create_sheets_for_teams_in_cluster(
            judge_id,
            cluster_id,
            presentation,
            journal,
            mdo,
            runpenalties,
            otherpenalties,
            redesign,
            championship,
        )

        # Keep legacy judge flags in sync across all clusters
        sync_judge_sheet_flags(judge_id)
        
        return Response({
            "message": f"Judge {judge.first_name} {judge.last_name} successfully assigned to contest {contest.name}",
            "mapping": mapping_result,
            "cluster_mapping": cluster_mapping_result,
            "score_sheets": sheets_result
        }, status=status.HTTP_201_CREATED)
        
    except ValidationError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_judge_contests(request, judge_id):
    """
    Get all contests that a judge is assigned to.
    
    Returns:
    {
        "judge": {judge_data},
        "contests": [{contest_data}]
    }
    """
    try:
        judge = get_object_or_404(Judge, id=judge_id)
        
        # Get all contest IDs for this judge
        contest_ids = MapContestToJudge.objects.filter(
            judgeid=judge_id
        ).values_list('contestid', flat=True)
        
        # Get contest details
        contests = Contest.objects.filter(id__in=contest_ids)
        
        from ...serializers import ContestSerializer
        judge_serializer = JudgeSerializer(judge)
        contest_serializer = ContestSerializer(contests, many=True)
        
        return Response({
            "judge": judge_serializer.data,
            "contests": contest_serializer.data
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def remove_judge_from_contest(request, judge_id, contest_id):
    """
    Remove a judge from a specific contest.
    This will also clean up their score sheets for that contest.
    """
    try:
        
        # Find the mapping
        mapping = get_object_or_404(
            MapContestToJudge, 
            judgeid=judge_id, 
            contestid=contest_id
        )
        
        # Get the judge's cluster to clean up scoresheets
        cluster_mapping = MapJudgeToCluster.objects.filter(judgeid=judge_id).first()
        
        # Clean up scoresheets for this judge-contest combination
        if cluster_mapping:
            # Get all teams in the contest
            contest_teams = MapContestToTeam.objects.filter(contestid=contest_id)
            team_ids = contest_teams.values_list('teamid', flat=True)
            
            # Delete scoresheets for this judge and contest teams
            scoresheet_mappings = MapScoresheetToTeamJudge.objects.filter(
                judgeid=judge_id,
                teamid__in=team_ids
            )
            # Get scoresheet IDs to delete
            scoresheet_ids = scoresheet_mappings.values_list('scoresheetid', flat=True)
            
            # Delete the scoresheets
            deleted_scoresheets = Scoresheet.objects.filter(id__in=scoresheet_ids).delete()
            
            # Delete the scoresheet mappings
            deleted_mappings = scoresheet_mappings.delete()
            
            # Delete the cluster-judge mapping
            cluster_mapping.delete()
        else:
            deleted_scoresheets = (0, {})
            deleted_mappings = (0, {})
        
        # Delete the contest-judge mapping
        mapping.delete()
        
        return Response({
            "message": f"Judge {judge_id} removed from contest {contest_id}",
            "details": {
                "scoresheets_deleted": deleted_scoresheets[0],
                "mappings_deleted": deleted_mappings[0]
            }
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def remove_judge_from_cluster(request, judge_id, cluster_id):
    """
    Remove a judge from a specific cluster only.
    This will clean up their score sheets for that cluster.
    If the judge is no longer in any clusters for the contest, also remove the contest-judge mapping.
    """
    from django.db import transaction
    from ...models import MapContestToCluster
        
    try:
        with transaction.atomic():
        # Find the cluster-judge mapping
            cluster_mapping = get_object_or_404(
            MapJudgeToCluster, 
            judgeid=judge_id, 
            clusterid=cluster_id
        )
        
        # Get the contest ID for this cluster (to check if judge should be removed from contest)
        contest_cluster_mapping = MapContestToCluster.objects.filter(clusterid=cluster_id).first()
        contest_id = contest_cluster_mapping.contestid if contest_cluster_mapping else None
        
        # IMPORTANT: Do NOT delete scoresheets when removing judge from cluster!
        # Scoresheets belong to judge-team relationships, not judge-cluster relationships.
        # Only delete scoresheets when judge is completely removed from contest or team is removed from contest.
        
        # Delete the cluster-judge mapping
        cluster_mapping.delete()
        
        # Check if judge is still in any other clusters for this contest
        # If not, remove the contest-judge mapping
        contest_judge_mapping_deleted = False
        if contest_id:
            # Get all clusters for this contest
            contest_cluster_ids = list(MapContestToCluster.objects.filter(
                contestid=contest_id
            ).values_list('clusterid', flat=True))
            
            # Check if judge is still in any of those clusters
            remaining_cluster_mappings = MapJudgeToCluster.objects.filter(
                judgeid=judge_id,
                clusterid__in=contest_cluster_ids
            ).exists()
            
            # If judge is not in any clusters for this contest, remove contest-judge mapping
            if not remaining_cluster_mappings:
                contest_judge_mappings = MapContestToJudge.objects.filter(
                    judgeid=judge_id,
                    contestid=contest_id
                )
                if contest_judge_mappings.exists():
                    contest_judge_mappings.delete()
                    contest_judge_mapping_deleted = True
        
        return Response({
            "message": f"Judge {judge_id} removed from cluster {cluster_id}",
            "details": {
                "scoresheets_deleted": 0,  # Scoresheets are preserved when removing from cluster
                "mappings_deleted": 0,     # No scoresheet mappings deleted
                "contest_judge_mapping_deleted": contest_judge_mapping_deleted
            }
        }, status=status.HTTP_200_OK)
        
    except MapJudgeToCluster.DoesNotExist:
        return Response({
            "error": f"Judge {judge_id} is not assigned to cluster {cluster_id}"
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        import traceback
        return Response({
            "error": f"Failed to remove judge from cluster: {str(e)}"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
