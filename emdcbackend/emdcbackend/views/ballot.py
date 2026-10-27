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
from ..models import Ballot
from ..serializers import BallotSerializer
from ..permissions import is_admin_user

# Ballot Views
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_ballot(request):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        serializer = BallotSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_all_ballots(request):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        ballots = Ballot.objects.all()
        serializer = BallotSerializer(ballots, many=True)
        return Response({"ballots": serializer.data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_ballot(request, ballot_id):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        ballot = Ballot.objects.get(id=ballot_id)
        ballot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    except Ballot.DoesNotExist:
        return Response({"error": "Ballot not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
