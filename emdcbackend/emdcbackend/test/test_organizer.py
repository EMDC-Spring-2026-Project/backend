from rest_framework import status
from rest_framework.test import APITestCase
from django.urls import reverse
from ..models import Organizer, MapUserToRole, Contest, Teams, MapContestToOrganizer, MapContestToTeam
from django.contrib.auth import get_user_model
from ..serializers import OrganizerSerializer  # Assuming you have a serializer for Organizer

User = get_user_model()

class OrganizerAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser", password="testpassword")
        self.client.login(username="testuser", password="testpassword")

        # Create an organizer object
        self.organizer = Organizer.objects.create(
            first_name="Test",
            last_name="User"
        )

        # Create a user-role mapping
        MapUserToRole.objects.create(uuid=self.user.id, role=2, relatedid=self.organizer.id)

    def get_auth_headers(self):
        # Session authentication doesn't need headers, return empty dict
        return {}

    def test_organizer_by_id(self):
        url = reverse('organizer_by_id', args=[self.organizer.id])
        response = self.client.get(url)
        expected_data = {"organizer": OrganizerSerializer(instance=self.organizer).data}
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, expected_data)

    def test_create_organizer(self):
        url = reverse('create_organizer')
        data = {
            "username": "neworganizer@example.com",  # Must be a valid email
            "password": "newpassword",
            "first_name": "New",
            "last_name": "Organizer"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['organizer']['first_name'], "New")

    def test_edit_organizer(self):
        url = reverse('edit_organizer')  # Pass the organizer ID
        data = {
            "id": self.organizer.id,  # Add the ID here
            "username": "updated@example.com",  # Must be a valid email
            "first_name": "Updated",
            "last_name": "User"
        }
        response = self.client.post(url, data)  # Use the method
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['organizer']['first_name'], "Updated")

    def test_delete_organizer(self):
        url = reverse('delete_organizer', args=[self.organizer.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["Detail"], "Organizer and all related mappings deleted successfully.")
        self.assertFalse(Organizer.objects.filter(id=self.organizer.id).exists())

    def test_organizer_disqualify_team(self):
        """Test organizer disqualifying a team"""
        team = Teams.objects.create(
            team_name="Test Team",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        contest = Contest.objects.create(
            name="Test Contest", date="2026-01-01", is_open=True, is_tabulated=False
        )
        MapContestToOrganizer.objects.create(contestid=contest.id, organizerid=self.organizer.id)
        MapContestToTeam.objects.create(contestid=contest.id, teamid=team.id)
        url = reverse('organizer_disqualify_team')
        data = {"teamid": team.id, "organizer_disqualified": True}
        response = self.client.post(url, data, format='json', **self.get_auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        team.refresh_from_db()
        self.assertTrue(team.organizer_disqualified)

    def test_unassigned_organizer_cannot_disqualify_team(self):
        team = Teams.objects.create(team_name="Protected Team")
        response = self.client.post(
            reverse('organizer_disqualify_team'),
            {"teamid": team.id, "organizer_disqualified": True}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        team.refresh_from_db()
        self.assertFalse(team.organizer_disqualified)
