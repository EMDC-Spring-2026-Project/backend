from django.db.models import Q

from ..models import MapContestToCluster, MapJudgeToCluster


def judge_cluster_assignments_for_contest(contest_id, cluster_ids=None):
    """Return judge-cluster assignments that unambiguously belong to a contest.

    New mappings carry ``contestid``. For legacy mappings without it, infer
    ownership only when the cluster is attached to this contest alone.
    """
    contest_clusters = MapContestToCluster.objects.filter(contestid=contest_id)
    if cluster_ids is not None:
        contest_clusters = contest_clusters.filter(clusterid__in=cluster_ids)

    contest_cluster_ids = list(
        contest_clusters.values_list("clusterid", flat=True).distinct()
    )
    if not contest_cluster_ids:
        return MapJudgeToCluster.objects.none()

    contests_by_cluster = {}
    for cluster_id, mapped_contest_id in MapContestToCluster.objects.filter(
        clusterid__in=contest_cluster_ids
    ).values_list("clusterid", "contestid"):
        contests_by_cluster.setdefault(cluster_id, set()).add(mapped_contest_id)

    unambiguous_legacy_cluster_ids = [
        cluster_id
        for cluster_id in contest_cluster_ids
        if contests_by_cluster.get(cluster_id) == {contest_id}
    ]
    return MapJudgeToCluster.objects.filter(
        clusterid__in=contest_cluster_ids
    ).filter(
        Q(contestid=contest_id)
        | Q(contestid__isnull=True, clusterid__in=unambiguous_legacy_cluster_ids)
    )
