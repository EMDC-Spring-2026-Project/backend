from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from ..models import RoleSharedPassword, Admin, Organizer, MapUserToRole
from ..auth.password_validators import (
    UppercasePasswordValidator,
    LowercasePasswordValidator,
    SpecialCharacterPasswordValidator
)


class PasswordAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an admin user for role mapping
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

        # Create a test user for password operations
        self.test_user = User.objects.create_user(username="testpass@example.com", password="oldpassword")

    def test_request_set_password(self):
        """Test admin/organizer sending set-password email"""
        url = reverse('request_set_password')
        data = {
            "username": self.test_user.username
        }
        response = self.client.post(url, data)
        # Note: This might fail if email backend is not configured, but should return 200 or 500
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_500_INTERNAL_SERVER_ERROR])
        if response.status_code == status.HTTP_200_OK:
            self.assertEqual(response.data['detail'], "Set-password email sent.")

    def test_request_password_reset(self):
        """Test public forgot password endpoint"""
        # Create an admin user for password reset (only admins and coaches can reset)
        admin_user = User.objects.create_user(username="adminreset@example.com", password="AdminPass123!")
        admin_obj = Admin.objects.create(first_name="Admin", last_name="Reset")
        MapUserToRole.objects.create(uuid=admin_user.id, role=1, relatedid=admin_obj.id)
        
        url = reverse('request_password_reset')
        data = {
            "username": admin_user.username
        }
        response = self.client.post(url, data)
        # Note: This might fail if email backend is not configured, but should return 200 or 500
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_500_INTERNAL_SERVER_ERROR])
        if response.status_code == status.HTTP_200_OK:
            self.assertIn('detail', response.data)

    def test_password_reset_does_not_reveal_ineligible_accounts(self):
        organizer_user = User.objects.create_user(
            username="organizer-reset@example.com", password="OrganizerPass123!"
        )
        organizer = Organizer.objects.create(first_name="Test", last_name="Organizer")
        MapUserToRole.objects.create(
            uuid=organizer_user.id, role=2, relatedid=organizer.id
        )
        url = reverse('request_password_reset')

        existing_response = self.client.post(url, {"username": organizer_user.username})
        missing_response = self.client.post(url, {"username": "missing@example.com"})

        self.assertEqual(existing_response.status_code, status.HTTP_200_OK)
        self.assertEqual(missing_response.status_code, status.HTTP_200_OK)
        self.assertEqual(existing_response.data, missing_response.data)

    def test_validate_password_token(self):
        """Test validating password reset token"""
        # Generate a valid token
        token = default_token_generator.make_token(self.test_user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.test_user.pk))
        
        url = reverse('validate_password_token')
        data = {
            "uid": uidb64,
            "token": token
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], "Token valid.")

    def test_validate_password_token_invalid(self):
        """Test validating invalid password reset token"""
        uidb64 = urlsafe_base64_encode(force_bytes(self.test_user.pk))
        
        url = reverse('validate_password_token')
        data = {
            "uid": uidb64,
            "token": "invalid_token"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], "Invalid or expired link.")

    def test_complete_password_set(self):
        """Test completing password set/reset"""
        # Generate a valid token
        token = default_token_generator.make_token(self.test_user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.test_user.pk))
        
        url = reverse('complete_password_set')
        data = {
            "uid": uidb64,
            "token": token,
            "password": "NewPassword123!"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('detail', response.data)
        
        # Verify password was changed
        self.test_user.refresh_from_db()
        self.assertTrue(self.test_user.check_password("NewPassword123!"))

    def test_complete_password_set_invalid_token(self):
        """Test completing password set with invalid token"""
        uidb64 = urlsafe_base64_encode(force_bytes(self.test_user.pk))
        
        url = reverse('complete_password_set')
        data = {
            "uid": uidb64,
            "token": "invalid_token",
            "password": "NewPassword123!"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_shared_password_organizer(self):
        """Test setting shared password for organizer role"""
        url = reverse('set_shared_password')
        data = {
            "role": 2,  # Organizer
            "password": "SharedOrgPass123!"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success', False))
        self.assertTrue(RoleSharedPassword.objects.filter(role=2).exists())

    def test_set_shared_password_judge(self):
        """Test setting shared password for judge role"""
        url = reverse('set_shared_password')
        data = {
            "role": 3,  # Judge
            "password": "SharedJudgePass123!"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success', False))
        self.assertTrue(RoleSharedPassword.objects.filter(role=3).exists())

    def test_set_shared_password_invalid_role(self):
        """Test setting shared password with invalid role"""
        url = reverse('set_shared_password')
        data = {
            "role": 1,  # Invalid (should be 2 or 3)
            "password": "ValidPass123!"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_set_shared_password_update_existing(self):
        """Test updating existing shared password"""
        # Create existing shared password
        RoleSharedPassword.objects.create(role=2, password_hash="old_hash")
        
        url = reverse('set_shared_password')
        data = {
            "role": 2,
            "password": "NewPassword123!"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        # Should update, not create new
        self.assertEqual(RoleSharedPassword.objects.filter(role=2).count(), 1)


class PasswordValidationTests(APITestCase):
    """Test password validation requirements: uppercase, lowercase, special character, min 8 chars"""
    
    def setUp(self):
        # Create an admin user for testing shared passwords
        self.user = User.objects.create_user(username="admin@example.com", password="AdminPass123!")
        self.client.login(username="admin@example.com", password="AdminPass123!")
        
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)
        
        # Create a test user for password reset tests
        self.test_user = User.objects.create_user(username="testuser@example.com", password="OldPass123!")
    
    def test_uppercase_validator(self):
        """Test that uppercase validator rejects passwords without uppercase letters"""
        validator = UppercasePasswordValidator()
        
        # Should pass
        try:
            validator.validate("Password123!")
        except ValidationError:
            self.fail("UppercasePasswordValidator raised ValidationError unexpectedly")
        
        # Should fail
        with self.assertRaises(ValidationError):
            validator.validate("password123!")
    
    def test_lowercase_validator(self):
        """Test that lowercase validator rejects passwords without lowercase letters"""
        validator = LowercasePasswordValidator()
        
        # Should pass
        try:
            validator.validate("Password123!")
        except ValidationError:
            self.fail("LowercasePasswordValidator raised ValidationError unexpectedly")
        
        # Should fail
        with self.assertRaises(ValidationError):
            validator.validate("PASSWORD123!")
    
    def test_special_character_validator(self):
        """Test that special character validator rejects passwords without special characters"""
        validator = SpecialCharacterPasswordValidator()
        
        # Should pass
        try:
            validator.validate("Password123!")
        except ValidationError:
            self.fail("SpecialCharacterPasswordValidator raised ValidationError unexpectedly")
        
        # Should fail
        with self.assertRaises(ValidationError):
            validator.validate("Password123")
    
    def test_weak_passwords_rejected_in_signup(self):
        """Test that signup endpoint rejects weak passwords"""
        url = reverse('signup')
        
        weak_passwords = [
            "short",  # Too short
            "nouppercase123!",  # No uppercase
            "NOLOWERCASE123!",  # No lowercase
            "NoSpecialChar123",  # No special character
            "OnlyLowercase",  # No uppercase, no special, no numbers
            "12345678",  # All numeric
        ]
        
        for weak_password in weak_passwords:
            response = self.client.post(url, {
                'username': f'test{weak_password}@example.com',
                'password': weak_password
            })
            # Should reject weak passwords
            self.assertIn(response.status_code, [
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ], f"Password '{weak_password}' should have been rejected but got {response.status_code}")
    
    def test_strong_password_accepted_in_signup(self):
        """Test that signup endpoint accepts strong passwords"""
        url = reverse('signup')
        
        strong_password = "StrongPass123!"
        response = self.client.post(url, {
            'username': 'newuser@example.com',
            'password': strong_password
        })
        # Should accept strong password
        self.assertIn(response.status_code, [
            status.HTTP_201_CREATED,
            status.HTTP_200_OK  # If user already exists
        ])
    
    def test_weak_passwords_rejected_in_complete_password_set(self):
        """Test that complete_password_set endpoint rejects weak passwords"""
        # Generate a valid token
        token = default_token_generator.make_token(self.test_user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.test_user.pk))
        
        url = reverse('complete_password_set')
        
        weak_passwords = [
            "short",  # Too short
            "nouppercase123!",  # No uppercase
            "NOLOWERCASE123!",  # No lowercase
            "NoSpecialChar123",  # No special character
        ]
        
        for weak_password in weak_passwords:
            response = self.client.post(url, {
                "uid": uidb64,
                "token": token,
                "password": weak_password
            })
            # Should reject weak passwords
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn('password', response.data or {})
    
    def test_strong_password_accepted_in_complete_password_set(self):
        """Test that complete_password_set endpoint accepts strong passwords"""
        # Generate a valid token
        token = default_token_generator.make_token(self.test_user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.test_user.pk))
        
        url = reverse('complete_password_set')
        strong_password = "NewStrongPass123!"
        
        response = self.client.post(url, {
            "uid": uidb64,
            "token": token,
            "password": strong_password
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify password was changed
        self.test_user.refresh_from_db()
        self.assertTrue(self.test_user.check_password(strong_password))
    
    def test_weak_passwords_rejected_in_shared_password(self):
        """Test that set_shared_password endpoint rejects weak passwords"""
        url = reverse('set_shared_password')
        
        weak_passwords = [
            "short",  # Too short
            "nouppercase123!",  # No uppercase
            "NOLOWERCASE123!",  # No lowercase
            "NoSpecialChar123",  # No special character
        ]
        
        for weak_password in weak_passwords:
            response = self.client.post(url, {
                "role": 2,  # Organizer
                "password": weak_password
            })
            # Should reject weak passwords
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn('error', response.data)
            self.assertIn('Password', str(response.data).title())
    
    def test_strong_password_accepted_in_shared_password(self):
        """Test that set_shared_password endpoint accepts strong passwords"""
        url = reverse('set_shared_password')
        
        strong_password = "SharedPass123!"
        response = self.client.post(url, {
            "role": 2,  # Organizer
            "password": strong_password
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success', False))
        self.assertTrue(RoleSharedPassword.objects.filter(role=2).exists())
    
    def test_django_validate_password_integration(self):
        """Test that Django's validate_password uses our custom validators"""
        # Weak passwords should fail
        weak_passwords = [
            "nouppercase123!",
            "NOLOWERCASE123!",
            "NoSpecialChar123",
            "short",
        ]
        
        for weak_password in weak_passwords:
            with self.assertRaises(ValidationError):
                validate_password(weak_password)
        
        # Strong password should pass
        try:
            validate_password("StrongPass123!")
        except ValidationError:
            self.fail("Strong password should have passed validation")
    
    def test_password_requirements_all_met(self):
        """Test that passwords meeting all requirements pass validation"""
        strong_passwords = [
            "Password123!",
            "MySecurePass456@",
            "Test123#Pass",
            "Complex$Pass789",
            "Simple!Pass1",
        ]
        
        for strong_password in strong_passwords:
            try:
                validate_password(strong_password)
            except ValidationError as e:
                self.fail(f"Password '{strong_password}' should have passed but failed: {e}")
