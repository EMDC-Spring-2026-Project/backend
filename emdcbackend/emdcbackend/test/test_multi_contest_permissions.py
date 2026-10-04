from datetime import date

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import (
    Coach,
    Contest,
    Judge,
    JudgeClusters,
    MapContestToCluster,
    MapContestToJudge,
    MapContestToOrganizer,
    MapContestToTeam,
    MapClusterToTeam,
    MapScoresheetToTeamJudge,
    MapUserToRole,
    Organizer,
    SpecialAward,
    Scoresheet,
    ScoresheetEnum,
    Teams,
)


class MultiContestPermissionTests(APITestCase):
    """Object-wide changes require access to every linked contest."""

    def setUp(self):
        self.managed_contest = Contest.objects.create(
            name="Managed Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        self.other_contest = Contest.objects.create(
            name="Other Contest", date=date.today(), is_open=True, is_tabulated=False
        )
        self.organizer = Organizer.objects.create(first_name="One", last_name="Organizer")
        self.organizer_user = User.objects.create_user(
            username="one-organizer@example.com", password="OrganizerPassword123!"
        )
        MapUserToRole.objects.create(
            uuid=self.organizer_user.id, role=2, relatedid=self.organizer.id
        )
        MapContestToOrganizer.objects.create(
            contestid=self.managed_contest.id, organizerid=self.organizer.id
        )
        self.client.force_authenticate(user=self.organizer_user)

    def _link_team_to_both_contests(self):
        team = Teams.objects.create(team_name="Shared Team")
        MapContestToTeam.objects.create(
            contestid=self.managed_contest.id, teamid=team.id
        )
        MapContestToTeam.objects.create(contestid=self.other_contest.id, teamid=team.id)
        return team

    def test_organizer_cannot_delete_team_shared_with_unmanaged_contest(self):
        team = self._link_team_to_both_contests()

        response = self.client.delete(reverse("delete_team_by_id", args=[team.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Teams.objects.filter(id=team.id).exists())

    def test_organizer_cannot_delete_judge_shared_with_unmanaged_contest(self):
        judge = Judge.objects.create(
            first_name="Shared",
            last_name="Judge",
            phone_number="5551234567",
            contestid=self.managed_contest.id,
        )
        MapContestToJudge.objects.create(
            contestid=self.managed_contest.id, judgeid=judge.id
        )
        MapContestToJudge.objects.create(contestid=self.other_contest.id, judgeid=judge.id)

        response = self.client.delete(reverse("delete_judge", args=[judge.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Judge.objects.filter(id=judge.id).exists())

    def test_organizer_cannot_delete_cluster_shared_with_unmanaged_contest(self):
        cluster = JudgeClusters.objects.create(cluster_name="Shared Cluster")
        MapContestToCluster.objects.create(
            contestid=self.managed_contest.id, clusterid=cluster.id
        )
        MapContestToCluster.objects.create(
            contestid=self.other_contest.id, clusterid=cluster.id
        )

        response = self.client.delete(reverse("delete_cluster", args=[cluster.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(JudgeClusters.objects.filter(id=cluster.id).exists())

    def test_organizer_cannot_disqualify_team_shared_with_unmanaged_contest(self):
        team = self._link_team_to_both_contests()

        response = self.client.post(
            reverse("organizer_disqualify_team"),
            {"teamid": team.id, "organizer_disqualified": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        team.refresh_from_db()
        self.assertFalse(team.organizer_disqualified)

    def test_organizer_cannot_change_coach_for_shared_team(self):
        team = self._link_team_to_both_contests()
        coach = Coach.objects.create(first_name="Test", last_name="Coach")

        response = self.client.post(
            reverse("create_coach_team_mapping"),
            {"teamid": team.id, "coachid": coach.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_organizer_cannot_create_award_for_shared_team(self):
        team = self._link_team_to_both_contests()

        response = self.client.post(
            reverse("create_award_team_mapping"),
            {"teamid": team.id, "award_name": "Cross Contest", "isJudge": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            SpecialAward.objects.filter(teamid=team.id, award_name="Cross Contest").exists()
        )

    def test_organizer_cannot_change_cluster_shared_with_unmanaged_contest(self):
        cluster = JudgeClusters.objects.create(cluster_name="Shared Assignment Cluster")
        team = Teams.objects.create(team_name="Cluster Team")
        MapContestToCluster.objects.create(
            contestid=self.managed_contest.id, clusterid=cluster.id
        )
        MapContestToCluster.objects.create(
            contestid=self.other_contest.id, clusterid=cluster.id
        )

        response = self.client.post(
            reverse("create_cluster_team_mapping"),
            {"clusterid": cluster.id, "teamid": team.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            MapClusterToTeam.objects.filter(clusterid=cluster.id, teamid=team.id).exists()
        )

    def test_organizer_cannot_access_scoresheet_for_shared_team(self):
        team = self._link_team_to_both_contests()
        judge = Judge.objects.create(
            first_name="Score",
            last_name="Judge",
            phone_number="5559876543",
            contestid=self.managed_contest.id,
        )
        scoresheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
        )
        MapScoresheetToTeamJudge.objects.create(
            scoresheetid=scoresheet.id,
            teamid=team.id,
            judgeid=judge.id,
            sheetType=ScoresheetEnum.PRESENTATION,
        )

        response = self.client.get(reverse("scores_by_id", args=[scoresheet.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
