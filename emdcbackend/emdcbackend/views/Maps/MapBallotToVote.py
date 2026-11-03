import logging

from django.core.exceptions import FieldError
from django.shortcuts import get_object_or_404
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
from ...serializers import MapBallotToVoteSerializer
from ...permissions import is_admin_user

logger = logging.getLogger(__name__)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_map_ballot_to_vote(request):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        serializer = MapBallotToVoteSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("Unexpected error while linking ballot to vote")
        return Response(
            {"error": "Unable to link the ballot and vote due to an unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
