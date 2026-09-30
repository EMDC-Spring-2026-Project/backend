from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth.models import User
from ..models import Admin, MapUserToRole
from ..serializers import AdminSerializer

class UserAuthTests(APITestCase):

    def setUp(self):
        # Create a test user
        self.user_data = {
            'username': 'testuser',
            'password': 'testpassword',
            'email': 'test@example.com'
        }
        self.user = User.objects.create_user(**self.user_data)

        # Create an Admin object
        self.admin_data = {
            'first_name': 'Test',
            'last_name': 'Admin',
        }
        self.admin = Admin.objects.create(**self.admin_data)

        # Map user to Admin role
        self.mapping = MapUserToRole.objects.create(
            uuid=self.user.id,
            role=1,  # Assuming 1 is the role for Admin
            relatedid=self.admin.id
        )

    def test_login(self):
        url = reverse('login')
        response = self.client.post(url, {
            'username': self.user.username,
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Login endpoint returns JsonResponse, parse JSON manually
        response_data = response.json()
        self.assertIn('user', response_data)
        self.assertEqual(response_data['user']['username'], self.user.username)
        self.assertEqual(response_data['role']['user_type'], 1)  # Ensure user role is Admin

    def test_login_invalid_user(self):
        url = reverse('login')
        response = self.client.post(url, {'username': 'invaliduser', 'password': 'wrongpassword'})
        # Login endpoint returns 401 for invalid credentials (not 404)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # Login endpoint returns JsonResponse, parse JSON manually
        response_data = response.json()
        self.assertEqual(response_data['detail'], 'Invalid credentials')

    def test_signup(self):
        url = reverse('signup')
        new_user_data = {
            'username': 'newuser@example.com',  # Must be a valid email
            'password': 'NewPassword123!'
        }
        response = self.client.post(url, new_user_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Session authentication doesn't return token, check for user instead
        self.assertIn('user', response.data)

    def test_get_user_by_id(self):
        url = reverse('user_by_id', kwargs={'user_id': self.user.id})
        self.client.login(username='testuser', password='testpassword')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['username'], self.user.username)

    def test_edit_user(self):
        url = reverse('edit_user')
        self.client.login(username='testuser', password='testpassword')
        response = self.client.post(url, {
            'id': self.user.id,
            'username': 'updateduser@example.com',  # Must be a valid email
            'password': 'updatedpassword'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['username'], 'updateduser@example.com')

    def test_delete_user(self):
        url = reverse('delete_user_by_id', kwargs={'user_id': self.user.id})
        self.client.login(username='testuser', password='testpassword')
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], 'User deleted successfully.')

    def test_session_verification(self):
        url = reverse('test_token')
        self.client.login(username='testuser', password='testpassword')
        response = self.client.get(url)

        # Check if the response data contains the entire string
        self.assertIn(f'passed for {self.user.username}', response.data)


class UserAccountAuthorizationTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner@example.com', password='OwnerPassword123!'
        )
        self.other_user = User.objects.create_user(
            username='other@example.com', password='OtherPassword123!'
        )

    def test_user_lookup_requires_authentication(self):
        response = self.client.get(
            reverse('user_by_id', kwargs={'user_id': self.owner.id})
        )
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_user_cannot_view_another_account(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(
            reverse('user_by_id', kwargs={'user_id': self.other_user.id})
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_cannot_edit_another_account(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            reverse('edit_user'),
            {
                'id': self.other_user.id,
                'username': 'stolen@example.com',
                'password': 'ChangedPassword123!',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.other_user.refresh_from_db()
        self.assertEqual(self.other_user.username, 'other@example.com')
        self.assertTrue(self.other_user.check_password('OtherPassword123!'))

    def test_user_cannot_delete_another_account(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(
            reverse('delete_user_by_id', kwargs={'user_id': self.other_user.id})
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(User.objects.filter(id=self.other_user.id).exists())

    def test_user_can_view_and_edit_own_account(self):
        self.client.force_authenticate(user=self.owner)
        lookup_response = self.client.get(
            reverse('user_by_id', kwargs={'user_id': self.owner.id})
        )
        self.assertEqual(lookup_response.status_code, status.HTTP_200_OK)

        edit_response = self.client.post(
            reverse('edit_user'),
            {'id': self.owner.id, 'username': 'updated-owner@example.com'},
            format='json',
        )
        self.assertEqual(edit_response.status_code, status.HTTP_200_OK)

    def test_admin_role_can_manage_another_account(self):
        admin_user = User.objects.create_user(
            username='admin@example.com', password='AdminPassword123!'
        )
        admin = Admin.objects.create(first_name='Site', last_name='Admin')
        MapUserToRole.objects.create(uuid=admin_user.id, role=1, relatedid=admin.id)
        self.client.force_authenticate(user=admin_user)

        lookup_response = self.client.get(
            reverse('user_by_id', kwargs={'user_id': self.other_user.id})
        )
        self.assertEqual(lookup_response.status_code, status.HTTP_200_OK)

        edit_response = self.client.post(
            reverse('edit_user'),
            {'id': self.other_user.id, 'username': 'managed@example.com'},
            format='json',
        )
        self.assertEqual(edit_response.status_code, status.HTTP_200_OK)

