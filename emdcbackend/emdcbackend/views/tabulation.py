import logging

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User

from ..models import (
    Contest,
    Teams,
    Scoresheet,
    MapScoresheetToTeamJudge,
    MapContestToTeam,
    ScoresheetEnum,
    MapClusterToTeam,
    JudgeClusters,
    MapContestToCluster,
    MapContestToOrganizer,
    MapUserToRole,
    MapJudgeToCluster,
    MapContestToJudge,
    Judge,
)
from .contest_utils import judge_cluster_assignments_for_contest

logger = logging.getLogger(__name__)

# ---------- Shared Helpers ----------

def qdiv(numer, denom):
    """Quiet division: returns 0.0 if denom is falsy/zero."""
    try:
        return float(numer) / float(denom) if denom else 0.0
    except Exception:
        return 0.0


def sort_by_score_with_id_fallback(teams, score_attr: str):
    """Sort by score descending, then team.id ascending."""
    def _score(t):
        v = getattr(t, score_attr)
        try:
            return float(v) if v is not None else 0.0
        except (ValueError, TypeError):
            return 0.0
    return sorted(teams, key=lambda t: (-_score(t), t.id))


def _numeric(value):
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_disqualified(team):
    return bool(team.judge_disqualified or team.organizer_disqualified)


def sort_by_standard_round_tiebreakers(teams, championship=False):
    """Apply the official total, machine, presentation, journal tiebreakers."""
    if championship:
        return sorted(
            teams,
            key=lambda team: (
                _is_disqualified(team),
                -_numeric(team.total_score),
                -_numeric(team.championship_machinedesign_score),
                -_numeric(team.championship_presentation_score),
                -_numeric(team.preliminary_journal_score),
                team.id,
            ),
        )
    return sorted(
        teams,
        key=lambda team: (
            _is_disqualified(team),
            -_numeric(team.preliminary_total_score),
            -_numeric(team.preliminary_machinedesign_score),
            -_numeric(team.preliminary_presentation_score),
            -_numeric(team.preliminary_journal_score),
            team.id,
        ),
    )


def _redesign_tiebreak_scores(team_id, contest_id):
    active_judge_ids = set(
        judge_cluster_assignments_for_contest(contest_id).values_list(
            "judgeid", flat=True
        )
    ) | set(
        MapContestToJudge.objects.filter(contestid=contest_id).values_list(
            "judgeid", flat=True
        )
    )
    sheet_ids = MapScoresheetToTeamJudge.objects.filter(
        teamid=team_id,
        judgeid__in=active_judge_ids,
        sheetType=ScoresheetEnum.REDESIGN,
    ).values_list("scoresheetid", flat=True)
    submitted = list(
        Scoresheet.objects.filter(
            id__in=sheet_ids,
            sheetType=ScoresheetEnum.REDESIGN,
            isSubmitted=True,
        ).values_list("field1", "field2")
    )
    if not submitted:
        return (0.0, 0.0)
    count = len(submitted)
    return (
        sum(_numeric(field1) for field1, _ in submitted) / count,
        sum(_numeric(field2) for _, field2 in submitted) / count,
    )


def sort_by_redesign_tiebreakers(teams, contest_id):
    teams = list(teams)
    category_scores = {
        team.id: _redesign_tiebreak_scores(team.id, contest_id)
        for team in teams
    }
    return sorted(
        teams,
        key=lambda team: (
            _is_disqualified(team),
            -_numeric(team.redesign_score),
            -category_scores[team.id][0],
            -category_scores[team.id][1],
            team.id,
        ),
    )


def _compute_totals_for_team(team: Teams, contest_id: int = None):
    """Compute totals and averages for a given team."""

    # 1) Start with: all scoresheets mapped to this team
    base_qs = MapScoresheetToTeamJudge.objects.filter(teamid=team.id)

    # 2) Resolve contest_id if not passed explicitly
    if contest_id is None:
        contest_mapping = MapContestToTeam.objects.filter(teamid=team.id).first()
        contest_id = contest_mapping.contestid if contest_mapping else None

    # 3) If we can figure out "active judges for this contest", filter to those
    if contest_id:
        # Clusters currently attached to this contest (e.g. championship cluster gets removed on undo)
        cluster_judge_ids = set(
            judge_cluster_assignments_for_contest(contest_id)
            .values_list("judgeid", flat=True)
        )
        contest_judge_ids = set(MapContestToJudge.objects.filter(
            contestid=contest_id
        ).values_list("judgeid", flat=True))
        active_judge_ids = cluster_judge_ids | contest_judge_ids

        if active_judge_ids:
            # Use only scores from active judges
            score_map = base_qs.filter(judgeid__in=active_judge_ids)
        else:
            # With an explicit contest context, unassigned sheets may belong to
            # another contest that shares this team and must not be counted.
            score_map = base_qs.none()
    else:
        # No contest context → use all scoresheets for this team
        score_map = base_qs


    
    # ALL teams should be processed for preliminary results first
    # Then additional processing for championship/redesign if applicable
    is_championship_round = team.advanced_to_championship
    
    # Check if team has redesign scoresheets to determine if it's a redesign round
    has_redesign_sheets = any(
        Scoresheet.objects.get(id=mapping.scoresheetid).sheetType == ScoresheetEnum.REDESIGN
        for mapping in score_map
        if Scoresheet.objects.filter(id=mapping.scoresheetid).exists()
    )
    is_redesign_round = not team.advanced_to_championship and has_redesign_sheets
    

    # Separate totals for preliminary and championship
    preliminary_totals = [0] * 12  # For preliminary scoresheets
    championship_totals = [0] * 12  # For championship scoresheets

    for mapping in score_map:
        try:
            sheet = Scoresheet.objects.get(id=mapping.scoresheetid)
        except Scoresheet.DoesNotExist:
            continue
        
        if not sheet.isSubmitted:
            continue
            

        # For redesign rounds, process both redesign and preliminary scoresheets
        # (teams can have both types of scoresheets)
        if is_redesign_round and sheet.sheetType == ScoresheetEnum.REDESIGN:
            # Process redesign scoresheet (handled later in the elif chain)
            pass
        elif is_redesign_round and sheet.sheetType not in [ScoresheetEnum.PRESENTATION, ScoresheetEnum.JOURNAL, ScoresheetEnum.MACHINEDESIGN, ScoresheetEnum.RUNPENALTIES, ScoresheetEnum.OTHERPENALTIES]:
            # Skip non-preliminary, non-redesign scoresheets for redesign teams
            continue

        if sheet.sheetType == ScoresheetEnum.PRESENTATION:
            preliminary_totals[0] += sum(getattr(sheet, f"field{i}", 0) for i in range(1, 9))
            preliminary_totals[1] += 1
        elif sheet.sheetType == ScoresheetEnum.JOURNAL:
            preliminary_totals[2] += sum(getattr(sheet, f"field{i}", 0) for i in range(1, 9))
            preliminary_totals[3] += 1
        elif sheet.sheetType == ScoresheetEnum.MACHINEDESIGN:
            preliminary_totals[4] += sum(getattr(sheet, f"field{i}", 0) for i in range(1, 9))
            preliminary_totals[5] += 1
        elif sheet.sheetType == ScoresheetEnum.RUNPENALTIES:
            # RUNPENALTIES has 16 numeric fields: fields 1-8 and 10-17 (skip field 9 which is dummy)
            # Use abs() to ensure penalties are always treated as positive deductions
            penalty_sum = sum(
                abs(getattr(sheet, f"field{i}", 0) or 0)
                for i in range(1, 18)
                if i != 9
            )
            preliminary_totals[7] += penalty_sum
            preliminary_totals[8] += 1
        elif sheet.sheetType == ScoresheetEnum.OTHERPENALTIES:
            # Use abs() to ensure penalties are always treated as positive deductions
            preliminary_totals[6] += sum(abs(getattr(sheet, f"field{i}", 0) or 0) for i in range(1, 8))
            preliminary_totals[11] += 1  # Count of OTHERPENALTIES judges
        elif sheet.sheetType == ScoresheetEnum.REDESIGN:
            # Initialize redesign rolling totals once per team
            if not hasattr(team, '_redesign_total') or team._redesign_total is None:
                team._redesign_total = 0
                team._redesign_judge_count = 0
            # Include all seven rubric categories, including Communication.
            team._redesign_total += sum((getattr(sheet, f"field{i}", 0) or 0) for i in range(1, 8))
            team._redesign_judge_count += 1

        elif sheet.sheetType == ScoresheetEnum.CHAMPIONSHIP:
            # Championship scoresheets: always process championship scoresheets
            
            # Accumulate scores for averaging (like preliminary round)
            # New championship structure: fields 1-9 = Machine Design, fields 10-18 = Presentation
            # Machine Design fields 1-8 (field9 is CharField for comments, so skip it)
            machine_design_score = sum(getattr(sheet, f"field{i}", 0) or 0 for i in range(1, 9))  # Machine Design (fields 1-8)
            championship_totals[0] += machine_design_score
            championship_totals[1] += 1  # Count of machine design judges
            
            # Presentation fields 10-17 (field18 is CharField for comments, so skip it)
            presentation_score = sum(getattr(sheet, f"field{i}", 0) or 0 for i in range(10, 18))  # Presentation (fields 10-17)
            championship_totals[2] += presentation_score
            championship_totals[3] += 1  # Count of presentation judges
            
            # Championship penalties: separate general (19-25) and run (26-42) penalties
            # Use abs() to ensure penalties are always treated as positive deductions
            general_penalties_score = sum(abs(getattr(sheet, f"field{i}", 0) or 0) for i in range(19, 26))  # General Penalties (fields 19-25)
            run_penalties_score = sum(abs(getattr(sheet, f"field{i}", 0) or 0) for i in range(26, 43))  # Run Penalties (fields 26-42)
            total_penalties_score = general_penalties_score + run_penalties_score
            
            championship_totals[6] += general_penalties_score  # Store general penalties in index 6
            championship_totals[7] += run_penalties_score      # Store run penalties in index 7
            championship_totals[8] += 1  # Count submitted penalty sheets

    # compute averages and totals based on round type
    # Check if team is in championship or redesign cluster
    team_clusters = MapClusterToTeam.objects.filter(teamid=team.id)
    is_championship_round = False
    is_redesign_round = False
    
    for mapping in team_clusters:
        try:
            cluster = JudgeClusters.objects.get(id=mapping.clusterid)
            if cluster.cluster_type == 'championship':
                is_championship_round = True
            elif cluster.cluster_type == 'redesign':
                is_redesign_round = True
        except JudgeClusters.DoesNotExist:
            continue
    
    # ALWAYS calculate preliminary scores for ALL teams first
    team.presentation_score = round(qdiv(preliminary_totals[0], preliminary_totals[1]), 2)
    team.journal_score = round(qdiv(preliminary_totals[2], preliminary_totals[3]), 2)
    team.machinedesign_score = round(qdiv(preliminary_totals[4], preliminary_totals[5]), 2)
    team.preliminary_journal_score = team.journal_score  
    team.preliminary_presentation_score = team.presentation_score  
    team.preliminary_machinedesign_score = team.machinedesign_score  

    # Separate judging groups may each record the same team's penalties. The
    # official rule is to average submitted penalty sheets, just like scores.
    team.preliminary_penalties_score = round(
        qdiv(preliminary_totals[6], preliminary_totals[11]), 2
    )
    team.penalties_score = round(
        qdiv(preliminary_totals[7], preliminary_totals[8]), 2
    )
    
    
    # Total penalties for calculation (both types combined)
    total_penalties = team.preliminary_penalties_score + team.penalties_score
    preliminary_total = (
        team.preliminary_presentation_score + team.preliminary_journal_score + team.preliminary_machinedesign_score
    ) - total_penalties
    
    # Store preliminary total score (rounded)
    team.preliminary_total_score = round(preliminary_total, 2)
    
    # Set total_score to preliminary_total by default
    team.total_score = team.preliminary_total_score

    if is_championship_round:
        # Championship round: journal from preliminary + championship score
        
        # Then calculate championship scores
        
        team.championship_machinedesign_score = round(qdiv(championship_totals[0], championship_totals[1]) if championship_totals[1] > 0 else 0, 2)  # Average machine design score
        team.championship_presentation_score = round(qdiv(championship_totals[2], championship_totals[3]) if championship_totals[3] > 0 else 0, 2)  # Average presentation score
        
        # Store separate penalty scores for championship
        team.championship_general_penalties_score = round(
            qdiv(championship_totals[6], championship_totals[8]), 2
        )
        team.championship_run_penalties_score = round(
            qdiv(championship_totals[7], championship_totals[8]), 2
        )
        team.championship_penalties_score = round(
            team.championship_general_penalties_score
            + team.championship_run_penalties_score,
            2,
        )
        
        # Championship total = machine design + presentation + preliminary journal - total penalties
        journal_score = team.preliminary_journal_score or 0
        championship_score = team.championship_machinedesign_score + team.championship_presentation_score
        team.total_score = round(journal_score + championship_score - team.championship_penalties_score, 2)
        team.championship_score = team.total_score  # Set championship_score to match total_score for championship rounds
        
    elif is_redesign_round:
        # Redesign is the average of all submitted judges' rubric totals.
        if hasattr(team, '_redesign_total') and team._redesign_judge_count > 0:
            team.redesign_score = round(
                qdiv(team._redesign_total, team._redesign_judge_count), 2
            )
        else:
            team.redesign_score = 0
        team.total_score = team.redesign_score
    else:
        
        pass
    
    team.save()


def set_team_rank(data):
    """Set preliminary rank by preliminary_total_score for ALL teams in the contest."""
    contest_team_ids = MapContestToTeam.objects.filter(contestid=data["contestid"])
    contestteams = []
    for mapping in contest_team_ids:
        try:
            t = Teams.objects.get(id=mapping.teamid)
            contestteams.append(t)
        except Teams.DoesNotExist:
            continue

    # Sort by preliminary_total_score for preliminary ranking
    contestteams = sort_by_standard_round_tiebreakers(contestteams)
    for rank, team in enumerate(contestteams, start=1):
        team.team_rank = rank
        team.save()


def set_cluster_rank(data):
    """Set per-cluster rank by total_score for eligible teams."""
    cluster_team_ids = MapClusterToTeam.objects.filter(clusterid=data["clusterid"])
    if data.get("contestid") is not None:
        contest_team_ids = MapContestToTeam.objects.filter(
            contestid=data["contestid"]
        ).values_list("teamid", flat=True)
        cluster_team_ids = cluster_team_ids.filter(teamid__in=contest_team_ids)
    clusterteams = []
    for mapping in cluster_team_ids:
        try:
            t = Teams.objects.get(id=mapping.teamid)
            clusterteams.append(t)
        except Teams.DoesNotExist:
            continue

    clusterteams = sort_by_standard_round_tiebreakers(clusterteams)
    for rank, team in enumerate(clusterteams, start=1):
        team.cluster_rank = rank
        team.save()


def set_redesign_rank(contest_id):
    """Set redesign-specific rank by redesign_score for teams in redesign clusters only."""
    # Get all redesign clusters
    redesign_clusters = JudgeClusters.objects.filter(cluster_type='redesign')
    redesign_teams = []
    
    for cluster in redesign_clusters:
        # Get teams in this redesign cluster
        cluster_team_ids = MapClusterToTeam.objects.filter(clusterid=cluster.id)
        for team_mapping in cluster_team_ids:
            try:
                team = Teams.objects.get(id=team_mapping.teamid)
                # Only include teams from this specific contest
                contest_mapping = MapContestToTeam.objects.filter(teamid=team.id, contestid=contest_id)
                if contest_mapping.exists():
                    redesign_teams.append(team)
            except Teams.DoesNotExist:
                continue

    # Sort by redesign_score instead of total_score
    # A team should appear only once even if legacy data maps it to more than
    # one redesign cluster. Stable ID fallback makes ties repeatable.
    redesign_teams = list({team.id: team for team in redesign_teams}.values())
    redesign_teams = sort_by_redesign_tiebreakers(redesign_teams, contest_id)
    
    for rank, team in enumerate(redesign_teams, start=1):
        team.team_rank = rank
        team.save()


def set_championship_rank(contest_id):
    """Set championship rankings for teams that advanced to championship for a specific contest."""
    contest_team_ids = MapContestToTeam.objects.filter(contestid=contest_id)
    championship_teams = []
    for mapping in contest_team_ids:
        try:
            t = Teams.objects.get(id=mapping.teamid)
            if t.advanced_to_championship:
                championship_teams.append(t)
        except Teams.DoesNotExist:
            continue

    # Sort championship teams by total_score and set rankings
    championship_teams = sort_by_standard_round_tiebreakers(
        championship_teams, championship=True
    )
    for rank, team in enumerate(championship_teams, start=1):
        team.championship_rank = rank
        team.save()


def _ensure_requester_is_organizer_of_contest(user, contest_id: int):
    """Allow only organizers mapped to this contest."""
    organizer_ids_for_user = list(
        MapUserToRole.objects.filter(
            uuid=user.id, role=MapUserToRole.RoleEnum.ORGANIZER
        ).values_list("relatedid", flat=True)
    )
    return MapContestToOrganizer.objects.filter(
        contestid=contest_id, organizerid__in=organizer_ids_for_user
    ).exists()


def recompute_totals_and_ranks(contest_id: int):
    """Recompute all teams' totals for a contest, then reapply cluster & contest ranks."""
    with transaction.atomic():
        # Lock the contest and its teams in a stable order. Concurrent score
        # submissions then wait instead of interleaving totals and rankings.
        Contest.objects.select_for_update().get(id=contest_id)
        team_ids = list(
            MapContestToTeam.objects.filter(contestid=contest_id)
            .order_by("teamid")
            .values_list("teamid", flat=True)
        )
        teams = list(
            Teams.objects.select_for_update().filter(id__in=team_ids).order_by("id")
        )

        for team in teams:
            _compute_totals_for_team(team, contest_id)
            team.save()

        for mapping in MapContestToCluster.objects.filter(contestid=contest_id):
            set_cluster_rank({"clusterid": mapping.clusterid, "contestid": contest_id})
        set_team_rank({"contestid": contest_id})
        set_championship_rank(contest_id)
        set_redesign_rank(contest_id)


# ---------- Endpoints ----------

@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def tabulate_scores(request):
    """Recompute totals and ranks for all teams."""
    contest_id = request.data.get("contestid")
    if not contest_id:
        return Response({"detail": "contestid is required"}, status=400)

    if not _ensure_requester_is_organizer_of_contest(request.user, contest_id):
        return Response(
            {"detail": "Organizer of this contest required."}, status=status.HTTP_403_FORBIDDEN
        )

    try:
        recompute_totals_and_ranks(contest_id)
        return Response(status=200)
    except Exception:
        transaction.set_rollback(True)
        logger.exception("Could not tabulate scores for contest %s", contest_id)
        return Response(
            {"detail": "Could not update contest results. No changes were saved; please try again or contact support."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def preliminary_results(request):
    """
    show ranked results per cluster.
    Organizers will choose advancers using set_advancers().
    Body: { "contestid": <int> }
    """
    contest_id = request.data.get("contestid")
    if not contest_id:
        return Response({"ok": False, "message": "contestid is required."}, status=status.HTTP_400_BAD_REQUEST)

    if not _ensure_requester_is_organizer_of_contest(request.user, contest_id):
        return Response(
            {"ok": False, "message": "Organizer of this contest required."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # recompute + apply ranks
    recompute_totals_and_ranks(contest_id)

    response_clusters = []
    contest_team_ids = MapContestToTeam.objects.filter(
        contestid=contest_id
    ).values_list("teamid", flat=True)
    for cm in MapContestToCluster.objects.filter(contestid=contest_id):
        # Every contest receives an internal "All Teams" cluster at creation.
        # It is useful for setup, but its members are also assigned to their
        # actual preliminary clusters. Including it in standings duplicates
        # every team's result.
        cluster = JudgeClusters.objects.filter(id=cm.clusterid).first()
        if cluster and cluster.cluster_name.strip().lower() == "all teams":
            continue

        # teams in this cluster
        team_maps = MapClusterToTeam.objects.filter(
            clusterid=cm.clusterid,
            teamid__in=contest_team_ids,
        )
        cluster_teams = []
        for m in team_maps:
            try:
                cluster_teams.append(Teams.objects.get(id=m.teamid))
            except Teams.DoesNotExist:
                continue

        ordered = sort_by_standard_round_tiebreakers(cluster_teams)
        response_clusters.append({
            "cluster_id": cm.clusterid,
            "teams": [
                {
                    "team_id": t.id,
                    "team_name": t.team_name,
                    "total": float(t.total_score or 0.0),
                    "cluster_rank": int(t.cluster_rank) if t.cluster_rank else None,
                    "advanced": bool(t.advanced_to_championship),
                }
                for t in ordered
            ]
        })

    return Response({"ok": True, "message": "Preliminary standings computed.", "data": response_clusters}, status=status.HTTP_200_OK)


@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def set_advancers(request):
    """
    Organizers pick which teams advance to CHAMPIONSHIP (single pool later).
    Body: { "contestid": <int>, "team_ids": [1,2,3,...] }  (IDs that ADVANCE)
    requester must be an organizer of this contest.
    Behavior:
      - All teams in the contest are set advanced_to_championship=False
      - Provided team_ids are set to True
      - Clears previous championship_rank (if any)
    """
    contest_id = request.data.get("contestid")
    team_ids = request.data.get("team_ids")

    if not contest_id:
        return Response({"ok": False, "message": "contestid is required"}, status=400)
    if not isinstance(team_ids, list):
        return Response({"ok": False, "message": "team_ids must be a list of ints"}, status=400)
    if any(not isinstance(team_id, int) or isinstance(team_id, bool) or team_id <= 0 for team_id in team_ids):
        return Response(
            {"ok": False, "message": "team_ids must contain only positive integers"},
            status=400,
        )

    if not _ensure_requester_is_organizer_of_contest(request.user, contest_id):
        return Response({"ok": False, "message": "Organizer of this contest required."}, status=403)

    # Limit changes to teams actually in the contest
    contest_team_ids = list(
        MapContestToTeam.objects.filter(contestid=contest_id).values_list("teamid", flat=True)
    )

    # Validate the complete request before changing existing advancement choices.
    disqualified_ids = set(Teams.objects.filter(
        id__in=contest_team_ids
    ).filter(
        Q(judge_disqualified=True) | Q(organizer_disqualified=True)
    ).values_list("id", flat=True))
    invalid_disqualified = [tid for tid in team_ids if tid in disqualified_ids]
    if invalid_disqualified:
        return Response(
            {
                "ok": False,
                "message": "Disqualified teams cannot advance to the championship round.",
                "team_ids": invalid_disqualified,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Reset only after validation, so a rejected request cannot erase the
    # contest's existing advancers.
    Teams.objects.filter(id__in=contest_team_ids).update(advanced_to_championship=False, championship_rank=None)

    # Set selected advancers (intersection safety).
    valid_selection = [tid for tid in team_ids if tid in contest_team_ids]
    Teams.objects.filter(id__in=valid_selection).update(advanced_to_championship=True)

    # Return summary
    advancers = list(
        Teams.objects.filter(id__in=contest_team_ids, advanced_to_championship=True)
            .values("id", "team_name")
            .order_by("id")
    )
    return Response({"ok": True, "advanced_count": len(advancers), "advanced": advancers}, status=200)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def list_advancers(request):
    """
    Convenience endpoint to list current advancers for a contest.
    Query: ?contestid=<int>
    """
    try:
        contest_id = int(request.GET.get("contestid"))
    except Exception:
        return Response({"ok": False, "message": "contestid is required as query param"}, status=400)

    contest_team_ids = list(
        MapContestToTeam.objects.filter(contestid=contest_id).values_list("teamid", flat=True)
    )
    advancers = list(
        Teams.objects.filter(id__in=contest_team_ids, advanced_to_championship=True)
            .values("id", "team_name")
            .order_by("id")
    )
    return Response({"ok": True, "advanced_count": len(advancers), "advanced": advancers}, status=200)


@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def championship_results(request):
    """ get championship results - ranked by total_score """
    contest_id = request.GET.get("contestid")
    if not contest_id:
        return Response({"ok": False, "message": "contestid is required."}, status=status.HTTP_400_BAD_REQUEST)

    if not _ensure_requester_is_organizer_of_contest(request.user, contest_id):
        return Response(
            {"ok": False, "message": "Organizer of this contest required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    #get championship results
    team_ids = MapContestToTeam.objects.filter(contestid=contest_id).values_list("teamid", flat=True)
    championship_teams = list(Teams.objects.filter(
        id__in=list(team_ids),
        advanced_to_championship=True
    ))
    championship_teams = sort_by_standard_round_tiebreakers(
        championship_teams, championship=True
    )

    results = []
    for i, team in enumerate(championship_teams, 1):
        results.append({
            "id": team.id,
            "team_name": team.team_name,
            "school": getattr(team, 'school', '') or getattr(team, 'school_name', ''),
            "team_rank": i,
            "journal_score": float(team.preliminary_journal_score or 0.0),  # From preliminary
            "presentation_score": float(team.championship_presentation_score or 0.0),  # From championship
            "machinedesign_score": float(team.championship_machinedesign_score or 0.0),  # From championship
            "penalties_score": float(team.championship_penalties_score or 0.0),  # From championship (total)
            "championship_general_penalties_score": float(team.championship_general_penalties_score or 0.0),  # General penalties
            "championship_run_penalties_score": float(team.championship_run_penalties_score or 0.0),  # Run penalties
            "total_score": float(team.total_score or 0.0),  # Combined
            "is_championship": True
        })
    
    return Response({"ok": True, "data": results}, status=200)

@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def redesign_results(request):
    """ get redesign results - ranked by total_score """
    contest_id = request.GET.get("contestid")
    if not contest_id:
        return Response({"ok": False, "message": "contestid is required."}, status=status.HTTP_400_BAD_REQUEST)

    if not _ensure_requester_is_organizer_of_contest(request.user, contest_id):
        return Response(
            {"ok": False, "message": "Organizer of this contest required."},
            status=status.HTTP_403_FORBIDDEN,
        )

    redesign_cluster_ids = MapContestToCluster.objects.filter(
        contestid=contest_id,
        clusterid__in=JudgeClusters.objects.filter(
            cluster_type="redesign"
        ).values_list("id", flat=True),
    ).values_list("clusterid", flat=True)
    team_ids = MapClusterToTeam.objects.filter(
        clusterid__in=redesign_cluster_ids
    ).values_list("teamid", flat=True)
    redesign_teams = list(Teams.objects.filter(
        id__in=list(team_ids)
    ).distinct())
    redesign_teams = sort_by_redesign_tiebreakers(redesign_teams, contest_id)

    results = []
    for i, team in enumerate(redesign_teams, 1):
        results.append({
            "id": team.id,
            "team_name": team.team_name,
            "school": getattr(team, 'school', '') or getattr(team, 'school_name', ''),
            "team_rank": i,  # Redesign rank
            "total_score": float(team.total_score or 0.0),
            "redesign_score": float(team.redesign_score or 0.0),
            "is_redesign": True
        })
    
    return Response({"ok": True, "data": results}, status=200)
