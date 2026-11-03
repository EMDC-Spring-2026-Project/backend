import logging

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from ...serializers import MapVoteToAwardSerializer, MapAwardToContestSerializer
from ...permissions import is_admin_user

logger = logging.getLogger(__name__)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_map_vote_to_award(request):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        serializer = MapVoteToAwardSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("Unexpected error while creating vote-to-award mapping")
        return Response(
            {"error": "Unable to create vote award mapping due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_map_award_to_contest(request):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        serializer = MapAwardToContestSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("Unexpected error while creating award-to-contest mapping")
        return Response(
            {"error": "Unable to create contest award mapping due to a server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
