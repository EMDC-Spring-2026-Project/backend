from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User

from ..models import (
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
    Judge,
)

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
        contest_cluster_ids = MapContestToCluster.objects.filter(
            contestid=contest_id
        ).values_list("clusterid", flat=True)

        # Judges still mapped into those clusters
        active_judge_ids = MapJudgeToCluster.objects.filter(
            clusterid__in=contest_cluster_ids
        ).values_list("judgeid", flat=True).distinct()

        if active_judge_ids:
            # Use only scores from active judges
            score_map = base_qs.filter(judgeid__in=active_judge_ids)
        else:
            # No active judge info → fall back to all scoresheets for this team
            score_map = base_qs
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
            # Sum all redesign fields (1..6) and count judges
            team._redesign_total += sum((getattr(sheet, f"field{i}", 0) or 0) for i in range(1, 7))
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

    # Penalties should be summed (not averaged) because each penalty represents a specific deduction
    team.preliminary_penalties_score = round(preliminary_totals[6], 2)  # Total OTHERPENALTIES (not averaged)
    team.penalties_score = round(preliminary_totals[7], 2)  # Total RUNPENALTIES (not averaged)
    
    
    # Total penalties for calculation (both types combined)
    total_penalties = preliminary_totals[6] + preliminary_totals[7]
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
        team.championship_general_penalties_score = round(championship_totals[6], 2)  # General penalties (fields 19-25)
        team.championship_run_penalties_score = round(championship_totals[7], 2)      # Run penalties (fields 26-42)
        team.championship_penalties_score = round(championship_totals[6] + championship_totals[7], 2)  # Total penalties for calculation
        
        # Championship total = machine design + presentation + preliminary journal - total penalties
        journal_score = team.preliminary_journal_score or 0
        championship_score = team.championship_machinedesign_score + team.championship_presentation_score
        team.total_score = round(journal_score + championship_score - team.championship_penalties_score, 2)
        team.championship_score = team.total_score  # Set championship_score to match total_score for championship rounds
        
    elif is_redesign_round:
        # Use summed redesign total only (no per-section fields, no averaging)
        if hasattr(team, '_redesign_total') and team._redesign_judge_count > 0:
            team.redesign_score = round(team._redesign_total, 2)
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
            if not t.organizer_disqualified:
                contestteams.append(t)
        except Teams.DoesNotExist:
            continue

    # Sort by preliminary_total_score for preliminary ranking
    contestteams.sort(key=lambda x: x.preliminary_total_score or 0, reverse=True)
    for rank, team in enumerate(contestteams, start=1):
        team.team_rank = rank
        team.save()


def set_cluster_rank(data):
    """Set per-cluster rank by total_score for eligible teams."""
    cluster_team_ids = MapClusterToTeam.objects.filter(clusterid=data["clusterid"])
    clusterteams = []
    for mapping in cluster_team_ids:
        try:
            t = Teams.objects.get(id=mapping.teamid)
            if not t.organizer_disqualified:
                clusterteams.append(t)
        except Teams.DoesNotExist:
            continue

    clusterteams.sort(key=lambda x: x.total_score, reverse=True)
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
                if contest_mapping.exists() and not team.organizer_disqualified:
                    redesign_teams.append(team)
            except Teams.DoesNotExist:
                continue

    # Sort by redesign_score instead of total_score
    redesign_teams.sort(key=lambda x: x.redesign_score or 0, reverse=True)
    
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
            if not t.organizer_disqualified and t.advanced_to_championship:
                championship_teams.append(t)
        except Teams.DoesNotExist:
            continue

    # Sort championship teams by total_score and set rankings
    championship_teams.sort(key=lambda x: x.total_score, reverse=True)
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
    contest_team_ids = MapContestToTeam.objects.filter(contestid=contest_id)
    teams = []
    for m in contest_team_ids:
        try:
            teams.append(Teams.objects.get(id=m.teamid))
        except Teams.DoesNotExist:
            continue

    # Compute totals and save all teams in one batch operation
    for t in teams:
        _compute_totals_for_team(t, contest_id)
        t.save()  # Save each team after computation

    for m in MapContestToCluster.objects.filter(contestid=contest_id):
        set_cluster_rank({"clusterid": m.clusterid})
    set_team_rank({"contestid": contest_id})

    # Set championship rankings for teams in championship clusters
    set_championship_rank(contest_id)

    # Set redesign rankings for redesign teams only
    set_redesign_rank(contest_id)


# ---------- Endpoints ----------

@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
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
    except Exception as e:
        return Response({"error": str(e)}, status=500)

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
    for cm in MapContestToCluster.objects.filter(contestid=contest_id):
        # Every contest receives an internal "All Teams" cluster at creation.
        # It is useful for setup, but its members are also assigned to their
        # actual preliminary clusters. Including it in standings duplicates
        # every team's result.
        cluster = JudgeClusters.objects.filter(id=cm.clusterid).first()
        if cluster and cluster.cluster_name.strip().lower() == "all teams":
            continue

        # teams in this cluster
        team_maps = MapClusterToTeam.objects.filter(clusterid=cm.clusterid)
        cluster_teams = []
        for m in team_maps:
            try:
                cluster_teams.append(Teams.objects.get(id=m.teamid))
            except Teams.DoesNotExist:
                continue

        ordered = sort_by_score_with_id_fallback(cluster_teams, "total_score")
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

    if not _ensure_requester_is_organizer_of_contest(request.user, contest_id):
        return Response({"ok": False, "message": "Organizer of this contest required."}, status=403)

    # Limit changes to teams actually in the contest
    contest_team_ids = list(
        MapContestToTeam.objects.filter(contestid=contest_id).values_list("teamid", flat=True)
    )

    # reset everyone in contest
    Teams.objects.filter(id__in=contest_team_ids).update(advanced_to_championship=False, championship_rank=None)

    # set selected advancers (intersection safety)
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
    championship_teams = Teams.objects.filter(
        id__in=list(team_ids),
        advanced_to_championship=True
    ).order_by('-total_score', 'id')

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
    redesign_teams = Teams.objects.filter(
        id__in=list(team_ids)
    ).distinct().order_by('-redesign_score', 'id')

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
