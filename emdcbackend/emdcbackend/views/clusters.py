from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.db import transaction
from ..models import JudgeClusters, MapContestToCluster, MapContestToOrganizer, MapUserToRole
from ..serializers import JudgeClustersSerializer
from .Maps.MapClusterToContest import  map_cluster_to_contest
from ..models import Teams, MapClusterToTeam


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


def _can_manage_cluster(user, cluster_id):
  if user.is_superuser or MapUserToRole.objects.filter(
      uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
  ).exists():
    return True
  contest_ids = list(MapContestToCluster.objects.filter(
      clusterid=cluster_id
  ).values_list("contestid", flat=True))
  # Cluster edits and deletion affect every contest using the shared cluster.
  return bool(contest_ids) and all(
      _can_manage_contest(user, contest_id) for contest_id in contest_ids
  )

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def cluster_by_id(request, cluster_id):
  cluster = get_object_or_404(JudgeClusters, id = cluster_id)
  serializer = JudgeClustersSerializer(instance=cluster)
  return Response({"Cluster": serializer.data}, status=status.HTTP_200_OK)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def clusters_get_all(request):
  clusters = JudgeClusters.objects.all()
  serializer = JudgeClustersSerializer(clusters, many=True)
  return Response({"Clusters":serializer.data}, status=status.HTTP_200_OK)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_cluster(request):
  try:
    contest_id = request.data.get("contestid")
    if not contest_id:
      return Response({"detail": "contestid is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not _can_manage_contest(request.user, contest_id):
      return Response({"detail": "You are not allowed to manage clusters for this contest."}, status=status.HTTP_403_FORBIDDEN)
    with transaction.atomic():
      cluster_response = make_cluster(request.data)
      responses = [
        map_cluster_to_contest({
          "contestid": contest_id,
          "clusterid": cluster_response.get("id")
        })
      ]
      
      # Check for any errors in mapping responses
      for response in responses:
        if isinstance(response, Response):
          return response

      return Response({
        "cluster": cluster_response,
        "cluster to contest map:": responses[0]
      }, status=status.HTTP_201_CREATED)

  except ValidationError as e:  # Catching ValidationErrors specifically
    return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
  
  except Exception as e:
    return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_cluster(request):
    cluster = get_object_or_404(JudgeClusters, id=request.data["id"])
    if not _can_manage_cluster(request.user, cluster.id):
        return Response({"detail": "You are not allowed to manage this cluster."}, status=status.HTTP_403_FORBIDDEN)
    
    # Cannot change from preliminary to championship/redesign
    original_type = (cluster.cluster_type or "preliminary").lower()
    new_type = request.data.get("cluster_type", original_type).lower()
    
    if original_type == "preliminary" and new_type in ["championship", "redesign"]:
        return Response(
            {"error": "Cannot change preliminary cluster to championship/redesign."}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    cluster.cluster_name = request.data["cluster_name"]
    if "cluster_type" in request.data:
        cluster.cluster_type = request.data["cluster_type"]
    cluster.save()

    serializer = JudgeClustersSerializer(instance=cluster)
    return Response({"cluster": serializer.data}, status=status.HTTP_200_OK)

@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_cluster(request, cluster_id):
    try:
        with transaction.atomic():
            cluster = get_object_or_404(JudgeClusters, id=cluster_id)
            if not _can_manage_cluster(request.user, cluster.id):
                return Response({"detail": "You are not allowed to manage this cluster."}, status=status.HTTP_403_FORBIDDEN)
            
            # Import mapping models
            from ..models import (
                MapClusterToTeam,
                MapJudgeToCluster,
                MapContestToCluster,
            )
            
            # Delete all mappings that reference this cluster
            MapClusterToTeam.objects.filter(clusterid=cluster_id).delete()
            MapJudgeToCluster.objects.filter(clusterid=cluster_id).delete()
            MapContestToCluster.objects.filter(clusterid=cluster_id).delete()
            
            # Now delete the cluster
            cluster.delete()
            
            return Response({"detail": "Cluster and all associated mappings deleted successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"detail": f"Error deleting cluster: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def make_judge_cluster_instance(data):
  serializer = JudgeClustersSerializer(data=data)
  if serializer.is_valid():
      serializer.save()
      return serializer.data
  raise ValidationError(serializer.errors)


def make_cluster(data):
  cluster_data = {
    "cluster_name": data["cluster_name"],
    "cluster_type": data.get("cluster_type", "preliminary")
  }
  cluster_response = make_judge_cluster_instance(cluster_data)
  if not cluster_response.get('id'):
        raise ValidationError('Cluster creation failed.')
  return cluster_response
