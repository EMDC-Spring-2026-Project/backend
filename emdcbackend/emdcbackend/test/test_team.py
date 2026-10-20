from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from unittest.mock import patch
from ..models import (
    Teams, Contest, Coach, MapUserToRole, Admin, JudgeClusters,
    MapContestToCluster, MapContestToTeam, MapClusterToTeam, MapCoachToTeam,
    Judge, MapContestToJudge,
)
from ..serializers import TeamSerializer


class TeamAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an admin user for role mapping
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

        # Create a contest
        from datetime import date
        self.contest = Contest.objects.create(
            name="Test Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        self.cluster = JudgeClusters.objects.create(
            cluster_name="Preliminary Cluster", cluster_type="preliminary"
        )
        MapContestToCluster.objects.create(
            contestid=self.contest.id, clusterid=self.cluster.id
        )

    def test_team_by_id(self):
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
        url = reverse('team_by_id', args=[team.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['Team']['team_name'], "Test Team")

    def test_get_all_teams(self):
        Teams.objects.create(
            team_name="Team 1",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        Teams.objects.create(
            team_name="Team 2",
            journal_score=95.0,
            presentation_score=90.0,
            machinedesign_score=85.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=270.0,
            championship_score=0.0
        )
        
        url = reverse('get_all_teams')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['teams']), 2)

    def test_team_by_id_requires_sign_in(self):
        team = Teams.objects.create(team_name="Private Team")
        self.client.logout()

        response = self.client.get(reverse('team_by_id', args=[team.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unrelated_user_cannot_view_team(self):
        team = Teams.objects.create(team_name="Unrelated Team")
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        unrelated = User.objects.create_user(
            username="unrelated-team@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unrelated)

        response = self.client.get(reverse('team_by_id', args=[team.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_judge_team_list_is_limited_to_assigned_contests(self):
        assigned_team = Teams.objects.create(team_name="Assigned Team")
        MapContestToTeam.objects.create(
            contestid=self.contest.id, teamid=assigned_team.id
        )
        other_contest = Contest.objects.create(
            name="Other Contest", date=self.contest.date,
            is_open=True, is_tabulated=False,
        )
        other_team = Teams.objects.create(team_name="Other Team")
        MapContestToTeam.objects.create(
            contestid=other_contest.id, teamid=other_team.id
        )
        judge = Judge.objects.create(
            first_name="Team", last_name="Judge", contestid=self.contest.id,
            phone_number="5551112222",
        )
        judge_user = User.objects.create_user(
            username="team-judge@example.com", password="testpassword"
        )
        MapUserToRole.objects.create(
            uuid=judge_user.id, role=MapUserToRole.RoleEnum.JUDGE,
            relatedid=judge.id,
        )
        MapContestToJudge.objects.create(
            contestid=self.contest.id, judgeid=judge.id
        )
        self.client.force_authenticate(user=judge_user)

        detail_response = self.client.get(
            reverse('team_by_id', args=[assigned_team.id])
        )
        list_response = self.client.get(reverse('get_all_teams'))

        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [team["id"] for team in list_response.data["teams"]],
            [assigned_team.id],
        )

    def test_create_team(self):
        url = reverse('create_team')
        data = {
            "username": "coach@example.com",
            "password": "coachpassword",
            "first_name": "Coach",
            "last_name": "Name",
            "team_name": "New Team",
            "contestid": self.contest.id,
            "clusterid": self.cluster.id
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    @patch("emdcbackend.views.coach.send_set_password_email")
    @patch("emdcbackend.views.team.make_sheets_for_team", side_effect=RuntimeError("generation failed"))
    def test_create_team_rolls_back_if_scoresheet_generation_fails(
        self, _mock_make_sheets, mock_send_email
    ):
        initial_counts = {
            "teams": Teams.objects.count(),
            "coaches": Coach.objects.count(),
            "users": User.objects.count(),
        }

        response = self.client.post(
            reverse('create_team'),
            {
                "username": "rollback-coach@example.com",
                "password": "coachpassword",
                "first_name": "Rollback",
                "last_name": "Coach",
                "team_name": "Rollback Team",
                "contestid": self.contest.id,
                "clusterid": self.cluster.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(Teams.objects.count(), initial_counts["teams"])
        self.assertEqual(Coach.objects.count(), initial_counts["coaches"])
        self.assertEqual(User.objects.count(), initial_counts["users"])
        self.assertFalse(MapContestToTeam.objects.exists())
        self.assertFalse(MapClusterToTeam.objects.exists())
        self.assertFalse(MapCoachToTeam.objects.exists())
        mock_send_email.assert_not_called()

    def test_unprivileged_user_cannot_change_team_roster(self):
        team = Teams.objects.create(team_name="Protected Team")
        from ..models import MapContestToTeam
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        unprivileged_user = User.objects.create_user(
            username="unprivileged@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unprivileged_user)

        response = self.client.delete(reverse('delete_team_by_id', args=[team.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Teams.objects.filter(id=team.id).exists())

    def test_edit_team(self):
        team = Teams.objects.create(
            team_name="Original Team",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        
        coach = Coach.objects.create(first_name="Coach", last_name="Name")
        coach_user = User.objects.create_user(username="coachuser@example.com", password="password")
        MapUserToRole.objects.create(uuid=coach_user.id, role=4, relatedid=coach.id)
        from ..models import MapCoachToTeam, MapContestToTeam
        MapCoachToTeam.objects.create(teamid=team.id, coachid=coach.id)
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)

        url = reverse('edit_team')
        data = {
            "id": team.id,
            "username": "coachuser@example.com",
            "first_name": "Coach",
            "last_name": "Name",
            "team_name": "Updated Team",
            "contestid": self.contest.id,
            "clusterid": self.cluster.id
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        team.refresh_from_db()
        self.assertEqual(team.team_name, "Updated Team")

    def test_edit_team_accepts_partial_request(self):
        team = Teams.objects.create(team_name="Original Team")
        coach = Coach.objects.create(first_name="Original", last_name="Coach")
        coach_user = User.objects.create_user(
            username="partial-coach@example.com", password="password"
        )
        MapUserToRole.objects.create(uuid=coach_user.id, role=4, relatedid=coach.id)
        from ..models import MapCoachToTeam, MapContestToTeam
        MapCoachToTeam.objects.create(teamid=team.id, coachid=coach.id)
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)

        response = self.client.post(
            reverse('edit_team'),
            {"id": team.id, "team_name": "Updated Team"},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        team.refresh_from_db()
        coach.refresh_from_db()
        self.assertEqual(team.team_name, "Updated Team")
        self.assertEqual(coach.first_name, "Original")
        self.assertEqual(coach.last_name, "Coach")

    def test_delete_team_by_id(self):
        team = Teams.objects.create(
            team_name="To Delete",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        from ..models import MapContestToTeam
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        url = reverse('delete_team_by_id', args=[team.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(Teams.objects.filter(id=team.id).exists())

    def test_edit_missing_team_returns_not_found(self):
        response = self.client.post(
            reverse('edit_team'), {"id": 999999}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_is_team_disqualified(self):
        team = Teams.objects.create(
            team_name="Test Team",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0,
            organizer_disqualified=True
        )
        url = reverse('is_team_disqualified', args=[team.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('is disqualified', False))

    def test_create_team_after_judge(self):
        """Test creating a team after judge assignment"""
        url = reverse('create_team_after_judge')
        data = {
            "username": "coach@example.com",
            "password": "coachpassword",
            "first_name": "Coach",
            "last_name": "Name",
            "team_name": "New Team After Judge",
            "contestid": self.contest.id,
            "clusterid": self.cluster.id
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_create_team_rejects_cluster_from_another_contest_atomically(self):
        from datetime import date
        other_contest = Contest.objects.create(
            name="Other Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        other_cluster = JudgeClusters.objects.create(
            cluster_name="Other Cluster", cluster_type="preliminary"
        )
        MapContestToCluster.objects.create(
            contestid=other_contest.id, clusterid=other_cluster.id
        )
        initial_team_count = Teams.objects.count()
        initial_user_count = User.objects.count()

        response = self.client.post(
            reverse('create_team'),
            {
                "username": "wrong-cluster-coach@example.com",
                "password": "coachpassword",
                "first_name": "Coach",
                "last_name": "Name",
                "team_name": "Wrong Cluster Team",
                "contestid": self.contest.id,
                "clusterid": other_cluster.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Teams.objects.count(), initial_team_count)
        self.assertEqual(User.objects.count(), initial_user_count)

    def test_unprivileged_user_cannot_use_create_team_after_judge(self):
        unprivileged_user = User.objects.create_user(
            username="ordinary-team-creator@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unprivileged_user)

        response = self.client.post(
            reverse('create_team_after_judge'),
            {
                "username": "new-coach@example.com",
                "password": "coachpassword",
                "first_name": "New",
                "last_name": "Coach",
                "team_name": "Unauthorized Team",
                "contestid": self.contest.id,
                "clusterid": self.cluster.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Teams.objects.filter(team_name="Unauthorized Team").exists())

    def test_get_teams_by_team_rank(self):
        """Test getting teams by team rank"""
        # Create teams with ranks
        team1 = Teams.objects.create(
            team_name="Team 1",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0,
            team_rank=1
        )
        team2 = Teams.objects.create(
            team_name="Team 2",
            journal_score=95.0,
            presentation_score=90.0,
            machinedesign_score=85.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=270.0,
            championship_score=0.0,
            team_rank=2
        )
        
        # Map teams to contest
        from ..models import MapContestToTeam
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team1.id)
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team2.id)
        
        url = reverse('get_teams_by_team_rank')
        response = self.client.get(url, data={"contestid": self.contest.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn('Teams', response.data)

    def test_get_teams_by_team_rank_missing_contestid(self):
        """Test get_teams_by_team_rank with missing contestid"""
        url = reverse('get_teams_by_team_rank')
        response = self.client.get(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
