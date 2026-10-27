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
from ..models import Votes
from ..serializers import VotesSerializer
from ..permissions import is_admin_user

# Votes Views
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_vote(request):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        serializer = VotesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_all_votes(request):
    if not is_admin_user(request.user):
        return Response({"detail": "Admin access is required."}, status=status.HTTP_403_FORBIDDEN)
    try:
        votes = Votes.objects.all()
        serializer = VotesSerializer(votes, many=True)
        return Response({"votes": serializer.data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
