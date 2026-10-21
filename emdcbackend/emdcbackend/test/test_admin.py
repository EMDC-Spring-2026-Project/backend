from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from ..models import Admin, MapUserToRole
from ..serializers import AdminSerializer
from django.contrib.auth.models import User
from unittest.mock import patch


class AdminTests(APITestCase):

    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser", password="testpassword")
        self.client.login(username="testuser", password="testpassword")

        # Create an admin object
        self.admin = Admin.objects.create(
            first_name="Test",
            last_name="User",
        )

        # Create a user-role mapping
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

    def test_admin_by_id(self):
        url = reverse("admin_by_id", args=[self.admin.id])
        response = self.client.get(url)
        expected_data = {"Admin": AdminSerializer(instance=self.admin).data}
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, expected_data)

    def test_admins_get_all(self):
        url = reverse("admins_get_all")
        response = self.client.get(url)
        expected_data = {"Admins": AdminSerializer(Admin.objects.all(), many=True).data}
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, expected_data)

    def test_create_admin(self):
        url = reverse("create_admin")
        data = {
            "username": "newadmin@example.com",
            "password": "NewPassword123!",
            "first_name": "New",
            "last_name": "Admin",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["admin"]["first_name"], "New")

    @patch("emdcbackend.auth.views.send_set_password_email")
    @patch(
        "emdcbackend.views.admin.create_user_role_map",
        side_effect=RuntimeError("role mapping failed"),
    )
    def test_failed_admin_creation_rolls_back_without_sending_email(
        self, _create_role, mock_send_email
    ):
        response = self.client.post(
            reverse("create_admin"),
            {
                "username": "rollback-admin@example.com",
                "password": "NewPassword123!",
                "first_name": "Rollback",
                "last_name": "Admin",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertFalse(User.objects.filter(username="rollback-admin@example.com").exists())
        self.assertFalse(Admin.objects.filter(first_name="Rollback").exists())
        mock_send_email.assert_not_called()

    def test_edit_admin(self):
        url = reverse("edit_admin")
        data = {
            "id": self.admin.id,
            "first_name": "Updated",
            "last_name": "User",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["Admin"]["first_name"], "Updated")

    def test_edit_admin_accepts_partial_request(self):
        response = self.client.post(
            reverse("edit_admin"),
            {"id": self.admin.id, "first_name": "Updated"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, "Updated")
        self.assertEqual(self.admin.last_name, "User")

    def test_delete_admin(self):
        url = reverse("delete_admin", args=[self.admin.id])
        response = self.client.delete(url)
        # Note: This might fail if the mapping doesn't exist or has wrong field names
        # The actual response depends on the implementation
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["Detail"], "Admin deleted successfully.")
        self.assertFalse(Admin.objects.filter(id=self.admin.id).exists())

    def test_delete_missing_admin_returns_not_found(self):
        response = self.client.delete(reverse("delete_admin", args=[999999]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_admin_cannot_access_admin_management(self):
        ordinary_user = User.objects.create_user(
            username="ordinary@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=ordinary_user)

        detail_response = self.client.get(
            reverse("admin_by_id", args=[self.admin.id])
        )
        list_response = self.client.get(reverse("admins_get_all"))
        create_response = self.client.post(
            reverse("create_admin"),
            {
                "username": "unauthorized-admin@example.com",
                "password": "Password123!",
                "first_name": "Unauthorized",
                "last_name": "Admin",
            },
        )
        edit_response = self.client.post(
            reverse("edit_admin"),
            {
                "id": self.admin.id,
                "first_name": "Changed",
                "last_name": "Name",
            },
        )
        delete_response = self.client.delete(
            reverse("delete_admin", args=[self.admin.id])
        )

        for response in (
            detail_response,
            list_response,
            create_response,
            edit_response,
            delete_response,
        ):
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, "Test")
        self.assertFalse(User.objects.filter(username="unauthorized-admin@example.com").exists())
