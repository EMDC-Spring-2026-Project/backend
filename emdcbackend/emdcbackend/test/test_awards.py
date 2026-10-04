from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from datetime import date
from ..models import (
    SpecialAward, Teams, Admin, Organizer, Judge, Contest, MapUserToRole,
    MapContestToOrganizer, MapContestToJudge, MapContestToTeam,
)


class AwardAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an admin user for role mapping
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

        # Create test data
        self.team = Teams.objects.create(
            team_name="Test Team",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )

    def test_get_all_awards(self):
        SpecialAward.objects.create(teamid=self.team.id, award_name="Best Design", isJudge=True)
        SpecialAward.objects.create(teamid=self.team.id, award_name="Best Presentation", isJudge=False)
        
        url = reverse('get_all_awards')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data.get('awards', [])), 2)

    def test_create_award_team_mapping(self):
        url = reverse('create_award_team_mapping')
        data = {
            "teamid": self.team.id,
            "award_name": "Best Innovation",
            "isJudge": True
        }
        response = self.client.post(url, data)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(SpecialAward.objects.filter(teamid=self.team.id, award_name="Best Innovation").exists())

    def test_get_award_by_team_id(self):
        SpecialAward.objects.create(teamid=self.team.id, award_name="Best Design", isJudge=True)
        
        url = reverse('get_award_id_by_team_id', args=[self.team.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_award_team_mapping(self):
        award = SpecialAward.objects.create(teamid=self.team.id, award_name="Best Design", isJudge=True)
        
        url = reverse('delete_award_team_mapping_by_id', args=[self.team.id, "Best Design"])
        response = self.client.delete(url)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT])
        self.assertFalse(SpecialAward.objects.filter(id=award.id).exists())

    def test_update_award_team_mapping(self):
        award = SpecialAward.objects.create(teamid=self.team.id, award_name="Best Design", isJudge=True)
        
        url = reverse('update_award_team_mapping', args=[self.team.id, "Best Design"])
        data = {
            "award_name": "Best Innovation",
            "isJudge": False
        }
        # Use PUT method (as per view decorator)
        response = self.client.put(url, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_get_awards_by_role(self):
        SpecialAward.objects.create(teamid=self.team.id, award_name="Judge Award", isJudge=True)
        SpecialAward.objects.create(teamid=self.team.id, award_name="Organizer Award", isJudge=False)
        
        url = reverse('get_awards_by_role', args=["True"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unprivileged_user_cannot_change_awards(self):
        award = SpecialAward.objects.create(
            teamid=self.team.id, award_name="Protected Award", isJudge=False
        )
        unprivileged_user = User.objects.create_user(
            username="ordinary@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unprivileged_user)

        create_response = self.client.post(
            reverse('create_award_team_mapping'),
            {"teamid": 0, "award_name": "Unauthorized Award", "isJudge": False},
        )
        update_response = self.client.put(
            reverse(
                'update_award_team_mapping',
                args=[award.teamid, award.award_name],
            ),
            {"teamid": self.team.id, "award_name": "Changed", "isJudge": False},
            format='json',
        )
        delete_response = self.client.delete(
            reverse(
                'delete_award_team_mapping_by_id',
                args=[award.teamid, award.award_name],
            )
        )

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)
        award.refresh_from_db()
        self.assertEqual(award.award_name, "Protected Award")

    def test_judge_can_assign_judge_award_only_within_assigned_contest(self):
        contest = Contest.objects.create(
            name="Judge Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        other_contest = Contest.objects.create(
            name="Other Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        other_team = Teams.objects.create(team_name="Other Team")
        MapContestToTeam.objects.create(contestid=contest.id, teamid=self.team.id)
        MapContestToTeam.objects.create(contestid=other_contest.id, teamid=other_team.id)
        judge = Judge.objects.create(
            first_name="Award",
            last_name="Judge",
            phone_number="5551234567",
            contestid=contest.id,
            presentation=True,
            journal=True,
            mdo=False,
        )
        judge_user = User.objects.create_user(
            username="award-judge@example.com", password="testpassword"
        )
        MapUserToRole.objects.create(uuid=judge_user.id, role=3, relatedid=judge.id)
        MapContestToJudge.objects.create(contestid=contest.id, judgeid=judge.id)
        judge_award = SpecialAward.objects.create(
            teamid=0, award_name="Judge Choice", isJudge=True
        )
        self.client.force_authenticate(user=judge_user)

        allowed_response = self.client.put(
            reverse(
                'update_award_team_mapping',
                args=[judge_award.teamid, judge_award.award_name],
            ),
            {"teamid": self.team.id, "award_name": judge_award.award_name, "isJudge": True},
            format='json',
        )
        self.assertEqual(allowed_response.status_code, status.HTTP_200_OK)

        denied_response = self.client.put(
            reverse(
                'update_award_team_mapping',
                args=[self.team.id, judge_award.award_name],
            ),
            {"teamid": other_team.id, "award_name": judge_award.award_name, "isJudge": True},
            format='json',
        )
        self.assertEqual(denied_response.status_code, status.HTTP_403_FORBIDDEN)
