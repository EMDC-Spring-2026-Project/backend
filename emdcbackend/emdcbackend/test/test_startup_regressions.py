from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from unittest.mock import patch
from ..auth.utils import send_email_via_resend


class StartupRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user(username="audit"))

    def test_get_endpoints_reject_missing_and_invalid_ids(self):
        for name, key in [
            ("get_teams_by_team_rank", "contestid"),
            ("get_teams_by_cluster_rank", "clusterid"),
            ("get_scoresheet_details_for_contest", "contestid"),
        ]:
            for value in [None, "bad", "0", "-1"]:
                with self.subTest(endpoint=name, value=value):
                    data = {} if value is None else {key: value}
                    self.assertEqual(self.client.get(reverse(name), data).status_code, 400)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @patch("resend.Emails.send")
    def test_local_email_delivery_does_not_contact_resend(self, send):
        result = send_email_via_resend("coach@example.com", "Set password", "<p>Local link</p>")
        self.assertEqual(result, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].body, "Local link")
        send.assert_not_called()
