from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from datetime import date
from ..models import (
    Ballot, Votes, MapBallotToVote, MapVoteToAward, MapTeamToVote, MapAwardToContest,
    Contest, Teams, SpecialAward, Admin, MapUserToRole
)


class BallotVoteAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an admin user for role mapping
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

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
        self.award = SpecialAward.objects.create(
            teamid=self.team.id,
            award_name="Best Design",
            isJudge=True
        )

    # Ballot Tests
    def test_create_ballot(self):
        url = reverse('create_ballot')
        data = {
            "contestid": self.contest.id,
            "isSubmitted": False
        }
        response = self.client.post(url, data)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(Ballot.objects.filter(contestid=self.contest.id).exists())

    def test_get_all_ballots(self):
        Ballot.objects.create(contestid=self.contest.id, isSubmitted=False)
        Ballot.objects.create(contestid=self.contest.id, isSubmitted=True)
        
        url = reverse('get_all_ballots')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data.get('ballots', [])), 2)

    def test_delete_ballot(self):
        ballot = Ballot.objects.create(contestid=self.contest.id, isSubmitted=False)
        url = reverse('delete_ballot', args=[ballot.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Ballot.objects.filter(id=ballot.id).exists())

    # Vote Tests
    def test_create_vote(self):
        url = reverse('create_vote')
        data = {
            "votedteamid": self.team.id
        }
        response = self.client.post(url, data)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(Votes.objects.filter(votedteamid=self.team.id).exists())

    def test_get_all_votes(self):
        Votes.objects.create(votedteamid=self.team.id)
        
        url = reverse('get_all_votes')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data.get('votes', [])), 1)

    # Mapping Tests
    def test_create_map_ballot_to_vote(self):
        ballot = Ballot.objects.create(contestid=self.contest.id, isSubmitted=False)
        vote = Votes.objects.create(votedteamid=self.team.id)
        
        url = reverse('create_map_ballot_to_vote')
        data = {
            "ballotid": ballot.id,
            "voteid": vote.id
        }
        response = self.client.post(url, data)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(MapBallotToVote.objects.filter(ballotid=ballot.id, voteid=vote.id).exists())

    def test_create_map_vote_to_award(self):
        vote = Votes.objects.create(votedteamid=self.team.id)
        
        url = reverse('create_map_vote_to_award')
        data = {
            "voteid": vote.id,
            "awardid": self.award.id
        }
        response = self.client.post(url, data)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(MapVoteToAward.objects.filter(voteid=vote.id, awardid=self.award.id).exists())

    def test_create_map_team_to_vote(self):
        vote = Votes.objects.create(votedteamid=self.team.id)
        
        url = reverse('create_map_team_to_vote')
        data = {
            "teamid": self.team.id,
            "voteid": vote.id
        }
        response = self.client.post(url, data)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(MapTeamToVote.objects.filter(teamid=self.team.id, voteid=vote.id).exists())

    def test_create_map_award_to_contest(self):
        url = reverse('create_map_award_to_contest')
        data = {
            "contestid": self.contest.id,
            "awardid": self.award.id
        }
        response = self.client.post(url, data)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(MapAwardToContest.objects.filter(contestid=self.contest.id, awardid=self.award.id).exists())

    def test_non_admin_cannot_access_ballot_or_vote_admin_endpoints(self):
        ordinary_user = User.objects.create_user(
            username="ordinary-ballot-user@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=ordinary_user)
        ballot = Ballot.objects.create(contestid=self.contest.id, isSubmitted=False)
        vote = Votes.objects.create(votedteamid=self.team.id)

        requests = [
            self.client.post(reverse('create_ballot'), {
                "contestid": self.contest.id, "isSubmitted": False
            }),
            self.client.get(reverse('get_all_ballots')),
            self.client.delete(reverse('delete_ballot', args=[ballot.id])),
            self.client.post(reverse('create_vote'), {"votedteamid": self.team.id}),
            self.client.get(reverse('get_all_votes')),
            self.client.post(reverse('create_map_ballot_to_vote'), {
                "ballotid": ballot.id, "voteid": vote.id
            }),
            self.client.post(reverse('create_map_vote_to_award'), {
                "voteid": vote.id, "awardid": self.award.id
            }),
            self.client.post(reverse('create_map_team_to_vote'), {
                "teamid": self.team.id, "voteid": vote.id
            }),
            self.client.post(reverse('create_map_award_to_contest'), {
                "contestid": self.contest.id, "awardid": self.award.id
            }),
        ]

        for response in requests:
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Ballot.objects.filter(id=ballot.id).exists())

