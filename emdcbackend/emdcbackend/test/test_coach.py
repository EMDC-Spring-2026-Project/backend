from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from ..models import Coach, MapUserToRole, Admin
from ..serializers import CoachSerializer


class CoachAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an admin user for role mapping
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

    def test_coach_by_id(self):
        coach = Coach.objects.create(first_name="Test", last_name="Coach")
        url = reverse('coach_by_id', args=[coach.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['Coach']['first_name'], "Test")

    def test_coach_get_all(self):
        Coach.objects.create(first_name="Coach 1", last_name="Test")
        Coach.objects.create(first_name="Coach 2", last_name="Test")
        
        url = reverse('coach_get_all')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['Coaches']), 2)

    def test_create_coach(self):
        url = reverse('create_coach')
        data = {
            "first_name": "New",
            "last_name": "Coach"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['coach']['first_name'], "New")

    def test_edit_coach(self):
        coach = Coach.objects.create(first_name="Original", last_name="Coach")
        
        # Create user and mapping
        coach_user = User.objects.create_user(username="coachuser@example.com", password="password")
        MapUserToRole.objects.create(uuid=coach_user.id, role=4, relatedid=coach.id)

        url = reverse('edit_coach')
        data = {
            "id": coach.id,
            "first_name": "Updated",
            "last_name": "Coach",
            "school_name": "Test School"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['coach']['first_name'], "Updated")

    def test_edit_coach_accepts_partial_request(self):
        coach = Coach.objects.create(first_name="Original", last_name="Coach")

        response = self.client.post(
            reverse('edit_coach'),
            {"id": coach.id, "first_name": "Updated"},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        coach.refresh_from_db()
        self.assertEqual(coach.first_name, "Updated")
        self.assertEqual(coach.last_name, "Coach")

    def test_delete_coach(self):
        coach = Coach.objects.create(first_name="To Delete", last_name="Coach")
        
        # Create user and mapping for coach (required for delete)
        coach_user = User.objects.create_user(username="coachdelete@example.com", password="password")
        MapUserToRole.objects.create(uuid=coach_user.id, role=4, relatedid=coach.id)
        
        url = reverse('delete_coach', args=[coach.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(Coach.objects.filter(id=coach.id).exists())

    def test_delete_missing_coach_returns_not_found(self):
        response = self.client.delete(reverse('delete_coach', args=[999999]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
