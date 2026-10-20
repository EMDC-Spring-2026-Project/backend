from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from datetime import date
from ..models import (
    Contest, Teams, Judge, JudgeClusters, MapContestToTeam, MapContestToOrganizer,
    MapUserToRole, Organizer, MapClusterToTeam, MapContestToCluster
)


class AdvanceAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an organizer user for role mapping
        self.organizer = Organizer.objects.create(first_name="Test", last_name="Organizer")
        MapUserToRole.objects.create(uuid=self.user.id, role=2, relatedid=self.organizer.id)

        # Create test data
        self.contest = Contest.objects.create(
            name="Test Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        self.team = Teams.objects.create(
            team_name="Test Team",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0,
            preliminary_journal_score=90.0,
            preliminary_presentation_score=85.0,
            preliminary_machinedesign_score=80.0,
            preliminary_penalties_score=0.0,
            preliminary_total_score=255.0
        )
        
        # Create clusters
        self.preliminary_cluster = JudgeClusters.objects.create(
            cluster_name="Preliminary Cluster",
            cluster_type="preliminary"
        )
        self.championship_cluster = JudgeClusters.objects.create(
            cluster_name="Championship Cluster",
            cluster_type="championship"
        )
        self.redesign_cluster = JudgeClusters.objects.create(
            cluster_name="Redesign Cluster",
            cluster_type="redesign"
        )
        
        # Map contest to organizer and team
        MapContestToOrganizer.objects.create(contestid=self.contest.id, organizerid=self.organizer.id)
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=self.team.id)
        
        # Map clusters to contest
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.preliminary_cluster.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.championship_cluster.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.redesign_cluster.id)
        
        # Map team to preliminary cluster
        MapClusterToTeam.objects.create(clusterid=self.preliminary_cluster.id, teamid=self.team.id)

    def test_advance_to_championship(self):
        """Test advancing teams to championship"""
        url = reverse('advance_to_championship')
        data = {
            "contestid": self.contest.id,
            "championship_team_ids": [self.team.id]
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertTrue(self.team.advanced_to_championship)

    def test_advance_to_championship_missing_contestid(self):
        """Test advance_to_championship with missing contestid"""
        url = reverse('advance_to_championship')
        data = {"championship_team_ids": [self.team.id]}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_advance_to_championship_missing_team_ids(self):
        """Test advance_to_championship with missing championship_team_ids"""
        url = reverse('advance_to_championship')
        data = {"contestid": self.contest.id}
        response = self.client.post(url, data, format='json')
        # Should accept empty list or return error
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_advance_to_championship_invalid_team_ids_type(self):
        """Test advance_to_championship with invalid team_ids type"""
        url = reverse('advance_to_championship')
        data = {"contestid": self.contest.id, "championship_team_ids": "not_a_list"}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_advance_to_championship_permission_denied(self):
        """Test advance_to_championship when user is not an organizer"""
        # Create a new user without organizer role and login
        other_user = User.objects.create_user(username="otheruser@example.com", password="testpassword")
        self.client.logout()  # Logout current user
        self.client.login(username="otheruser@example.com", password="testpassword")
        
        url = reverse('advance_to_championship')
        data = {"contestid": self.contest.id, "championship_team_ids": [self.team.id]}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_championship_cluster_does_not_change_team_state(self):
        self.team.advanced_to_championship = True
        self.team.championship_rank = 1
        self.team.save()
        MapContestToCluster.objects.filter(
            contestid=self.contest.id, clusterid=self.championship_cluster.id
        ).delete()

        response = self.client.post(
            reverse('advance_to_championship'),
            {"contestid": self.contest.id, "championship_team_ids": []},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.team.refresh_from_db()
        self.assertTrue(self.team.advanced_to_championship)
        self.assertEqual(self.team.championship_rank, 1)

    def test_undo_championship_advancement(self):
        """Test undoing championship advancement"""
        # First advance a team
        self.team.advanced_to_championship = True
        self.team.save()
        
        url = reverse('undo_championship_advancement')
        data = {"contestid": self.contest.id}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertFalse(self.team.advanced_to_championship)

    def test_undo_championship_advancement_missing_contestid(self):
        """Test undo_championship_advancement with missing contestid"""
        url = reverse('undo_championship_advancement')
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_undo_championship_advancement_permission_denied(self):
        """Test undo_championship_advancement when user is not an organizer"""
        # Create a new user without organizer role and login
        other_user = User.objects.create_user(username="otheruser@example.com", password="testpassword")
        self.client.logout()  # Logout current user
        self.client.login(username="otheruser@example.com", password="testpassword")
        
        url = reverse('undo_championship_advancement')
        data = {"contestid": self.contest.id}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
