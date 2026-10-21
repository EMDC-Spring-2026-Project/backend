from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from ..models import (
    Judge, Contest, JudgeClusters, MapUserToRole, MapContestToJudge,
    MapJudgeToCluster, Teams, MapContestToCluster, MapContestToTeam,
    Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge,
)
from ..serializers import JudgeSerializer


class JudgeAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create a contest
        from datetime import date
        self.contest = Contest.objects.create(
            name="Test Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )

        # Create a cluster
        self.cluster = JudgeClusters.objects.create(cluster_name="Test Cluster")
        MapContestToCluster.objects.create(
            contestid=self.contest.id, clusterid=self.cluster.id
        )

        # Create an admin user for role mapping
        from ..models import Admin
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

    def test_judge_by_id(self):
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            mdo=False,
            journal=True
        )
        url = reverse('judge_by_id', args=[judge.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['Judge']['first_name'], "Test")

    def test_get_all_judges(self):
        Judge.objects.create(
            first_name="Judge 1",
            last_name="Test",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            mdo=False,
            journal=False
        )
        Judge.objects.create(
            first_name="Judge 2",
            last_name="Test",
            phone_number="0987654321",
            contestid=self.contest.id,
            presentation=False,
            mdo=True,
            journal=False
        )
        
        url = reverse('get_all_judges')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['Judges']), 2)

    def test_judge_directory_requires_sign_in(self):
        judge = Judge.objects.create(
            first_name="Private",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
        )
        self.client.logout()

        detail_response = self.client.get(reverse('judge_by_id', args=[judge.id]))
        list_response = self.client.get(reverse('get_all_judges'))

        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_judge(self):
        url = reverse('create_judge')
        data = {
            "username": "judge@example.com",
            "password": "judgepassword",
            "first_name": "New",
            "last_name": "Judge",
            "phone_number": "1234567890",
            "contestid": self.contest.id,
            "clusterid": self.cluster.id,
            "presentation": True,
            "mdo": False,
            "journal": True,
            "runpenalties": False,
            "otherpenalties": False,
            "redesign": False,
            "championship": False
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['judge']['first_name'], "New")

    def test_create_judge_rejects_cluster_from_another_contest_atomically(self):
        from datetime import date
        other_contest = Contest.objects.create(
            name="Other Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        other_cluster = JudgeClusters.objects.create(cluster_name="Other Cluster")
        MapContestToCluster.objects.create(
            contestid=other_contest.id, clusterid=other_cluster.id
        )
        initial_user_count = User.objects.count()
        initial_judge_count = Judge.objects.count()

        response = self.client.post(
            reverse('create_judge'),
            {
                "username": "wrong-cluster-judge@example.com",
                "password": "judgepassword",
                "first_name": "Wrong",
                "last_name": "Cluster",
                "phone_number": "1234567890",
                "contestid": self.contest.id,
                "clusterid": other_cluster.id,
                "presentation": True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.count(), initial_user_count)
        self.assertEqual(Judge.objects.count(), initial_judge_count)

    def test_edit_judge_rejects_cluster_from_another_contest_before_changes(self):
        from datetime import date
        judge = Judge.objects.create(
            first_name="Original", last_name="Judge", phone_number="1234567890",
            contestid=self.contest.id,
        )
        judge_user = User.objects.create_user(
            username="protected-judge@example.com", password="password"
        )
        MapUserToRole.objects.create(uuid=judge_user.id, role=3, relatedid=judge.id)
        MapContestToJudge.objects.create(contestid=self.contest.id, judgeid=judge.id)
        MapJudgeToCluster.objects.create(
            judgeid=judge.id, clusterid=self.cluster.id, contestid=self.contest.id
        )
        other_contest = Contest.objects.create(
            name="Other Edit Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        other_cluster = JudgeClusters.objects.create(cluster_name="Other Edit Cluster")
        MapContestToCluster.objects.create(
            contestid=other_contest.id, clusterid=other_cluster.id
        )

        response = self.client.post(
            reverse('edit_judge'),
            {
                "id": judge.id,
                "first_name": "Should Not Persist",
                "contestid": self.contest.id,
                "clusterid": other_cluster.id,
                "presentation": True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        judge.refresh_from_db()
        self.assertEqual(judge.first_name, "Original")
        self.assertTrue(
            MapJudgeToCluster.objects.filter(
                judgeid=judge.id, clusterid=self.cluster.id
            ).exists()
        )

    def test_edit_judge(self):
        judge = Judge.objects.create(
            first_name="Original",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            mdo=False,
            journal=True
        )
        
        # Create user and mapping
        judge_user = User.objects.create_user(username="judgeuser@example.com", password="password")
        MapUserToRole.objects.create(uuid=judge_user.id, role=3, relatedid=judge.id)
        MapContestToJudge.objects.create(contestid=self.contest.id, judgeid=judge.id)
        MapJudgeToCluster.objects.create(judgeid=judge.id, clusterid=self.cluster.id)

        url = reverse('edit_judge')
        data = {
            "id": judge.id,
            "username": "judgeuser@example.com",
            "first_name": "Updated",
            "last_name": "Judge",
            "phone_number": "0987654321",
            "contestid": self.contest.id,
            "clusterid": self.cluster.id,
            "presentation": False,
            "mdo": True,
            "journal": False,
            "runpenalties": True,
            "otherpenalties": False,
            "redesign": False,
            "championship": False,
            "role": 1
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        judge.refresh_from_db()
        self.assertEqual(judge.first_name, "Updated")
        self.assertEqual(judge.phone_number, "0987654321")

    def test_edit_judge_accepts_partial_request_without_removing_clusters(self):
        judge = Judge.objects.create(
            first_name="Original",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            role=Judge.JudgeRoleEnum.GENERAL,
        )
        judge_user = User.objects.create_user(
            username="partial-judge@example.com", password="password"
        )
        MapUserToRole.objects.create(uuid=judge_user.id, role=3, relatedid=judge.id)
        assignment = MapJudgeToCluster.objects.create(
            judgeid=judge.id,
            clusterid=self.cluster.id,
            contestid=self.contest.id,
            presentation=True,
        )

        response = self.client.post(
            reverse('edit_judge'),
            {"id": judge.id, "phone_number": "9999999999"},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        judge.refresh_from_db()
        assignment.refresh_from_db()
        self.assertEqual(judge.first_name, "Original")
        self.assertEqual(judge.phone_number, "9999999999")
        self.assertTrue(assignment.presentation)

    def test_delete_judge(self):
        self.client.force_authenticate(user=self.user)
        self.assertTrue(MapUserToRole.objects.filter(uuid=self.user.id, role=1).exists())
        judge = Judge.objects.create(
            first_name="To Delete",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            mdo=False,
            journal=False
        )
        url = reverse('delete_judge', args=[judge.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(Judge.objects.filter(id=judge.id).exists())

    def test_delete_missing_judge_returns_not_found(self):
        response = self.client.delete(reverse('delete_judge', args=[999999]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unassigned_user_cannot_delete_judge(self):
        judge = Judge.objects.create(
            first_name="Protected",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
        )
        MapContestToJudge.objects.create(contestid=self.contest.id, judgeid=judge.id)
        unassigned_user = User.objects.create_user(
            username="unassigned@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unassigned_user)

        response = self.client.delete(reverse('delete_judge', args=[judge.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Judge.objects.filter(id=judge.id).exists())

    def test_are_all_score_sheets_submitted(self):
        """Test checking if all score sheets are submitted for judges"""
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            mdo=False,
            journal=True
        )
        url = reverse('are_all_score_sheets_submitted')
        # Endpoint expects a list of judge objects
        data = [{"id": judge.id}]
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, {judge.id: False})

    def test_score_sheet_status_rejects_malformed_judge_list(self):
        response = self.client.post(
            reverse('are_all_score_sheets_submitted'),
            ["not-a-judge"],
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unrelated_user_cannot_read_judge_submission_status(self):
        judge = Judge.objects.create(
            first_name="Private", last_name="Judge", phone_number="5551112222",
            contestid=self.contest.id,
        )
        MapContestToJudge.objects.create(
            contestid=self.contest.id, judgeid=judge.id
        )
        unrelated_user = User.objects.create_user(
            username="unrelated-status@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unrelated_user)

        response = self.client.post(
            reverse('are_all_score_sheets_submitted'),
            [{"id": judge.id}],
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_judge_disqualify_team(self):
        """Test judge disqualifying a team"""
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            mdo=False,
            journal=True
        )
        from ..models import Teams
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
        url = reverse('judge_disqualify_team')
        data = {"teamid": team.id, "judge_disqualified": True}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        team.refresh_from_db()
        self.assertTrue(team.judge_disqualified)

    def test_unassigned_user_cannot_disqualify_team(self):
        team = Teams.objects.create(team_name="Protected Team")
        unassigned_user = User.objects.create_user(
            username="unassigned-disqualify@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unassigned_user)

        response = self.client.post(
            reverse('judge_disqualify_team'),
            {"teamid": team.id, "judge_disqualified": True}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        team.refresh_from_db()
        self.assertFalse(team.judge_disqualified)

    def test_judge_cannot_disqualify_team_shared_with_unassigned_contest(self):
        from datetime import date
        other_contest = Contest.objects.create(
            name="Other Shared Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        team = Teams.objects.create(team_name="Shared Protected Team")
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        MapContestToTeam.objects.create(contestid=other_contest.id, teamid=team.id)
        judge = Judge.objects.create(
            first_name="Single", last_name="Contest", phone_number="5552223333",
            contestid=self.contest.id, presentation=True,
        )
        judge_user = User.objects.create_user(
            username="single-contest-judge@example.com", password="password"
        )
        MapUserToRole.objects.create(uuid=judge_user.id, role=3, relatedid=judge.id)
        MapContestToJudge.objects.create(contestid=self.contest.id, judgeid=judge.id)
        sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id, judgeid=judge.id, scoresheetid=sheet.id,
            sheetType=ScoresheetEnum.PRESENTATION,
        )
        self.client.force_authenticate(user=judge_user)

        response = self.client.post(
            reverse('judge_disqualify_team'),
            {"teamid": team.id, "judge_disqualified": True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        team.refresh_from_db()
        self.assertFalse(team.judge_disqualified)

    def test_judge_disqualification_parses_false_form_value(self):
        team = Teams.objects.create(team_name="Form Boolean Team", judge_disqualified=True)
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        judge = Judge.objects.create(
            first_name="Form", last_name="Judge", phone_number="5554445555",
            contestid=self.contest.id, presentation=True,
        )
        judge_user = User.objects.create_user(
            username="form-judge@example.com", password="password"
        )
        MapUserToRole.objects.create(uuid=judge_user.id, role=3, relatedid=judge.id)
        MapContestToJudge.objects.create(contestid=self.contest.id, judgeid=judge.id)
        sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id, judgeid=judge.id, scoresheetid=sheet.id,
            sheetType=ScoresheetEnum.PRESENTATION,
        )
        self.client.force_authenticate(user=judge_user)

        response = self.client.post(
            reverse('judge_disqualify_team'),
            {"teamid": team.id, "judge_disqualified": "false"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        team.refresh_from_db()
        self.assertFalse(team.judge_disqualified)

    def test_judge_finalizes_team_when_organizer_disqualified_first(self):
        team = Teams.objects.create(
            team_name="Organizer First Team",
            organizer_disqualified=True,
            team_rank=3,
            cluster_rank=2,
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        judge = Judge.objects.create(
            first_name="Final", last_name="Judge", phone_number="5552223333",
            contestid=self.contest.id, presentation=True,
        )
        MapContestToJudge.objects.create(
            contestid=self.contest.id, judgeid=judge.id
        )
        judge_user = User.objects.create_user(
            username="final-judge@example.com", password="testpassword"
        )
        MapUserToRole.objects.create(
            uuid=judge_user.id,
            role=MapUserToRole.RoleEnum.JUDGE,
            relatedid=judge.id,
        )
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id, judgeid=judge.id, scoresheetid=scoresheet.id,
            sheetType=ScoresheetEnum.PRESENTATION,
        )
        self.client.force_authenticate(user=judge_user)

        response = self.client.post(
            reverse('judge_disqualify_team'),
            {"teamid": team.id, "judge_disqualified": True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        team.refresh_from_db()
        scoresheet.refresh_from_db()
        self.assertTrue(team.judge_disqualified)
        self.assertIsNone(team.team_rank)
        self.assertIsNone(team.cluster_rank)
        self.assertTrue(scoresheet.isSubmitted)
