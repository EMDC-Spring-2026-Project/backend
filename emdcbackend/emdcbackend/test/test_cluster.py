from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from ..models import JudgeClusters, Admin, Contest, MapContestToCluster, MapUserToRole
from ..serializers import JudgeClustersSerializer


class ClusterAPITests(APITestCase):
    def setUp(self):
        # Create a user and login using session authentication
        self.user = User.objects.create_user(username="testuser@example.com", password="testpassword")
        self.client.login(username="testuser@example.com", password="testpassword")

        # Create an admin user for role mapping
        self.admin = Admin.objects.create(first_name="Admin", last_name="User")
        MapUserToRole.objects.create(uuid=self.user.id, role=1, relatedid=self.admin.id)

    def test_cluster_by_id(self):
        cluster = JudgeClusters.objects.create(cluster_name="Test Cluster")
        url = reverse('cluster_by_id', args=[cluster.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['Cluster']['cluster_name'], "Test Cluster")

    def test_clusters_get_all(self):
        JudgeClusters.objects.create(cluster_name="Cluster 1")
        JudgeClusters.objects.create(cluster_name="Cluster 2")
        
        url = reverse('clusters_get_all')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['Clusters']), 2)

    def test_create_cluster(self):
        # Create a contest first
        from datetime import date
        from ..models import Contest
        contest = Contest.objects.create(
            name="Test Contest",
            date=date.today(),
            is_open=True,
            is_tabulated=False
        )
        
        url = reverse('create_cluster')
        data = {
            "cluster_name": "New Cluster",
            "contestid": contest.id
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['cluster']['cluster_name'], "New Cluster")
        self.assertTrue(JudgeClusters.objects.filter(cluster_name="New Cluster").exists())

    def test_edit_cluster(self):
        cluster = JudgeClusters.objects.create(cluster_name="Original Cluster")
        url = reverse('edit_cluster')
        data = {
            "id": cluster.id,
            "cluster_name": "Updated Cluster",
            "cluster_type": "preliminary"  # Can't change from preliminary to championship
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['cluster']['cluster_name'], "Updated Cluster")
        cluster.refresh_from_db()
        self.assertEqual(cluster.cluster_name, "Updated Cluster")

    def test_delete_cluster(self):
        cluster = JudgeClusters.objects.create(cluster_name="To Delete")
        url = reverse('delete_cluster', args=[cluster.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(JudgeClusters.objects.filter(id=cluster.id).exists())

    def test_unassigned_user_cannot_delete_cluster(self):
        contest = Contest.objects.create(
            name="Test Contest", date="2026-01-01", is_open=True, is_tabulated=False
        )
        cluster = JudgeClusters.objects.create(cluster_name="Protected Cluster")
        MapContestToCluster.objects.create(contestid=contest.id, clusterid=cluster.id)
        unassigned_user = User.objects.create_user(
            username="unassigned-cluster@example.com", password="testpassword"
        )
        self.client.force_authenticate(user=unassigned_user)

        response = self.client.delete(reverse('delete_cluster', args=[cluster.id]))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(JudgeClusters.objects.filter(id=cluster.id).exists())
