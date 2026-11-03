"""
Django management command to create admin accounts.

This is the recommended way to create admin accounts in all environments.

Usage:
    # Interactive mode (prompts for input)
    python manage.py create_first_admin
    
    # Non-interactive mode (read the password from the named environment variable)
    CREATE_ADMIN_PASSWORD='...' python manage.py create_first_admin --username admin@example.com --password-env CREATE_ADMIN_PASSWORD
"""

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.contrib.auth.models import User
import os
from getpass import getpass
from emdcbackend.models import Admin, MapUserToRole
from emdcbackend.serializers import AdminSerializer


class Command(BaseCommand):
    help = 'Create an admin account (works for first admin or additional admins)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Email address for the admin account',
        )
        parser.add_argument(
            '--password-env',
            type=str,
            help='Name of the environment variable containing the password',
        )
        parser.add_argument(
            '--first-name',
            type=str,
            default='Admin',
            help='First name of the admin',
        )
        parser.add_argument(
            '--last-name',
            type=str,
            default='User',
            help='Last name of the admin',
        )

    def handle(self, *args, **options):
        # Check if any admins already exist
        admin_count = MapUserToRole.objects.filter(role=MapUserToRole.RoleEnum.ADMIN).count()
        if admin_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Note: {admin_count} admin(s) already exist. Creating additional admin...'
                )
            )

        # Get input interactively if not provided
        username = options.get('username')
        if not username:
            username = input('Email address (username): ').strip()
            if not username:
                raise CommandError('Username is required.')

        password_env = options.get('password_env')
        if password_env:
            password = os.environ.get(password_env)
            if not password:
                raise CommandError(f'Password environment variable {password_env} is not set.')
        else:
            password = getpass('Password: ')
            if not password:
                raise CommandError('Password is required.')
            password_confirmation = getpass('Confirm password: ')
            if password != password_confirmation:
                raise CommandError('Passwords do not match.')

        first_name = options.get('first_name', 'Admin')
        last_name = options.get('last_name', 'User')

        candidate_user = User(
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        try:
            validate_password(password, user=candidate_user)
        except ValidationError as error:
            messages = '; '.join(error.messages)
            raise CommandError(
                f'Password does not meet the password requirements: {messages}'
            ) from error

        # Check if user already exists
        existing_user = User.objects.filter(username__iexact=username).first()
        if existing_user:
            existing_map = MapUserToRole.objects.filter(
                uuid=existing_user.id, role=MapUserToRole.RoleEnum.ADMIN
            ).first()
            if existing_map:
                self.stdout.write(
                    self.style.WARNING(
                        f'Admin already exists for user: {username}'
                    )
                )
                return

        try:
            with transaction.atomic():
                # Create user if doesn't exist
                if not existing_user:
                    user = User.objects.create_user(username=username, password=password)
                    self.stdout.write(self.style.SUCCESS(f'Created user: {username}'))
                else:
                    user = existing_user
                    user.set_password(password)
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f'Updated password for user: {username}'))

                # Create admin
                admin_data = {"first_name": first_name, "last_name": last_name}
                serializer = AdminSerializer(data=admin_data)
                if serializer.is_valid():
                    admin = serializer.save()
                    self.stdout.write(self.style.SUCCESS(f'Created admin: {first_name} {last_name}'))
                else:
                    raise ValidationError(serializer.errors)

                # Create role mapping
                MapUserToRole.objects.get_or_create(
                    uuid=user.id,
                    role=MapUserToRole.RoleEnum.ADMIN,
                    defaults={'relatedid': admin.id}
                )
                self.stdout.write(self.style.SUCCESS('Created admin role mapping'))

            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✓ Successfully created admin account!\n'
                    f'  Username: {username}\n'
                    f'  Name: {first_name} {last_name}\n'
                    f'  You can now log in at /api/login/'
                )
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating admin: {str(e)}'))
            raise

