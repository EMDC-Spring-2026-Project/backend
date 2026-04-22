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
from ..serializers import AdminSerializer
from ..models import Admin
from ..auth.views import create_user
from ..auth.views import delete_user
from .Maps.MapUserToRole import create_user_role_map
from ..models import MapUserToRole
from ..auth.views import User, delete_user_by_id

# get an admin by a certain id
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def admin_by_id(request, admin_id):
  admin = get_object_or_404(Admin, id = admin_id)
  serializer = AdminSerializer(instance=admin)
  return Response({"Admin": serializer.data}, status=status.HTTP_200_OK)

# get all admins
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def admins_get_all(request):
  admins = Admin.objects.all()
  serializer = AdminSerializer(admins, many=True)
  return Response({"Admins":serializer.data}, status=status.HTTP_200_OK)

# create an admin
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_admin(request):
    username = request.data.get("username")
    if not username:
        return Response({"detail": "username is required"}, status=status.HTTP_400_BAD_REQUEST)

    # Prevent duplicate admin creation for the same user
    existing_user = User.objects.filter(username__iexact=username).first()
    if existing_user:
        existing_map = MapUserToRole.objects.filter(
            uuid=existing_user.id, role=MapUserToRole.RoleEnum.ADMIN
        ).first()
        if existing_map:
            existing_admin = Admin.objects.filter(id=existing_map.relatedid).first()
            admin_data = AdminSerializer(existing_admin).data if existing_admin else None
            return Response(
                {
                    "success": True,
                    "message": "Admin already exists for this user",
                    "user": {"id": existing_user.id, "username": existing_user.username},
                    "admin": admin_data,
                },
                status=status.HTTP_200_OK,
            )

    try:
        with transaction.atomic():
            user_response, admin_response = create_user_and_admin(request.data)
            role_mapping = create_user_role_map({
                "uuid": user_response.get("user").get("id"),
                "role": 1,
                "relatedid": admin_response.get("id")
            })
            if not role_mapping:
                raise ValidationError('Failed to create admin role mapping.')

            responses = [role_mapping]
                
            return Response({
                "user": user_response,
                "admin": admin_response,
                "user_map": responses[0],
            }, status=status.HTTP_201_CREATED)

    except ValidationError as e:  # Catching ValidationErrors specifically
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
  
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def create_user_and_admin(data):
    user_data = {"username": data["username"], "password": data["password"]}
    user_response = create_user(user_data)
    if not user_response.get('user'):
        raise ValidationError('User creation failed.')
    
    admin_data = {"first_name": data["first_name"], "last_name": data["last_name"]}
    admin_response = make_admin(admin_data)
    if not admin_response.get('id'):
        raise ValidationError('Admin creation failed.')
    
    return user_response, admin_response

def make_admin(data):
    serializer = AdminSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    raise ValidationError(serializer.errors)

# edit an admin
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_admin(request):
    admin = get_object_or_404(Admin, id=request.data["id"])
    admin.first_name = request.data["first_name"]
    admin.last_name = request.data["last_name"]
    admin.save()

    serializer = AdminSerializer(instance=admin)
    return Response({"Admin": serializer.data}, status=status.HTTP_200_OK)


# delete an admin by a certain id
@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_admin(request, admin_id):
    try:
        admin = get_object_or_404(Admin, id=admin_id)
        admin_mapping = MapUserToRole.objects.get(role=MapUserToRole.RoleEnum.ADMIN, relatedid=admin_id)
        user_id = admin_mapping.uuid
        admin.delete()
        admin_mapping.delete()
        delete_user(user_id)
        return Response({"Detail": "Admin deleted successfully."}, status=status.HTTP_200_OK)
    except Admin.DoesNotExist:
        return Response({"error": "Admin not found."}, status=status.HTTP_404_NOT_FOUND)
    except MapUserToRole.DoesNotExist:
        return Response({"error": "Admin mapping not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    