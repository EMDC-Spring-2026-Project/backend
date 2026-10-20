from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from unittest.mock import patch
from ..models import (
    Scoresheet, ScoresheetEnum, Teams, Judge, MapScoresheetToTeamJudge,
    Admin, MapUserToRole, MapContestToJudge, JudgeClusters, MapJudgeToCluster,
    MapContestToCluster, MapContestToTeam,
)
from ..serializers import ScoresheetSerializer


class ScoresheetAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an admin user for role mapping
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

        # Create a team
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

        # Create a judge
        from datetime import date
        from ..models import Contest
        self.contest = Contest.objects.create(
            name="Test Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        self.judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            mdo=False,
            journal=True
        )

    def test_scores_by_id(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            field1=1.0,
            field2=2.0,
            field3=3.0,
            field4=4.0,
            field5=5.0,
            field6=6.0,
            field7=7.0,
            field8=8.0
        )
        url = reverse('scores_by_id', args=[scoresheet.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['ScoreSheet']['sheetType'], ScoresheetEnum.PRESENTATION)

    def test_scores_by_id_requires_sign_in(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )
        self.client.logout()

        response = self.client.get(reverse('scores_by_id', args=[scoresheet.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_score_sheet(self):
        url = reverse('create_score_sheets')
        data = {
            "sheetType": ScoresheetEnum.PRESENTATION,
            "isSubmitted": False,
            "field1": 1.0,
            "field2": 2.0,
            "field3": 3.0,
            "field4": 4.0,
            "field5": 5.0,
            "field6": 6.0,
            "field7": 7.0,
            "field8": 8.0,
            "teamid": self.team.id,
            "judgeid": self.judge.id
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_non_admin_cannot_create_score_sheet_directly(self):
        ordinary_user = User.objects.create_user(
            username="ordinary@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=ordinary_user)

        response = self.client.post(
            reverse('create_score_sheets'),
            {"sheetType": ScoresheetEnum.PRESENTATION, "isSubmitted": False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_make_sheets_for_team_handles_empty_cluster(self):
        from ..views.scoresheets import make_sheets_for_team
        cluster = JudgeClusters.objects.create(
            cluster_name="Empty Cluster", cluster_type="preliminary"
        )

        created = make_sheets_for_team(self.team.id, cluster.id)

        self.assertEqual(created, [])
        self.assertFalse(
            MapScoresheetToTeamJudge.objects.filter(teamid=self.team.id).exists()
        )

    def test_make_sheets_for_team_creates_each_judges_enabled_types_once(self):
        from ..views.scoresheets import make_sheets_for_team
        cluster = JudgeClusters.objects.create(
            cluster_name="Mixed Roles", cluster_type="preliminary"
        )
        MapJudgeToCluster.objects.create(clusterid=cluster.id, judgeid=self.judge.id)
        second_judge = Judge.objects.create(
            first_name="Second", last_name="Judge", phone_number="5551112222",
            contestid=self.contest.id, presentation=False, journal=False, mdo=False,
            runpenalties=False, otherpenalties=True, redesign=True, championship=True,
        )
        MapJudgeToCluster.objects.create(clusterid=cluster.id, judgeid=second_judge.id)

        created = make_sheets_for_team(self.team.id, cluster.id)

        created_pairs = [(entry["judge_id"], entry["sheetType"]) for entry in created]
        self.assertCountEqual(
            created_pairs,
            [
                (self.judge.id, ScoresheetEnum.PRESENTATION),
                (self.judge.id, ScoresheetEnum.JOURNAL),
                (second_judge.id, ScoresheetEnum.OTHERPENALTIES),
                (second_judge.id, ScoresheetEnum.REDESIGN),
                (second_judge.id, ScoresheetEnum.CHAMPIONSHIP),
            ],
        )
        self.assertEqual(len(created_pairs), len(set(created_pairs)))

    def test_cluster_scoresheet_generation_rejects_missing_cluster(self):
        from rest_framework.exceptions import ValidationError
        from ..views.scoresheets import create_scoresheets_for_judges_in_cluster

        with self.assertRaises(ValidationError):
            create_scoresheets_for_judges_in_cluster(999999)

    @patch(
        "emdcbackend.views.scoresheets.create_sheets_for_teams_in_cluster",
        side_effect=RuntimeError("generation failed"),
    )
    def test_cluster_scoresheet_generation_propagates_failures(self, _mock_create):
        from rest_framework.exceptions import ValidationError
        from ..models import MapClusterToTeam
        from ..views.scoresheets import create_scoresheets_for_judges_in_cluster

        cluster = JudgeClusters.objects.create(
            cluster_name="Generation Cluster", cluster_type="preliminary"
        )
        MapJudgeToCluster.objects.create(judgeid=self.judge.id, clusterid=cluster.id)
        MapClusterToTeam.objects.create(clusterid=cluster.id, teamid=self.team.id)

        with self.assertRaises(ValidationError):
            create_scoresheets_for_judges_in_cluster(cluster.id)

    def test_bulk_sheet_creation_does_not_assign_all_contest_teams_to_empty_cluster(self):
        from ..views.scoresheets import create_sheets_for_teams_in_cluster
        cluster = JudgeClusters.objects.create(
            cluster_name="Unassigned Cluster", cluster_type="preliminary"
        )
        MapContestToCluster.objects.create(
            contestid=self.contest.id, clusterid=cluster.id
        )
        MapContestToTeam.objects.create(
            contestid=self.contest.id, teamid=self.team.id
        )

        created = create_sheets_for_teams_in_cluster(
            self.judge.id,
            cluster.id,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
        )

        self.assertEqual(created, [])
        self.assertFalse(
            MapScoresheetToTeamJudge.objects.filter(
                teamid=self.team.id, judgeid=self.judge.id
            ).exists()
        )

    def test_edit_score_sheet(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            field1=1.0,
            field2=2.0,
            field3=3.0,
            field4=4.0,
            field5=5.0,
            field6=6.0,
            field7=7.0,
            field8=8.0
        )
        url = reverse('edit_score_sheets')
        data = {
            "id": scoresheet.id,
            "sheetType": ScoresheetEnum.PRESENTATION,
            "isSubmitted": True,
            "field1": 10.0,
            "field2": 20.0,
            "field3": 30.0,
            "field4": 40.0,
            "field5": 50.0,
            "field6": 60.0,
            "field7": 70.0,
            "field8": 80.0
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        scoresheet.refresh_from_db()
        self.assertTrue(scoresheet.isSubmitted)
        self.assertEqual(scoresheet.field1, 10.0)
        self.assertEqual(scoresheet.field8, 80.0)

    def test_submit_score_sheet_preserves_omitted_fields(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            **{f"field{number}": float(number) for number in range(1, 9)},
        )

        response = self.client.post(
            reverse('edit_score_sheets'),
            {
                "id": scoresheet.id,
                "sheetType": ScoresheetEnum.PRESENTATION,
                "isSubmitted": True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        scoresheet.refresh_from_db()
        self.assertTrue(scoresheet.isSubmitted)
        self.assertEqual(scoresheet.field1, 1.0)
        self.assertEqual(scoresheet.field8, 8.0)

    def test_edit_score_sheet_returns_not_found_for_missing_sheet(self):
        response = self.client.post(
            reverse('edit_score_sheets'),
            {"id": 999999, "isSubmitted": False},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_edit_score_sheet_rejects_ambiguous_submission_value(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )

        response = self.client.post(
            reverse('edit_score_sheets'),
            {"id": scoresheet.id, "isSubmitted": "yes"},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        scoresheet.refresh_from_db()
        self.assertFalse(scoresheet.isSubmitted)

    def test_delete_score_sheet(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            field1=1.0,
            field2=2.0,
            field3=3.0,
            field4=4.0,
            field5=5.0,
            field6=6.0,
            field7=7.0,
            field8=8.0
        )
        url = reverse('delete_score_sheets', args=[scoresheet.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Scoresheet.objects.filter(id=scoresheet.id).exists())

    def test_edit_score_sheet_field(self):
        """Test editing a single field in a scoresheet"""
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            field1=1.0,
            field2=2.0,
            field3=3.0,
            field4=4.0,
            field5=5.0,
            field6=6.0,
            field7=7.0,
            field8=8.0
        )
        url = reverse('edit_score_sheet_field')
        data = {
            "id": scoresheet.id,
            "field": 1,  # field number or field name
            "new_value": 99.0
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        scoresheet.refresh_from_db()
        self.assertEqual(scoresheet.field1, 99.0)

    def test_edit_score_sheet_field_rejects_non_score_attributes(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )

        response = self.client.post(
            reverse('edit_score_sheet_field'),
            {"id": scoresheet.id, "field": "sheetType", "new_value": ScoresheetEnum.CHAMPIONSHIP},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        scoresheet.refresh_from_db()
        self.assertEqual(scoresheet.sheetType, ScoresheetEnum.PRESENTATION)

    def test_edit_score_sheet_field_returns_validation_error_for_incomplete_submission(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )

        response = self.client.post(
            reverse('edit_score_sheet_field'),
            {"id": scoresheet.id, "field": "isSubmitted", "new_value": True},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_edit_score_sheet_field_parses_false_string_as_false(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=True,
            **{f"field{number}": float(number) for number in range(1, 9)},
        )

        response = self.client.post(
            reverse('edit_score_sheet_field'),
            {"id": scoresheet.id, "field": "isSubmitted", "new_value": "false"},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        scoresheet.refresh_from_db()
        self.assertFalse(scoresheet.isSubmitted)

    def test_update_scores(self):
        """Test updating multiple scores in a scoresheet"""
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            field1=1.0,
            field2=2.0,
            field3=3.0,
            field4=4.0,
            field5=5.0,
            field6=6.0,
            field7=7.0,
            field8=8.0
        )
        url = reverse('update_scores')
        data = {
            "id": scoresheet.id,
            "field1": 10.0,
            "field2": 20.0,
            "field3": 30.0,
            "isSubmitted": True
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        scoresheet.refresh_from_db()
        self.assertTrue(scoresheet.isSubmitted)
        self.assertEqual(scoresheet.field1, 10.0)
        self.assertEqual(scoresheet.field3, 30.0)

    def test_update_scores_preserves_omitted_fields(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.CHAMPIONSHIP,
            isSubmitted=False,
            field1=10.0,
            field2=20.0,
            field19=30.0,
            field26=40.0,
        )

        response = self.client.post(
            reverse('update_scores'),
            {"id": scoresheet.id, "field19": 35.0},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        scoresheet.refresh_from_db()
        self.assertEqual(scoresheet.field1, 10.0)
        self.assertEqual(scoresheet.field2, 20.0)
        self.assertEqual(scoresheet.field19, 35.0)
        self.assertEqual(scoresheet.field26, 40.0)

    def test_update_scores_returns_not_found_for_missing_sheet(self):
        response = self.client.post(
            reverse('update_scores'),
            {"id": 999999, "field1": 10.0},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_scores_rejects_non_boolean_submission_value(self):
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )

        response = self.client.post(
            reverse('update_scores'),
            {"id": scoresheet.id, "isSubmitted": 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        scoresheet.refresh_from_db()
        self.assertFalse(scoresheet.isSubmitted)

    def test_unrelated_user_cannot_view_multi_team_penalty_scores(self):
        unrelated_user = User.objects.create_user(
            username="unrelated-penalties@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unrelated_user)

        response = self.client.get(reverse(
            'multi_team_run_penalties', args=[self.judge.id, self.contest.id]
        ))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_assigned_judge_can_view_multi_team_penalty_scores(self):
        judge_user = User.objects.create_user(
            username="penalty-viewer@example.com", password="testpassword"
        )
        MapUserToRole.objects.create(
            uuid=judge_user.id,
            role=MapUserToRole.RoleEnum.JUDGE,
            relatedid=self.judge.id,
        )
        MapContestToJudge.objects.create(
            contestid=self.contest.id, judgeid=self.judge.id
        )
        self.client.force_authenticate(user=judge_user)

        response = self.client.get(reverse(
            'multi_team_run_penalties', args=[self.judge.id, self.contest.id]
        ))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unassigned_judge_cannot_edit_scoresheet(self):
        """A judge may only edit scoresheets assigned to that judge."""
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False, field1=10.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=self.judge.id,
            scoresheetid=scoresheet.id,
            sheetType=ScoresheetEnum.PRESENTATION,
        )
        other_user = User.objects.create_user(
            username="other-judge@example.com", password="testpassword"
        )
        other_judge = Judge.objects.create(
            first_name="Other",
            last_name="Judge",
            phone_number="0987654321",
            contestid=self.contest.id,
        )
        MapUserToRole.objects.create(
            uuid=other_user.id,
            role=MapUserToRole.RoleEnum.JUDGE,
            relatedid=other_judge.id,
        )
        self.client.force_authenticate(user=other_user)

        response = self.client.post(
            reverse('update_scores'),
            {"id": scoresheet.id, "field1": 99.0},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        scoresheet.refresh_from_db()
        self.assertEqual(scoresheet.field1, 10.0)

    def test_get_scoresheet_details_by_team(self):
        """Test getting scoresheet details for a team"""
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            field1=1.0,
            field2=2.0,
            field3=3.0,
            field4=4.0,
            field5=5.0,
            field6=6.0,
            field7=7.0,
            field8=8.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=self.judge.id,
            scoresheetid=scoresheet.id,
            sheetType=ScoresheetEnum.PRESENTATION
        )
        url = reverse('get_score_sheets_by_team_id', args=[self.team.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsInstance(response.data, dict)

    def test_unrelated_user_cannot_view_team_score_breakdown(self):
        unrelated_user = User.objects.create_user(
            username="unrelated-breakdown@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unrelated_user)

        response = self.client.get(
            reverse('get_score_sheets_by_team_id', args=[self.team.id])
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_scoresheet_details_for_contest(self):
        """Test getting scoresheet details for a contest"""
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,
            field1=1.0,
            field2=2.0,
            field3=3.0,
            field4=4.0,
            field5=5.0,
            field6=6.0,
            field7=7.0,
            field8=8.0
        )
        from ..models import MapContestToTeam
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=self.team.id)
        cluster = JudgeClusters.objects.create(
            cluster_name="Contest Score Cluster", cluster_type="preliminary"
        )
        MapContestToCluster.objects.create(
            contestid=self.contest.id, clusterid=cluster.id
        )
        MapJudgeToCluster.objects.create(
            judgeid=self.judge.id, clusterid=cluster.id
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=self.judge.id,
            scoresheetid=scoresheet.id,
            sheetType=ScoresheetEnum.PRESENTATION
        )
        url = reverse('get_scoresheet_details_for_contest')
        response = self.client.get(url, data={"contestid": self.contest.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn(self.team.id, response.data["teams"])
        self.assertEqual(
            response.data["teams"][self.team.id][str(ScoresheetEnum.PRESENTATION)]["1"],
            [1.0],
        )
