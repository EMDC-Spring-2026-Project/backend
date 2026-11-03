from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from datetime import date
from unittest.mock import patch
from ..models import (
    Contest, Teams, Judge, JudgeClusters, MapContestToTeam, MapContestToOrganizer,
    MapUserToRole, Organizer, Admin, MapClusterToTeam, MapJudgeToCluster,
    Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, MapContestToCluster,
    MapContestToJudge,
)


class TabulationAPITests(APITestCase):
    def test_redesign_total_includes_communication(self):
        self.cluster.cluster_type = "redesign"
        self.cluster.save()
        judge = Judge.objects.create(first_name="Redesign", last_name="Judge", contestid=self.contest.id)
        MapJudgeToCluster.objects.create(judgeid=judge.id, clusterid=self.cluster.id, redesign=True)
        sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.REDESIGN, isSubmitted=True,
            field1=1, field2=2, field3=3, field4=4, field5=5, field6=6, field7=7,
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id, judgeid=judge.id, scoresheetid=sheet.id,
            sheetType=ScoresheetEnum.REDESIGN,
        )
        response = self.client.put(reverse("tabulate_scores"), {"contestid": self.contest.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.team.refresh_from_db()
        self.assertEqual(self.team.redesign_score, 28)

    def test_redesign_averages_submitted_judges(self):
        self.cluster.cluster_type = "redesign"
        self.cluster.save()
        for index, multiplier in enumerate((1, 2), start=1):
            judge = Judge.objects.create(
                first_name=f"Redesign {index}", last_name="Judge",
                contestid=self.contest.id,
            )
            MapJudgeToCluster.objects.create(
                judgeid=judge.id, clusterid=self.cluster.id,
                contestid=self.contest.id, redesign=True,
            )
            sheet = Scoresheet.objects.create(
                sheetType=ScoresheetEnum.REDESIGN, isSubmitted=True,
                **{f"field{number}": number * multiplier for number in range(1, 8)},
            )
            MapScoresheetToTeamJudge.objects.create(
                teamid=self.team.id, judgeid=judge.id, scoresheetid=sheet.id,
                sheetType=ScoresheetEnum.REDESIGN,
            )

        response = self.client.put(
            reverse("tabulate_scores"), {"contestid": self.contest.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertEqual(self.team.redesign_score, 42)

    def test_penalties_are_averaged_across_judging_groups(self):
        for index, penalty in enumerate((10, 20), start=1):
            judge = Judge.objects.create(
                first_name=f"Penalty {index}", last_name="Judge",
                contestid=self.contest.id,
            )
            MapJudgeToCluster.objects.create(
                judgeid=judge.id, clusterid=self.cluster.id,
                contestid=self.contest.id, runpenalties=True, otherpenalties=True,
            )
            run_sheet = Scoresheet.objects.create(
                sheetType=ScoresheetEnum.RUNPENALTIES, isSubmitted=True,
                **{
                    f"field{number}": penalty if number == 1 else 0
                    for number in (*range(1, 9), *range(10, 18))
                },
            )
            other_sheet = Scoresheet.objects.create(
                sheetType=ScoresheetEnum.OTHERPENALTIES, isSubmitted=True,
                **{f"field{number}": index for number in range(1, 8)},
            )
            for sheet in (run_sheet, other_sheet):
                MapScoresheetToTeamJudge.objects.create(
                    teamid=self.team.id, judgeid=judge.id, scoresheetid=sheet.id,
                    sheetType=sheet.sheetType,
                )

        response = self.client.put(
            reverse("tabulate_scores"), {"contestid": self.contest.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertEqual(self.team.penalties_score, 15)
        self.assertEqual(self.team.preliminary_penalties_score, 10.5)
        self.assertEqual(self.team.total_score, -25.5)

    def test_standard_ties_use_machine_then_presentation_then_journal(self):
        from ..views.tabulation import sort_by_standard_round_tiebreakers

        lower_machine = Teams.objects.create(
            team_name="Lower Machine", preliminary_total_score=100,
            preliminary_machinedesign_score=30,
            preliminary_presentation_score=40, preliminary_journal_score=30,
        )
        higher_machine = Teams.objects.create(
            team_name="Higher Machine", preliminary_total_score=100,
            preliminary_machinedesign_score=35,
            preliminary_presentation_score=30, preliminary_journal_score=35,
        )

        ordered = sort_by_standard_round_tiebreakers(
            [lower_machine, higher_machine]
        )
        self.assertEqual(
            [team.id for team in ordered], [higher_machine.id, lower_machine.id]
        )

    def test_redesign_ties_use_first_then_second_category(self):
        from ..views.tabulation import sort_by_redesign_tiebreakers

        self.cluster.cluster_type = "redesign"
        self.cluster.save()
        other_team = Teams.objects.create(team_name="Other Redesign Team", redesign_score=20)
        self.team.redesign_score = 20
        self.team.save()
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=other_team.id)
        MapClusterToTeam.objects.create(clusterid=self.cluster.id, teamid=other_team.id)
        judge = Judge.objects.create(
            first_name="Tie", last_name="Judge", contestid=self.contest.id
        )
        MapJudgeToCluster.objects.create(
            judgeid=judge.id, clusterid=self.cluster.id,
            contestid=self.contest.id, redesign=True,
        )
        for team, first, second in (
            (self.team, 10, 10),
            (other_team, 12, 8),
        ):
            sheet = Scoresheet.objects.create(
                sheetType=ScoresheetEnum.REDESIGN, isSubmitted=True,
                field1=first, field2=second, field3=0, field4=0,
                field5=0, field6=0, field7=0,
            )
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=sheet.id,
                sheetType=ScoresheetEnum.REDESIGN,
            )

        ordered = sort_by_redesign_tiebreakers(
            [self.team, other_team], self.contest.id
        )
        self.assertEqual([team.id for team in ordered], [other_team.id, self.team.id])

    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an organizer user for role mapping (tabulation requires organizer)
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
            championship_score=0.0
        )
        self.cluster = JudgeClusters.objects.create(
            cluster_name="Test Cluster",
            cluster_type="preliminary"
        )
        
        # Map contest to organizer and team
        MapContestToOrganizer.objects.create(contestid=self.contest.id, organizerid=self.organizer.id)
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=self.team.id)
        MapClusterToTeam.objects.create(clusterid=self.cluster.id, teamid=self.team.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.cluster.id)

    def test_tabulate_scores(self):
        url = reverse('tabulate_scores')
        data = {
            "contestid": self.contest.id
        }
        # Use PUT method (as per view decorator)
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    @patch("emdcbackend.views.tabulation.recompute_totals_and_ranks")
    def test_tabulation_rolls_back_partial_updates_when_recalculation_fails(self, recompute):
        self.team.total_score = 255.0
        self.team.save()

        def partially_update_then_fail(contest_id):
            Teams.objects.filter(id=self.team.id).update(total_score=1.0)
            raise RuntimeError("database detail must not be returned")

        recompute.side_effect = partially_update_then_fail
        response = self.client.put(
            reverse("tabulate_scores"),
            {"contestid": self.contest.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.team.refresh_from_db()
        self.assertEqual(self.team.total_score, 255.0)
        self.assertNotIn("database detail", response.data["detail"])

    def test_tabulation_ignores_scores_from_judge_not_assigned_to_contest(self):
        other_contest = Contest.objects.create(
            name="Other Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        other_judge = Judge.objects.create(
            first_name="Other", last_name="Judge", phone_number="5553334444",
            contestid=other_contest.id, presentation=True,
        )
        MapContestToJudge.objects.create(
            contestid=other_contest.id, judgeid=other_judge.id
        )
        sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=True,
            **{f"field{number}": 1 for number in range(1, 9)},
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=other_judge.id,
            scoresheetid=sheet.id,
            sheetType=ScoresheetEnum.PRESENTATION,
        )

        response = self.client.put(
            reverse('tabulate_scores'),
            {"contestid": self.contest.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertEqual(self.team.presentation_score, 0)
        self.assertEqual(self.team.total_score, 0)

    def test_tabulation_does_not_use_other_contests_judge_in_shared_cluster(self):
        other_contest = Contest.objects.create(
            name="Other Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        MapContestToCluster.objects.create(
            contestid=other_contest.id, clusterid=self.cluster.id
        )
        MapContestToTeam.objects.create(
            contestid=other_contest.id, teamid=self.team.id
        )
        other_judge = Judge.objects.create(
            first_name="Other", last_name="Judge", phone_number="5553334444",
            contestid=other_contest.id, presentation=True,
        )
        MapContestToJudge.objects.create(
            contestid=other_contest.id, judgeid=other_judge.id
        )
        MapJudgeToCluster.objects.create(
            judgeid=other_judge.id,
            clusterid=self.cluster.id,
            contestid=other_contest.id,
            presentation=True,
        )
        sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=True,
            **{f"field{number}": 1 for number in range(1, 9)},
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=other_judge.id,
            scoresheetid=sheet.id,
            sheetType=ScoresheetEnum.PRESENTATION,
        )

        response = self.client.put(
            reverse("tabulate_scores"),
            {"contestid": self.contest.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertEqual(self.team.presentation_score, 0)
        self.assertEqual(self.team.total_score, 0)

    def test_preliminary_results(self):
        url = reverse('preliminary_results')
        data = {
            "contestid": self.contest.id
        }
        # Use PUT method (as per view decorator)
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return teams with preliminary results
        self.assertIn('data', response.data or {})

    def test_scoring_actions_reject_unassigned_organizer(self):
        """A signed-in organizer cannot access another organizer's contest."""
        other_user = User.objects.create_user(
            username="other-organizer@example.com", password="testpassword"
        )
        other_organizer = Organizer.objects.create(
            first_name="Other", last_name="Organizer"
        )
        MapUserToRole.objects.create(
            uuid=other_user.id,
            role=MapUserToRole.RoleEnum.ORGANIZER,
            relatedid=other_organizer.id,
        )
        self.client.force_authenticate(user=other_user)

        for endpoint in ('tabulate_scores', 'preliminary_results'):
            with self.subTest(endpoint=endpoint):
                response = self.client.put(
                    reverse(endpoint), {"contestid": self.contest.id}, format='json'
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        for endpoint in ('championship_results', 'redesign_results'):
            with self.subTest(endpoint=endpoint):
                response = self.client.put(
                    f"{reverse(endpoint)}?contestid={self.contest.id}", {}, format='json'
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_preliminary_results_excludes_internal_all_teams_cluster(self):
        """Standings should list a team only in its real scoring cluster."""
        internal_cluster = JudgeClusters.objects.create(
            cluster_name="All Teams",
            cluster_type="preliminary",
        )
        MapContestToCluster.objects.create(
            contestid=self.contest.id, clusterid=internal_cluster.id
        )
        MapClusterToTeam.objects.create(
            clusterid=internal_cluster.id, teamid=self.team.id
        )

        response = self.client.put(
            reverse('preliminary_results'),
            {"contestid": self.contest.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["cluster_id"], self.cluster.id)

    def test_preliminary_results_excludes_other_contests_teams_in_shared_cluster(self):
        other_contest = Contest.objects.create(
            name="Other Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        other_team = Teams.objects.create(
            team_name="Other Contest Team", total_score=999.0
        )
        MapContestToCluster.objects.create(
            contestid=other_contest.id, clusterid=self.cluster.id
        )
        MapContestToTeam.objects.create(
            contestid=other_contest.id, teamid=other_team.id
        )
        MapClusterToTeam.objects.create(
            clusterid=self.cluster.id, teamid=other_team.id
        )

        response = self.client.put(
            reverse("preliminary_results"),
            {"contestid": self.contest.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        cluster_results = next(
            item for item in response.data["data"]
            if item["cluster_id"] == self.cluster.id
        )
        self.assertEqual(
            [team["team_id"] for team in cluster_results["teams"]],
            [self.team.id],
        )

    def test_championship_results(self):
        url = reverse('championship_results')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.put(url_with_params, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_redesign_results(self):
        url = reverse('redesign_results')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.put(url_with_params, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_set_advancers(self):
        url = reverse('set_advancers')
        data = {
            "contestid": self.contest.id,
            "team_ids": [self.team.id]
        }
        # Use PUT method (as per view decorator)
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_rejected_disqualified_advancer_keeps_existing_selection(self):
        self.team.advanced_to_championship = True
        self.team.championship_rank = 1
        self.team.save(update_fields=["advanced_to_championship", "championship_rank"])
        disqualified_team = Teams.objects.create(
            team_name="Disqualified Team", judge_disqualified=True
        )
        MapContestToTeam.objects.create(
            contestid=self.contest.id, teamid=disqualified_team.id
        )

        response = self.client.put(
            reverse("set_advancers"),
            {"contestid": self.contest.id, "team_ids": [disqualified_team.id]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.team.refresh_from_db()
        self.assertTrue(self.team.advanced_to_championship)
        self.assertEqual(self.team.championship_rank, 1)

    def test_list_advancers(self):
        # Set a team as advanced
        self.team.advanced_to_championship = True
        self.team.save()
        
        url = reverse('list_advancers')
        # Use GET method (as per view decorator)
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.get(url_with_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return list of advanced teams
        self.assertIn('advanced', response.data or {})
        self.assertIn('advanced_count', response.data or {})
        self.assertEqual(response.data['advanced_count'], 1)

    # Edge case tests
    def test_tabulate_scores_missing_contestid(self):
        """Test tabulate_scores with missing contestid"""
        url = reverse('tabulate_scores')
        response = self.client.put(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('contestid', str(response.data).lower() or '')

    def test_preliminary_results_missing_contestid(self):
        """Test preliminary_results with missing contestid"""
        url = reverse('preliminary_results')
        response = self.client.put(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_championship_results_missing_contestid(self):
        """Test championship_results with missing contestid"""
        url = reverse('championship_results')
        response = self.client.put(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_redesign_results_missing_contestid(self):
        """Test redesign_results with missing contestid"""
        url = reverse('redesign_results')
        response = self.client.put(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_advancers_missing_contestid(self):
        """Test set_advancers with missing contestid"""
        url = reverse('set_advancers')
        data = {"team_ids": [self.team.id]}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_advancers_missing_team_ids(self):
        """Test set_advancers with missing team_ids"""
        url = reverse('set_advancers')
        data = {"contestid": self.contest.id}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_advancers_invalid_team_ids_type(self):
        """Test set_advancers with invalid team_ids type (not a list)"""
        url = reverse('set_advancers')
        data = {"contestid": self.contest.id, "team_ids": "not_a_list"}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_advancers_empty_team_ids(self):
        """Test set_advancers with empty team_ids list"""
        url = reverse('set_advancers')
        data = {"contestid": self.contest.id, "team_ids": []}
        response = self.client.put(url, data, format='json')
        # Should succeed but no teams advanced
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('advanced_count', 0), 0)

    def test_list_advancers_missing_contestid(self):
        """Test list_advancers with missing contestid"""
        url = reverse('list_advancers')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_advancers_invalid_contestid(self):
        """Test list_advancers with invalid contestid"""
        url = reverse('list_advancers')
        url_with_params = f"{url}?contestid=invalid"
        response = self.client.get(url_with_params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_championship_results_no_advanced_teams(self):
        """Test championship_results when no teams are advanced"""
        url = reverse('championship_results')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.put(url_with_params, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data or {})
        self.assertEqual(len(response.data.get('data', [])), 0)

    def test_redesign_results_no_redesign_teams(self):
        """Test redesign_results when no redesign teams exist"""
        url = reverse('redesign_results')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.put(url_with_params, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data or {})

    def test_set_advancers_permission_denied(self):
        """Test set_advancers when user is not an organizer of the contest"""
        # Create a new user without organizer role and login
        other_user = User.objects.create_user(username="otheruser@example.com", password="testpassword")
        self.client.logout()  # Logout current user
        self.client.login(username="otheruser@example.com", password="testpassword")
        
        url = reverse('set_advancers')
        data = {"contestid": self.contest.id, "team_ids": [self.team.id]}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_set_advancers_with_invalid_team_ids(self):
        """Test set_advancers with team_ids that don't belong to contest"""
        url = reverse('set_advancers')
        # Create a team not in the contest (with required fields)
        other_team = Teams.objects.create(
            team_name="Other Team",
            journal_score=0.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0
        )
        data = {"contestid": self.contest.id, "team_ids": [other_team.id, self.team.id]}
        response = self.client.put(url, data, format='json')
        # Should succeed but only advance the valid team
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('advanced_count', 0), 1)

    def test_preliminary_results_with_clusters(self):
        """Test preliminary_results returns correct cluster structure"""
        from ..models import MapContestToCluster
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.cluster.id)
        
        url = reverse('preliminary_results')
        data = {"contestid": self.contest.id}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data or {})
        if response.data.get('data'):
            cluster_data = response.data['data'][0]
            self.assertIn('cluster_id', cluster_data)
            self.assertIn('teams', cluster_data)

    def test_championship_results_with_advanced_team(self):
        """Test championship_results with an advanced team"""
        self.team.advanced_to_championship = True
        self.team.save()
        
        url = reverse('championship_results')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.put(url_with_params, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data or {})
        if response.data.get('data'):
            team_data = response.data['data'][0]
            self.assertIn('team_name', team_data)
            self.assertIn('total_score', team_data)
            self.assertTrue(team_data.get('is_championship', False))

    def test_redesign_results_with_redesign_team(self):
        """Test redesign_results with a redesign team"""
        # Create a redesign cluster and map team to it
        redesign_cluster = JudgeClusters.objects.create(
            cluster_name="Redesign Cluster",
            cluster_type="redesign"
        )
        from ..models import MapContestToCluster
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=redesign_cluster.id)
        MapClusterToTeam.objects.create(clusterid=redesign_cluster.id, teamid=self.team.id)
        self.team.redesign_score = 100.0
        self.team.save()
        
        url = reverse('redesign_results')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.put(url_with_params, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data or {})

    def test_redesign_results_excludes_preliminary_only_teams(self):
        """Redesign standings must not include teams outside the redesign round."""
        redesign_cluster = JudgeClusters.objects.create(
            cluster_name="Redesign Cluster", cluster_type="redesign"
        )
        MapContestToCluster.objects.create(
            contestid=self.contest.id, clusterid=redesign_cluster.id
        )
        MapClusterToTeam.objects.create(
            clusterid=redesign_cluster.id, teamid=self.team.id
        )
        preliminary_only_team = Teams.objects.create(
            team_name="Preliminary Only Team", redesign_score=0.0, total_score=250.0
        )
        MapContestToTeam.objects.create(
            contestid=self.contest.id, teamid=preliminary_only_team.id
        )
        MapClusterToTeam.objects.create(
            clusterid=self.cluster.id, teamid=preliminary_only_team.id
        )

        response = self.client.put(
            f"{reverse('redesign_results')}?contestid={self.contest.id}", {}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([team["id"] for team in response.data["data"]], [self.team.id])

    def test_list_advancers_no_advanced_teams(self):
        """Test list_advancers when no teams are advanced"""
        url = reverse('list_advancers')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.get(url_with_params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('advanced_count', 0), 0)
        self.assertEqual(len(response.data.get('advanced', [])), 0)

    # Additional edge case tests
    def test_tabulate_scores_with_no_teams(self):
        """Test tabulating scores when contest has no teams"""
        # Create a contest with no teams
        empty_contest = Contest.objects.create(
            name="Empty Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        MapContestToOrganizer.objects.create(contestid=empty_contest.id, organizerid=self.organizer.id)
        
        url = reverse('tabulate_scores')
        data = {"contestid": empty_contest.id}
        response = self.client.put(url, data, format='json')
        # Should succeed even with no teams
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_preliminary_results_with_tied_scores(self):
        """Test preliminary results with teams having tied scores"""
        from ..models import MapContestToCluster
        # Create teams with same scores
        team1 = Teams.objects.create(
            team_name="Tied Team 1",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0,
            preliminary_total_score=255.0
        )
        team2 = Teams.objects.create(
            team_name="Tied Team 2",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0,
            preliminary_total_score=255.0
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team1.id)
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team2.id)
        MapClusterToTeam.objects.create(clusterid=self.cluster.id, teamid=team1.id)
        MapClusterToTeam.objects.create(clusterid=self.cluster.id, teamid=team2.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.cluster.id)
        
        url = reverse('preliminary_results')
        data = {"contestid": self.contest.id}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Teams with tied scores should be handled (sorted by id as tiebreaker)

    def test_tabulate_scores_with_partial_scoresheets(self):
        """Test tabulating scores with teams having only some scoresheet types"""
        from ..models import Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, Judge
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            journal=False,
            mdo=False
        )

        # Assign judge to cluster
        from ..models import MapJudgeToCluster
        MapJudgeToCluster.objects.create(
            judgeid=judge.id,
            clusterid=self.cluster.id
        )

        # Create only presentation scoresheet (no journal, no mdo)
        presentation_sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=True,
            field1=5.0, field2=5.0, field3=5.0, field4=5.0,
            field5=5.0, field6=5.0, field7=10.0, field8=10.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=judge.id,
            scoresheetid=presentation_sheet.id,
            sheetType=ScoresheetEnum.PRESENTATION
        )
        
        url = reverse('tabulate_scores')
        data = {"contestid": self.contest.id}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.team.refresh_from_db()
        # Should have presentation score but journal and mdo should be 0
        self.assertGreater(self.team.presentation_score, 0.0)

    def test_tabulate_scores_with_multiple_judges(self):
        """Test tabulating scores with multiple judges (averaging)"""
        from ..models import Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, Judge
        judge1 = Judge.objects.create(
            first_name="Judge",
            last_name="One",
            phone_number="1111111111",
            contestid=self.contest.id,
            presentation=True
        )
        judge2 = Judge.objects.create(
            first_name="Judge",
            last_name="Two",
            phone_number="2222222222",
            contestid=self.contest.id,
            presentation=True
        )

        # Assign judges to cluster
        from ..models import MapJudgeToCluster
        MapJudgeToCluster.objects.create(
            judgeid=judge1.id,
            clusterid=self.cluster.id
        )
        MapJudgeToCluster.objects.create(
            judgeid=judge2.id,
            clusterid=self.cluster.id
        )
        
        # Create two presentation scoresheets from different judges
        sheet1 = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=True,
            field1=2.0, field2=2.0, field3=2.0, field4=2.0,
            field5=2.0, field6=2.0, field7=4.0, field8=4.0
        )
        sheet2 = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=True,
            field1=4.0, field2=4.0, field3=4.0, field4=4.0,
            field5=4.0, field6=4.0, field7=8.0, field8=8.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=judge1.id,
            scoresheetid=sheet1.id,
            sheetType=ScoresheetEnum.PRESENTATION
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=self.team.id,
            judgeid=judge2.id,
            scoresheetid=sheet2.id,
            sheetType=ScoresheetEnum.PRESENTATION
        )
        
        url = reverse('tabulate_scores')
        data = {"contestid": self.contest.id}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.team.refresh_from_db()
        # Should average: (20 + 40) / 2 = 30.0
        self.assertEqual(self.team.presentation_score, 30.0)

    def test_tabulate_scores_places_disqualified_teams_at_bottom(self):
        """Disqualified teams keep scores but rank below eligible teams."""
        from ..models import MapContestToCluster
        disqualified_team = Teams.objects.create(
            team_name="Disqualified Team",
            journal_score=100.0,
            presentation_score=100.0,
            machinedesign_score=100.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=300.0,
            championship_score=0.0,
            judge_disqualified=True
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=disqualified_team.id)
        MapClusterToTeam.objects.create(clusterid=self.cluster.id, teamid=disqualified_team.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.cluster.id)
        
        url = reverse('tabulate_scores')
        data = {"contestid": self.contest.id}
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Disqualified teams remain visible for score review but rank last.
        disqualified_team.refresh_from_db()
        self.assertEqual(disqualified_team.team_rank, 2)

    def test_championship_results_with_penalties(self):
        """Test championship results calculation with penalties"""
        self.team.advanced_to_championship = True
        self.team.preliminary_journal_score = 90.0
        self.team.championship_machinedesign_score = 80.0
        self.team.championship_presentation_score = 70.0
        self.team.championship_penalties_score = 10.0
        self.team.total_score = 230.0  # 90 + 80 + 70 - 10
        self.team.save()
        
        url = reverse('championship_results')
        url_with_params = f"{url}?contestid={self.contest.id}"
        response = self.client.put(url_with_params, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.data.get('data'):
            team_data = response.data['data'][0]
            self.assertEqual(team_data['total_score'], 230.0)
            self.assertEqual(team_data['penalties_score'], 10.0)


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
            championship_score=0.0
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
        from ..models import MapContestToCluster
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.preliminary_cluster.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.championship_cluster.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.redesign_cluster.id)
        
        # Map team to preliminary cluster
        MapClusterToTeam.objects.create(clusterid=self.preliminary_cluster.id, teamid=self.team.id)

    def test_advance_to_championship(self):
        url = reverse('advance_to_championship')
        data = {
            "contestid": self.contest.id,
            "championship_team_ids": [self.team.id]
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertTrue(self.team.advanced_to_championship)

    def test_undo_championship_advancement(self):
        # First advance a team
        self.team.advanced_to_championship = True
        self.team.save()
        
        url = reverse('undo_championship_advancement')
        data = {
            "contestid": self.contest.id
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.team.refresh_from_db()
        self.assertFalse(self.team.advanced_to_championship)
