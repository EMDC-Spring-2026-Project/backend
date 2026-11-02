from unittest.mock import patch

from django.db import OperationalError
from django.urls import reverse
from rest_framework.test import APITestCase


class APIHealthTests(APITestCase):
    def test_health_endpoint_is_public_and_checks_database(self):
        response = self.client.get(reverse("api_health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_endpoint_returns_generic_unavailable_when_database_fails(self):
        with self.assertLogs("emdcbackend.views.health", level="ERROR"):
            with patch(
                "emdcbackend.views.health.connection.cursor",
                side_effect=OperationalError("sensitive database detail"),
            ):
                response = self.client.get(reverse("api_health"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertNotIn("sensitive database detail", response.content.decode())

    def test_health_endpoint_rejects_non_get_requests(self):
        response = self.client.post(reverse("api_health"))

        self.assertEqual(response.status_code, 405)
