from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from datetime import date
from ..models import Admin, Contest, JudgeClusters, MapContestToCluster, MapUserToRole
from ..serializers import ContestSerializer


class ContestAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")
        self.admin = Admin.objects.create(first_name="Test", last_name="Administrator")
        MapUserToRole.objects.create(
            uuid=self.user.id,
            role=MapUserToRole.RoleEnum.ADMIN,
            relatedid=self.admin.id,
        )

    def test_contest_by_id(self):
        contest = Contest.objects.create(
            name="Test Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        url = reverse('contest_by_id', args=[contest.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['Contest']['name'], "Test Contest")

    def test_contest_get_all(self):
        Contest.objects.create(name="Contest 1", date=date.today(), is_open=True, is_tabulated=False)
        Contest.objects.create(name="Contest 2", date=date.today(), is_open=False, is_tabulated=True)
        
        url = reverse('contest_get_all')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['Contests']), 2)

    def test_create_contest(self):
        url = reverse('create_contest')
        data = {
            "name": "New Contest",
            "date": str(date.today())
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['contest']['name'], "New Contest")
        self.assertTrue(Contest.objects.filter(name="New Contest").exists())

    def test_edit_contest(self):
        contest = Contest.objects.create(
            name="Original Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        url = reverse('edit_contest')
        data = {
            "id": contest.id,
            "name": "Updated Contest",
            "date": str(date.today()),
            "is_open": False,
            "is_tabulated": True
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['Contest']['name'], "Updated Contest")
        contest.refresh_from_db()
        self.assertFalse(contest.is_open)
        self.assertTrue(contest.is_tabulated)

    def test_delete_contest(self):
        contest = Contest.objects.create(
            name="To Delete",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        url = reverse('delete_contest', args=[contest.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Contest.objects.filter(id=contest.id).exists())

    def test_unprivileged_user_cannot_manage_contests(self):
        contest = Contest.objects.create(
            name="Protected Contest", date=date.today(), is_open=False, is_tabulated=False
        )
        unprivileged_user = User.objects.create_user(
            username="judge@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unprivileged_user)

        create_response = self.client.post(
            reverse('create_contest'), {"name": "Unauthorized", "date": str(date.today())}
        )
        edit_response = self.client.post(
            reverse('edit_contest'),
            {"id": contest.id, "name": "Changed", "date": str(date.today()), "is_open": True, "is_tabulated": False},
        )
        delete_response = self.client.delete(reverse('delete_contest', args=[contest.id]))

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(edit_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)
        contest.refresh_from_db()
        self.assertEqual(contest.name, "Protected Contest")
