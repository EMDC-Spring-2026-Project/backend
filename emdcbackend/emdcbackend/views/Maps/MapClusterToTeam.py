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
from ...models import JudgeClusters, Teams, MapClusterToTeam, MapJudgeToCluster, MapContestToCluster, MapContestToOrganizer, MapUserToRole
from ...serializers import TeamSerializer, ClusterToTeamSerializer, JudgeClustersSerializer
from rest_framework.exceptions import ValidationError


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
def create_cluster_team_mapping(request):
    cluster_id = request.data.get("clusterid")
    if not cluster_id:
        return Response({"detail": "clusterid is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not _can_manage_cluster(request.user, cluster_id):
        return Response({"detail": "You are not allowed to change this cluster."}, status=status.HTTP_403_FORBIDDEN)
    serializer = ClusterToTeamSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"mapping": serializer.data}, status=status.HTTP_200_OK)
    return Response(
        serializer.errors, status=status.HTTP_400_BAD_REQUEST
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def teams_by_cluster_id(request, cluster_id):
    try:
        mappings = MapClusterToTeam.objects.filter(clusterid=cluster_id)
        team_ids = mappings.values_list("teamid", flat=True)
        teams = Teams.objects.filter(id__in=team_ids)
        serialized_teams = TeamSerializer(teams, many=True).data

        for team in serialized_teams:
            mapping = mappings.filter(teamid=team["id"]).first()
            team["map_id"] = mapping.id if mapping else None

        return Response({"Teams": serialized_teams}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def cluster_by_team_id(request, team_id):
    try:
        mappings = MapClusterToTeam.objects.filter(teamid=team_id)
        if not mappings.exists():
            return Response({"error": "No clusters found for the given team"}, status=status.HTTP_404_NOT_FOUND)
        cluster_ids = [mapping.clusterid for mapping in mappings]
        clusters = JudgeClusters.objects.filter(id__in=cluster_ids)
        serializer = JudgeClustersSerializer(clusters, many=True)
        return Response({"Clusters": serializer.data}, status=status.HTTP_200_OK)
    except JudgeClusters.DoesNotExist:
        return Response({"error": "One or more clusters not found for the given IDs"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_cluster_team_mapping_by_id(request, map_id):
    try:
        map_to_delete = get_object_or_404(MapClusterToTeam, id=map_id)
        if not _can_manage_cluster(request.user, map_to_delete.clusterid):
            return Response({"detail": "You are not allowed to change this cluster."}, status=status.HTTP_403_FORBIDDEN)
        # teamid on mapping is an integer FK id in our schema; keep it as a raw id
        team_id = map_to_delete.teamid
        map_to_delete.delete()

        all_teams_cluster = JudgeClusters.objects.filter(cluster_name="All Teams").first()
        if all_teams_cluster:
            if not MapClusterToTeam.objects.filter(teamid=team_id, clusterid=all_teams_cluster.id).exists():
                new_map_data = {"clusterid": all_teams_cluster.id, "teamid": team_id}
                serializer = ClusterToTeamSerializer(data=new_map_data)
                if serializer.is_valid():
                    serializer.save()

        return Response({"detail": "Team removed from cluster and moved to All Teams."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_teams_by_cluster_rank(request):
    try:
        clusterid = int(request.query_params.get("clusterid", ""))
        if clusterid <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"detail": "clusterid must be a positive integer"}, status=status.HTTP_400_BAD_REQUEST)
    mappings = MapClusterToTeam.objects.filter(clusterid=clusterid)
    teams = Teams.objects.filter(
        id__in=mappings.values_list('teamid', flat=True),
        cluster_rank__isnull=False
    ).order_by('cluster_rank')
    serializer = TeamSerializer(teams, many=True)
    return Response({"Teams": serializer.data}, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def teams_by_judge_id(request, judge_id):
    try:
        # Get all clusters assigned to this judge
        judge_cluster_mappings = MapJudgeToCluster.objects.filter(judgeid=judge_id)
        cluster_ids = judge_cluster_mappings.values_list('clusterid', flat=True)

        if not cluster_ids:
            return Response({"Teams": []}, status=status.HTTP_200_OK)

        # Get all team mappings for these clusters
        team_mappings = MapClusterToTeam.objects.filter(clusterid__in=cluster_ids)
        team_ids = team_mappings.values_list('teamid', flat=True).distinct()

        # Get the actual team objects
        teams = Teams.objects.filter(id__in=team_ids)
        serializer = TeamSerializer(teams, many=True)

        return Response({"Teams": serializer.data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def create_team_to_cluster_map(map_data):
    serializer = ClusterToTeamSerializer(data=map_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    else:
        return ValidationError(serializer.errors)
