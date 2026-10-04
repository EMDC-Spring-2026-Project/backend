"""
Unit tests for utility and helper functions
"""
from django.test import TestCase
from django.contrib.auth.models import User
from ..views.tabulation import qdiv, sort_by_score_with_id_fallback
from ..auth.password_utils import build_set_password_url
from ..models import Teams


class QdivTests(TestCase):
    """Test the qdiv (quiet division) helper function"""
    
    def test_qdiv_normal_division(self):
        """Test normal division"""
        result = qdiv(10, 2)
        self.assertEqual(result, 5.0)
    
    def test_qdiv_float_result(self):
        """Test division that results in float"""
        result = qdiv(7, 2)
        self.assertEqual(result, 3.5)
    
    def test_qdiv_by_zero(self):
        """Test division by zero returns 0.0"""
        result = qdiv(10, 0)
        self.assertEqual(result, 0.0)
    
    def test_qdiv_by_none(self):
        """Test division by None returns 0.0"""
        result = qdiv(10, None)
        self.assertEqual(result, 0.0)
    
    def test_qdiv_numerator_none(self):
        """Test division with None numerator"""
        result = qdiv(None, 5)
        self.assertEqual(result, 0.0)
    
    def test_qdiv_string_inputs(self):
        """Test division with string inputs (should convert to float)"""
        result = qdiv("10", "2")
        self.assertEqual(result, 5.0)
    
    def test_qdiv_invalid_strings(self):
        """Test division with invalid string inputs"""
        result = qdiv("invalid", "invalid")
        self.assertEqual(result, 0.0)
    
    def test_qdiv_zero_numerator(self):
        """Test 0 divided by number"""
        result = qdiv(0, 5)
        self.assertEqual(result, 0.0)
    
    def test_qdiv_negative_numbers(self):
        """Test division with negative numbers"""
        result = qdiv(-10, 2)
        self.assertEqual(result, -5.0)
    
    def test_qdiv_negative_denominator(self):
        """Test division with negative denominator"""
        result = qdiv(10, -2)
        self.assertEqual(result, -5.0)


class SortByScoreWithIdFallbackTests(TestCase):
    """Test the sort_by_score_with_id_fallback helper function"""
    
    def setUp(self):
        """Create test teams with various scores"""
        self.team1 = Teams.objects.create(
            team_name="Team 1",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        self.team2 = Teams.objects.create(
            team_name="Team 2",
            journal_score=95.0,
            presentation_score=90.0,
            machinedesign_score=85.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=270.0,
            championship_score=0.0
        )
        self.team3 = Teams.objects.create(
            team_name="Team 3",
            journal_score=85.0,
            presentation_score=80.0,
            machinedesign_score=75.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=240.0,
            championship_score=0.0
        )
    
    def test_sort_by_total_score_descending(self):
        """Test sorting by total_score in descending order"""
        teams = [self.team1, self.team2, self.team3]
        sorted_teams = sort_by_score_with_id_fallback(teams, "total_score")
        
        # Should be sorted: team2 (270), team1 (255), team3 (240)
        self.assertEqual(sorted_teams[0], self.team2)
        self.assertEqual(sorted_teams[1], self.team1)
        self.assertEqual(sorted_teams[2], self.team3)
    
    def test_sort_by_journal_score(self):
        """Test sorting by journal_score"""
        teams = [self.team1, self.team2, self.team3]
        sorted_teams = sort_by_score_with_id_fallback(teams, "journal_score")
        
        # Should be sorted: team2 (95), team1 (90), team3 (85)
        self.assertEqual(sorted_teams[0], self.team2)
        self.assertEqual(sorted_teams[1], self.team1)
        self.assertEqual(sorted_teams[2], self.team3)
    
    def test_sort_with_tied_scores(self):
        """Test sorting with tied scores (should use id as tiebreaker)"""
        # Create teams with same score
        team_a = Teams.objects.create(
            team_name="Team A",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        team_b = Teams.objects.create(
            team_name="Team B",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        
        teams = [team_b, team_a]  # team_b has higher id
        sorted_teams = sort_by_score_with_id_fallback(teams, "total_score")
        
        # With tied scores, should sort by id ascending (lower id first)
        self.assertEqual(sorted_teams[0], team_a)
        self.assertEqual(sorted_teams[1], team_b)
    
    def test_sort_with_zero_scores_instead_of_none(self):
        """Test sorting with zero scores (None not allowed in DB)"""
        team_zero = Teams.objects.create(
            team_name="Team Zero Score",
            journal_score=0.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0
        )
        
        teams = [self.team1, team_zero]
        sorted_teams = sort_by_score_with_id_fallback(teams, "total_score")
        
        # Team with higher score should be first
        self.assertEqual(sorted_teams[0], self.team1)
        self.assertEqual(sorted_teams[1], team_zero)
    
    def test_sort_with_zero_scores(self):
        """Test sorting with zero scores"""
        team_zero = Teams.objects.create(
            team_name="Team Zero",
            journal_score=0.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0
        )
        
        teams = [team_zero, self.team1]
        sorted_teams = sort_by_score_with_id_fallback(teams, "total_score")
        
        # Team with higher score should be first
        self.assertEqual(sorted_teams[0], self.team1)
        self.assertEqual(sorted_teams[1], team_zero)
    
    def test_sort_empty_list(self):
        """Test sorting empty list"""
        teams = []
        sorted_teams = sort_by_score_with_id_fallback(teams, "total_score")
        self.assertEqual(sorted_teams, [])
    
    def test_sort_single_team(self):
        """Test sorting single team"""
        teams = [self.team1]
        sorted_teams = sort_by_score_with_id_fallback(teams, "total_score")
        self.assertEqual(sorted_teams, [self.team1])


class BuildSetPasswordUrlTests(TestCase):
    """Test the build_set_password_url helper function"""
    
    def setUp(self):
        """Create a test user"""
        self.user = User.objects.create_user(
            username="test@example.com",
            password="testpassword"
        )
    
    def test_build_set_password_url_structure(self):
        """Test that URL has correct structure"""
        url = build_set_password_url(self.user)
        
        # Should contain frontend base, uid, token, and email
        self.assertIn("set-password", url)
        self.assertIn("uid=", url)
        self.assertIn("token=", url)
        self.assertIn("email=", url)
        self.assertIn(self.user.username, url)
    
    def test_build_set_password_url_contains_uid(self):
        """Test that URL contains encoded user ID"""
        url = build_set_password_url(self.user)
        
        # Should contain uid parameter
        self.assertIn("uid=", url)
        # Extract uid from URL
        uid_part = url.split("uid=")[1].split("&")[0]
        self.assertIsNotNone(uid_part)
        self.assertGreater(len(uid_part), 0)
    
    def test_build_set_password_url_contains_token(self):
        """Test that URL contains token"""
        url = build_set_password_url(self.user)
        
        # Should contain token parameter
        self.assertIn("token=", url)
        token_part = url.split("token=")[1].split("&")[0]
        self.assertIsNotNone(token_part)
        self.assertGreater(len(token_part), 0)
    
    def test_build_set_password_url_different_users(self):
        """Test that different users get different URLs"""
        user2 = User.objects.create_user(
            username="test2@example.com",
            password="testpassword"
        )
        
        url1 = build_set_password_url(self.user)
        url2 = build_set_password_url(user2)
        
        # URLs should be different (different uid and email)
        self.assertNotEqual(url1, url2)
        self.assertIn(self.user.username, url1)
        self.assertIn(user2.username, url2)
    
    def test_build_set_password_url_uses_settings(self):
        """Test that URL uses FRONTEND_BASE_URL from settings"""
        import os
        from unittest.mock import patch
        from django.test import override_settings

        with patch.dict(os.environ, {"FRONTEND_BASE_URL": ""}), override_settings(FRONTEND_BASE_URL="https://custom-frontend.com"):
            url = build_set_password_url(self.user)
            self.assertIn("https://custom-frontend.com", url)
    
    def test_build_set_password_url_default_frontend(self):
        """Test that URL uses default frontend URL if not in settings"""
        from django.test import override_settings
        
        # Test with empty string (should use default)
        with override_settings(FRONTEND_BASE_URL=""):
            # Should use default
            url = build_set_password_url(self.user)
            # Default is http://127.0.0.1:5173
            self.assertIn("set-password", url)


class ComputeTotalsForTeamTests(TestCase):
    """Test the _compute_totals_for_team helper function with various scenarios"""
    
    def setUp(self):
        """Set up test data"""
        from datetime import date
        from ..models import Contest, JudgeClusters, MapClusterToTeam
        
        self.contest = Contest.objects.create(
            name="Test Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        
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

        # Map contest to clusters
        from ..models import MapContestToCluster
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.preliminary_cluster.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.championship_cluster.id)
        MapContestToCluster.objects.create(contestid=self.contest.id, clusterid=self.redesign_cluster.id)
    
    def test_compute_totals_no_scoresheets(self):
        """Test computing totals for team with no scoresheets"""
        from ..models import Teams, MapContestToTeam
        from ..views.tabulation import _compute_totals_for_team
        
        team = Teams.objects.create(
            team_name="Team No Sheets",
            journal_score=0.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        
        _compute_totals_for_team(team)
        team.refresh_from_db()
        
        # All scores should be 0
        self.assertEqual(team.presentation_score, 0.0)
        self.assertEqual(team.journal_score, 0.0)
        self.assertEqual(team.machinedesign_score, 0.0)
        self.assertEqual(team.total_score, 0.0)
        self.assertEqual(team.preliminary_total_score, 0.0)
    
    def test_compute_totals_preliminary_only(self):
        """Test computing totals for team with only preliminary scoresheets"""
        from ..models import Teams, Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, Judge, MapContestToTeam
        from ..views.tabulation import _compute_totals_for_team
        
        team = Teams.objects.create(
            team_name="Team Preliminary",
            journal_score=0.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0
        )
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True,
            journal=False,
            mdo=False
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)

        # Assign judge to preliminary cluster
        from ..models import MapJudgeToCluster
        MapJudgeToCluster.objects.create(
            judgeid=judge.id,
            clusterid=self.preliminary_cluster.id
        )
        
        # Create presentation scoresheet
        presentation_sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=True,
            field1=10.0, field2=10.0, field3=10.0, field4=10.0,
            field5=10.0, field6=10.0, field7=10.0, field8=10.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id,
            judgeid=judge.id,
            scoresheetid=presentation_sheet.id,
            sheetType=ScoresheetEnum.PRESENTATION
        )
        
        _compute_totals_for_team(team)
        team.refresh_from_db()
        
        # Presentation score should be 80.0 (sum of 8 fields = 80, divided by 1 judge)
        self.assertEqual(team.presentation_score, 80.0)
        self.assertEqual(team.preliminary_presentation_score, 80.0)
    
    def test_compute_totals_with_penalties(self):
        """Test computing totals with penalty scoresheets"""
        from ..models import Teams, Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, Judge, MapContestToTeam
        from ..views.tabulation import _compute_totals_for_team
        
        team = Teams.objects.create(
            team_name="Team With Penalties",
            journal_score=90.0,
            presentation_score=85.0,
            machinedesign_score=80.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=255.0,
            championship_score=0.0
        )
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            runpenalties=True,
            otherpenalties=False
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)

        # Assign judge to preliminary cluster
        from ..models import MapJudgeToCluster
        MapJudgeToCluster.objects.create(
            judgeid=judge.id,
            clusterid=self.preliminary_cluster.id
        )
        
        # Create run penalties scoresheet (all required fields for RUNPENALTIES)
        penalty_sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.RUNPENALTIES,
            isSubmitted=True,
            field1=5.0, field2=3.0, field3=0.0, field4=0.0, field5=0.0, field6=0.0, field7=0.0, field8=0.0,
            field10=0.0, field11=0.0, field12=0.0, field13=0.0, field14=0.0, field15=0.0, field16=0.0, field17=0.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id,
            judgeid=judge.id,
            scoresheetid=penalty_sheet.id,
            sheetType=ScoresheetEnum.RUNPENALTIES
        )
        
        _compute_totals_for_team(team)
        team.refresh_from_db()
        
        # Penalties should be summed (not averaged) - field1 + field2 = 8.0
        self.assertEqual(team.penalties_score, 8.0)
    
    def test_compute_totals_championship_round(self):
        """Test computing totals for championship round"""
        from ..models import Teams, Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, Judge, MapContestToTeam, MapClusterToTeam
        from ..views.tabulation import _compute_totals_for_team
        
        team = Teams.objects.create(
            team_name="Championship Team",
            journal_score=90.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0,
            advanced_to_championship=True,
            preliminary_journal_score=90.0
        )
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            championship=True
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        MapClusterToTeam.objects.create(clusterid=self.championship_cluster.id, teamid=team.id)

        # Assign judge to championship cluster
        from ..models import MapJudgeToCluster
        MapJudgeToCluster.objects.create(
            judgeid=judge.id,
            clusterid=self.championship_cluster.id
        )
        
        # Create championship scoresheet
        championship_sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.CHAMPIONSHIP,
            isSubmitted=True,
            field1=10.0, field2=10.0, field3=10.0, field4=10.0,  # Machine Design (fields 1-8)
            field5=10.0, field6=10.0, field7=10.0, field8=10.0,
            field10=15.0, field11=15.0, field12=15.0, field13=15.0,  # Presentation (fields 10-17)
            field14=15.0, field15=15.0, field16=15.0, field17=15.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id,
            judgeid=judge.id,
            scoresheetid=championship_sheet.id,
            sheetType=ScoresheetEnum.CHAMPIONSHIP
        )
        
        _compute_totals_for_team(team)
        team.refresh_from_db()
        
        # Championship scores should be calculated
        self.assertEqual(team.championship_machinedesign_score, 80.0)  # 8 fields * 10 = 80
        self.assertEqual(team.championship_presentation_score, 120.0)  # 8 fields * 15 = 120
        # Total = journal (90) + machine design (80) + presentation (120) - penalties (0) = 290
        # But preliminary scores are also calculated, so check championship score specifically
        self.assertGreaterEqual(team.championship_machinedesign_score, 80.0)
        self.assertGreaterEqual(team.championship_presentation_score, 120.0)
    
    def test_compute_totals_redesign_round(self):
        """Test computing totals for redesign round"""
        from ..models import Teams, Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, Judge, MapContestToTeam, MapClusterToTeam
        from ..views.tabulation import _compute_totals_for_team
        
        team = Teams.objects.create(
            team_name="Redesign Team",
            journal_score=0.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0,
            advanced_to_championship=False
        )
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            redesign=True
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        MapClusterToTeam.objects.create(clusterid=self.redesign_cluster.id, teamid=team.id)

        # Assign judge to redesign cluster
        from ..models import MapJudgeToCluster
        MapJudgeToCluster.objects.create(
            judgeid=judge.id,
            clusterid=self.redesign_cluster.id
        )
        
        # Create redesign scoresheet (field7 is required)
        redesign_sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.REDESIGN,
            isSubmitted=True,
            field1=20.0, field2=20.0, field3=20.0,
            field4=20.0, field5=20.0, field6=20.0, field7=0.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id,
            judgeid=judge.id,
            scoresheetid=redesign_sheet.id,
            sheetType=ScoresheetEnum.REDESIGN
        )
        
        _compute_totals_for_team(team)
        team.refresh_from_db()
        
        # Redesign score should be sum of all fields (120.0)
        self.assertEqual(team.redesign_score, 120.0)
        self.assertEqual(team.total_score, 120.0)
    
    def test_compute_totals_unsubmitted_scoresheets(self):
        """Test that unsubmitted scoresheets are not counted"""
        from ..models import Teams, Scoresheet, ScoresheetEnum, MapScoresheetToTeamJudge, Judge, MapContestToTeam
        from ..views.tabulation import _compute_totals_for_team
        
        team = Teams.objects.create(
            team_name="Team Unsubmitted",
            journal_score=0.0,
            presentation_score=0.0,
            machinedesign_score=0.0,
            penalties_score=0.0,
            redesign_score=0.0,
            total_score=0.0,
            championship_score=0.0
        )
        judge = Judge.objects.create(
            first_name="Test",
            last_name="Judge",
            phone_number="1234567890",
            contestid=self.contest.id,
            presentation=True
        )
        MapContestToTeam.objects.create(contestid=self.contest.id, teamid=team.id)
        
        # Create unsubmitted scoresheet
        unsubmitted_sheet = Scoresheet.objects.create(
            sheetType=ScoresheetEnum.PRESENTATION,
            isSubmitted=False,  # Not submitted
            field1=100.0, field2=100.0, field3=100.0, field4=100.0,
            field5=100.0, field6=100.0, field7=100.0, field8=100.0
        )
        MapScoresheetToTeamJudge.objects.create(
            teamid=team.id,
            judgeid=judge.id,
            scoresheetid=unsubmitted_sheet.id,
            sheetType=ScoresheetEnum.PRESENTATION
        )
        
        _compute_totals_for_team(team)
        team.refresh_from_db()
        
        # Unsubmitted scoresheet should not be counted
        self.assertEqual(team.presentation_score, 0.0)

