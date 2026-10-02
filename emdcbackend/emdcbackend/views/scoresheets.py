from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from .Maps.MapScoreSheet import delete_score_sheet_mapping
from ..models import Scoresheet, Teams, Judge, MapClusterToTeam, MapScoresheetToTeamJudge, MapJudgeToCluster, ScoresheetEnum, Contest, MapContestToTeam, MapContestToCluster, MapContestToOrganizer, MapUserToRole
from ..serializers import ScoresheetSerializer, MapScoreSheetToTeamJudgeSerializer


def _can_edit_scoresheet(user, scoresheet):
    """Allow only the assigned judge, the contest organizer, or an administrator."""
    if user.is_superuser:
        return True

    role_mappings = MapUserToRole.objects.filter(uuid=user.id)
    if role_mappings.filter(role=MapUserToRole.RoleEnum.ADMIN).exists():
        return True

    score_mappings = MapScoresheetToTeamJudge.objects.filter(scoresheetid=scoresheet.id)
    judge_ids = role_mappings.filter(
        role=MapUserToRole.RoleEnum.JUDGE
    ).values_list("relatedid", flat=True)
    if score_mappings.filter(judgeid__in=judge_ids).exists():
        return True

    organizer_ids = list(role_mappings.filter(
        role=MapUserToRole.RoleEnum.ORGANIZER
    ).values_list("relatedid", flat=True))
    team_ids = score_mappings.values_list("teamid", flat=True)
    contest_ids = set(MapContestToTeam.objects.filter(
        teamid__in=team_ids
    ).values_list("contestid", flat=True))
    if not organizer_ids or not contest_ids:
        return False
    managed_contest_ids = set(MapContestToOrganizer.objects.filter(
        contestid__in=contest_ids, organizerid__in=organizer_ids
    ).values_list("contestid", flat=True))
    return contest_ids.issubset(managed_contest_ids)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def scores_by_id(request, scores_id):
    scores = get_object_or_404(Scoresheet, id=scores_id)
    if not _can_edit_scoresheet(request.user, scores):
        return Response({"detail": "You cannot view this scoresheet."}, status=status.HTTP_403_FORBIDDEN)
    serializer = ScoresheetSerializer(instance=scores)
    return Response({"ScoreSheet": serializer.data}, status=status.HTTP_200_OK)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_score_sheet(request):
    map_data = request.data
    result = create_score_sheet_helper(map_data)
    if "errors" in result:
        return Response(result["errors"], status=status.HTTP_400_BAD_REQUEST)
    return Response(result, status=status.HTTP_201_CREATED)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_score_sheet(request):
    try:
        scores = get_object_or_404(Scoresheet, id=request.data["id"])
        if not _can_edit_scoresheet(request.user, scores):
            return Response({"detail": "You cannot edit this scoresheet."}, status=status.HTTP_403_FORBIDDEN)
        scores.sheetType = request.data["sheetType"]
        scores.isSubmitted = request.data["isSubmitted"]
        
        if scores.sheetType == ScoresheetEnum.OTHERPENALTIES:
            scores.field1 = request.data.get("field1", 0)
            scores.field2 = request.data.get("field2", 0)
            scores.field3 = request.data.get("field3", 0)
            scores.field4 = request.data.get("field4", 0)
            scores.field5 = request.data.get("field5", 0)
            scores.field6 = request.data.get("field6", 0)
            scores.field7 = request.data.get("field7", 0)
        elif scores.sheetType == ScoresheetEnum.REDESIGN:
            scores.field1 = request.data.get("field1", 0)
            scores.field2 = request.data.get("field2", 0)
            scores.field3 = request.data.get("field3", 0)
            scores.field4 = request.data.get("field4", 0)
            scores.field5 = request.data.get("field5", 0)
            scores.field6 = request.data.get("field6", 0)
            scores.field7 = request.data.get("field7", 0)
            scores.field9 = request.data.get("field9", "")
        elif scores.sheetType == ScoresheetEnum.CHAMPIONSHIP:
            # Championship scoresheets: fields 1-42
            # Fields 1-8: Machine Design
            # Field 9: Machine Design comment
            # Fields 10-17: Presentation  
            # Field 18: Presentation comment
            # Fields 19-25: General Penalties
            # Fields 26-42: Run Penalties
            for i in range(1, 43):
                if i == 9 or i == 18:
                    # Comment fields
                    scores.__setattr__(f"field{i}", request.data.get(f"field{i}", ""))
                else:
                    # Score/penalty fields
                    scores.__setattr__(f"field{i}", request.data.get(f"field{i}", 0))
        else:
            scores.field1 = request.data.get("field1", 0)
            scores.field2 = request.data.get("field2", 0)
            scores.field3 = request.data.get("field3", 0)
            scores.field4 = request.data.get("field4", 0)
            scores.field5 = request.data.get("field5", 0)
            scores.field6 = request.data.get("field6", 0)
            scores.field7 = request.data.get("field7", 0)
            scores.field8 = request.data.get("field8", 0)
            scores.field9 = request.data.get("field9", "")
            if scores.sheetType == ScoresheetEnum.RUNPENALTIES:
                scores.field10 = request.data.get("field10", 0)
                scores.field11 = request.data.get("field11", 0)
                scores.field12 = request.data.get("field12", 0)
                scores.field13 = request.data.get("field13", 0)
                scores.field14 = request.data.get("field14", 0)
                scores.field15 = request.data.get("field15", 0)
                scores.field16 = request.data.get("field16", 0)
                scores.field17 = request.data.get("field17", 0)
        scores.save()
        
        # Trigger tabulation recalculation asynchronously for all scoresheet types when submitted
        if scores.isSubmitted:
            try:
                # Get the team ID from the mapping
                team_mapping = MapScoresheetToTeamJudge.objects.filter(scoresheetid=scores.id).first()
                if team_mapping:
                    # Get the contest ID for this team
                    contest_mapping = MapContestToTeam.objects.filter(teamid=team_mapping.teamid).first()
                    if contest_mapping:
                        # Schedule tabulation asynchronously to avoid blocking the response
                        import threading
                        from .tabulation import recompute_totals_and_ranks
                        
                        def async_tabulation():
                            try:
                                recompute_totals_and_ranks(contest_mapping.contestid)
                            except Exception as e:
                                pass
                        
                        # Run tabulation in background thread
                        threading.Thread(target=async_tabulation, daemon=True).start()
            except Exception as tab_error:
                # Don't fail the request if tabulation fails
                pass
        
        serializer = ScoresheetSerializer(instance=scores)
        return Response({"edit_score_sheets": serializer.data})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def update_scores(request):
    try:
        scores = get_object_or_404(Scoresheet, id=request.data["id"])
        if not _can_edit_scoresheet(request.user, scores):
            return Response({"detail": "You cannot edit this scoresheet."}, status=status.HTTP_403_FORBIDDEN)
        
        # Update isSubmitted field if provided
        if "isSubmitted" in request.data:
            scores.isSubmitted = request.data["isSubmitted"]
        if scores.sheetType == ScoresheetEnum.OTHERPENALTIES:
            scores.field1 = request.data.get("field1") or 0
            scores.field2 = request.data.get("field2") or 0
            scores.field3 = request.data.get("field3") or 0
            scores.field4 = request.data.get("field4") or 0
            scores.field5 = request.data.get("field5") or 0
            scores.field6 = request.data.get("field6") or 0
            scores.field7 = request.data.get("field7") or 0
        elif scores.sheetType == ScoresheetEnum.REDESIGN:
            scores.field1 = request.data.get("field1") or 0
            scores.field2 = request.data.get("field2") or 0
            scores.field3 = request.data.get("field3") or 0
            scores.field4 = request.data.get("field4") or 0
            scores.field5 = request.data.get("field5") or 0
            scores.field6 = request.data.get("field6") or 0
            scores.field7 = request.data.get("field7") or 0
            scores.field9 = request.data.get("field9") or ""
        elif scores.sheetType == ScoresheetEnum.CHAMPIONSHIP:
            # Championship structure: fields 1-9 = Machine Design, fields 10-18 = Presentation
            # Machine Design fields 1-9 (field9 is CharField for comments)
            scores.field1 = request.data.get("field1") or 0
            scores.field2 = request.data.get("field2") or 0
            scores.field3 = request.data.get("field3") or 0
            scores.field4 = request.data.get("field4") or 0
            scores.field5 = request.data.get("field5") or 0
            scores.field6 = request.data.get("field6") or 0
            scores.field7 = request.data.get("field7") or 0
            scores.field8 = request.data.get("field8") or 0
            scores.field9 = request.data.get("field9") or ""  # Machine Design comment
            # Presentation fields 10-18
            scores.field10 = request.data.get("field10") or 0
            scores.field11 = request.data.get("field11") or 0
            scores.field12 = request.data.get("field12") or 0
            scores.field13 = request.data.get("field13") or 0
            scores.field14 = request.data.get("field14") or 0
            scores.field15 = request.data.get("field15") or 0
            scores.field16 = request.data.get("field16") or 0
            scores.field17 = request.data.get("field17") or 0
            scores.field18 = request.data.get("field18") or ""  # Presentation comment
            # Penalty fields 19-42 (General Penalties: 19-25, Run Penalties: 26-42)
            scores.field19 = request.data.get("field19") or 0
            scores.field20 = request.data.get("field20") or 0
            scores.field21 = request.data.get("field21") or 0
            scores.field22 = request.data.get("field22") or 0
            scores.field23 = request.data.get("field23") or 0
            scores.field24 = request.data.get("field24") or 0
            scores.field25 = request.data.get("field25") or 0
            scores.field26 = request.data.get("field26") or 0
            scores.field27 = request.data.get("field27") or 0
            scores.field28 = request.data.get("field28") or 0
            scores.field29 = request.data.get("field29") or 0
            scores.field30 = request.data.get("field30") or 0
            scores.field31 = request.data.get("field31") or 0
            scores.field32 = request.data.get("field32") or 0
            scores.field33 = request.data.get("field33") or 0
            scores.field34 = request.data.get("field34") or 0
            scores.field35 = request.data.get("field35") or 0
            scores.field36 = request.data.get("field36") or 0
            scores.field37 = request.data.get("field37") or 0
            scores.field38 = request.data.get("field38") or 0
            scores.field39 = request.data.get("field39") or 0
            scores.field40 = request.data.get("field40") or 0
            scores.field41 = request.data.get("field41") or 0
            scores.field42 = request.data.get("field42") or 0
        else:
            scores.field1 = request.data.get("field1") or 0
            scores.field2 = request.data.get("field2") or 0
            scores.field3 = request.data.get("field3") or 0
            scores.field4 = request.data.get("field4") or 0
            scores.field5 = request.data.get("field5") or 0
            scores.field6 = request.data.get("field6") or 0
            scores.field7 = request.data.get("field7") or 0
            scores.field8 = request.data.get("field8") or 0
            scores.field9 = request.data.get("field9") or ""
            if scores.sheetType == ScoresheetEnum.RUNPENALTIES:
                scores.field10 = request.data.get("field10") or 0
                scores.field11 = request.data.get("field11") or 0
                scores.field12 = request.data.get("field12") or 0
                scores.field13 = request.data.get("field13") or 0
                scores.field14 = request.data.get("field14") or 0
                scores.field15 = request.data.get("field15") or 0
                scores.field16 = request.data.get("field16") or 0
                scores.field17 = request.data.get("field17") or 0
            
        scores.save()
        
        # Reload from database to verify save
        scores.refresh_from_db()
        
        serializer = ScoresheetSerializer(instance=scores)
        
        # If this is a championship scoresheet submission, trigger tabulation recalculation asynchronously
        if scores.sheetType == ScoresheetEnum.CHAMPIONSHIP and scores.isSubmitted:
            try:
                # Get the team ID from the mapping
                team_mapping = MapScoresheetToTeamJudge.objects.filter(scoresheetid=scores.id).first()
                if team_mapping:
                    # Get the contest ID for this team
                    contest_mapping = MapContestToTeam.objects.filter(teamid=team_mapping.teamid).first()
                    if contest_mapping:
                        # Schedule tabulation asynchronously to avoid blocking the response
                        import threading
                        from .tabulation import recompute_totals_and_ranks
                        
                        def async_tabulation():
                            try:
                                recompute_totals_and_ranks(contest_mapping.contestid)
                            except Exception as e:
                                pass
                        
                        # Run tabulation in background thread
                        threading.Thread(target=async_tabulation, daemon=True).start()
            except Exception as tab_error:
                # Don't fail the request if tabulation fails
                pass
        
        return Response({"updated_sheet": serializer.data})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_score_sheet_field(request):
    sheet = get_object_or_404(Scoresheet, id=request.data["id"])
    if not _can_edit_scoresheet(request.user, sheet):
        return Response({"detail": "You cannot edit this scoresheet."}, status=status.HTTP_403_FORBIDDEN)

    field_name = ""
    if isinstance(request.data["field"], int):
        field_name = "field"+str(request.data["field"])
    else:
        field_name = request.data["field"]

    if hasattr(sheet, field_name):
        setattr(sheet, field_name, request.data["new_value"])
        sheet.save()
        serializer = ScoresheetSerializer(instance=sheet)
        return Response({"score_sheet": serializer.data}, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Invalid field"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_score_sheet(request, scores_id):
    scores = get_object_or_404(Scoresheet, id=scores_id)
    if not _can_edit_scoresheet(request.user, scores):
        return Response({"detail": "You cannot edit this scoresheet."}, status=status.HTTP_403_FORBIDDEN)
    scores.delete()
    return Response({"detail": "Score Sheet deleted successfully."}, status=status.HTTP_200_OK)

def create_score_sheet_helper(map_data):
    serializer = ScoresheetSerializer(data=map_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    else:
        return {"errors": serializer.errors}


def create_base_score_sheet(sheet_type):
    base_score_data = {
        "sheetType": sheet_type,
        "isSubmitted": False,
        "field1": 0.0,
        "field2": 0.0,
        "field3": 0.0,
        "field4": 0.0,
        "field5": 0.0,
        "field6": 0.0,
        "field7": 0.0,
        "field8": 0.0,
        "field9": "",
    }

    serializer = ScoresheetSerializer(data=base_score_data)
    if serializer.is_valid():
        score_sheet = serializer.save()
        return score_sheet
    else:
        raise ValidationError(serializer.errors)

def create_base_score_sheet_runpenalties():
    base_score_data = {
        "sheetType": 4,
        "isSubmitted": False,
        "field1": 0.0,
        "field2": 0.0,
        "field3": 0.0,
        "field4": 0.0,
        "field5": 0.0,
        "field6": 0.0,
        "field7": 0.0,
        "field8": 0.0,
        "field9": "",
        "field10": 0.0,
        "field11": 0.0,
        "field12": 0.0,
        "field13": 0.0,
        "field14": 0.0,
        "field15": 0.0,
        "field16": 0.0,
        "field17": 0.0
    }

    serializer = ScoresheetSerializer(data=base_score_data)
    if serializer.is_valid():
        score_sheet = serializer.save()
        return score_sheet
    else:
        raise ValidationError(serializer.errors)

def create_base_score_sheet_otherpenalties():
    base_score_data = {
        "sheetType": 5,
        "isSubmitted": False,
        "field1": 0.0,
        "field2": 0.0,
        "field3": 0.0,
        "field4": 0.0,
        "field5": 0.0,
        "field6": 0.0,
        "field7": 0.0,
        "field9": ""
    }

    serializer = ScoresheetSerializer(data=base_score_data)
    if serializer.is_valid():
        score_sheet = serializer.save()
        return score_sheet
    else:
        raise ValidationError(serializer.errors)

def create_base_score_sheet_Redesign():
    base_score_data = {
        "sheetType": 6,
        "isSubmitted": False,
        "field1": 0.0,
        "field2": 0.0,
        "field3": 0.0,
        "field4": 0.0,
        "field5": 0.0,
        "field6": 0.0,
        "field7": 0.0,
        "field9": ""
    }

    serializer = ScoresheetSerializer(data=base_score_data)
    if serializer.is_valid():
        score_sheet = serializer.save()
        return score_sheet
    else:
        raise ValidationError(serializer.errors)

def create_base_score_sheet_Championship():
    base_score_data = {
        "sheetType": 7,
        "isSubmitted": False,
        # Machine Design fields 1-8
        "field1": 0.0, "field2": 0.0, "field3": 0.0, "field4": 0.0,
        "field5": 0.0, "field6": 0.0, "field7": 0.0, "field8": 0.0,
        # Machine Design comment field 9
        "field9": "",
        # Presentation fields 10-17
        "field10": 0.0, "field11": 0.0, "field12": 0.0, "field13": 0.0,
        "field14": 0.0, "field15": 0.0, "field16": 0.0, "field17": 0.0,
        # Presentation comment field 18
        "field18": "",
        # Penalty fields 19-42 (General Penalties: 19-25, Run Penalties: 26-42)
        "field19": 0.0, "field20": 0.0, "field21": 0.0, "field22": 0.0, "field23": 0.0, "field24": 0.0, "field25": 0.0,
        "field26": 0.0, "field27": 0.0, "field28": 0.0, "field29": 0.0, "field30": 0.0, "field31": 0.0, "field32": 0.0,
        "field33": 0.0, "field34": 0.0, "field35": 0.0, "field36": 0.0, "field37": 0.0, "field38": 0.0, "field39": 0.0,
        "field40": 0.0, "field41": 0.0, "field42": 0.0
    }

    serializer = ScoresheetSerializer(data=base_score_data)
    if serializer.is_valid():
        score_sheet = serializer.save()
        return score_sheet
    else:
        raise ValidationError(serializer.errors)

def create_sheets_for_teams_in_cluster(judge_id, cluster_id, presentation, journal, mdo, runpenalties, otherpenalties, redesign, championship):
    try:
        # Fetch all mappings for the teams in the cluster
        mappings = MapClusterToTeam.objects.filter(clusterid=cluster_id)

        # Get team_ids either from direct mappings or contest relationship
        if mappings.exists():
            # Extract all the team_ids from the direct mappings
            team_ids = mappings.values_list('teamid', flat=True)
        else:
            # Try to find teams through contest relationship
            # If cluster belongs to a contest, create scoresheets for all teams in that contest
            try:
                contest_mapping = MapContestToCluster.objects.filter(clusterid=cluster_id).first()
                if contest_mapping:
                    contest_team_mappings = MapContestToTeam.objects.filter(contestid=contest_mapping.contestid)
                    if contest_team_mappings.exists():
                        team_ids = contest_team_mappings.values_list('teamid', flat=True)
                    else:
                        return []
                else:
                    return []
            except Exception as e:
                return []

        # Fetch all teams with the given team_ids
        teams_in_cluster = Teams.objects.filter(id__in=team_ids)

        # List to store responses
        created_score_sheets = []

        for team in teams_in_cluster:
            # Check if team has advanced to championship
            team_has_advanced = getattr(team, 'advanced_to_championship', False)

            # Check for existing scoresheets to prevent duplicates
            existing_mappings = MapScoresheetToTeamJudge.objects.filter(
                teamid=team.id,
                judgeid=judge_id
            )
            if existing_mappings.exists():
                existing_types = existing_mappings.values_list('sheetType', flat=True)

            # Create scoresheets based on enabled flags - advancement status doesn't prevent scoresheet creation
            # The advancement status only affects which round the team competes in, not which scoresheets can be created
            if runpenalties:
                # Check if runpenalties scoresheet already exists
                existing_runpenalties = existing_mappings.filter(sheetType=4).exists()
                if not existing_runpenalties:
                    sheet = create_base_score_sheet_runpenalties()
                    map_data = {"teamid": team.id, "judgeid": judge_id, "scoresheetid": sheet.id, "sheetType": 4}
                    map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                    if map_serializer.is_valid():
                        map_serializer.save()
                        created_score_sheets.append({
                            "team_id": team.id,
                            "judge_id": judge_id,
                            "scoresheet_id": sheet.id,
                            "sheetType": 4
                        })
                    else:
                        raise ValidationError(map_serializer.errors)
                else:
                    pass
            if otherpenalties:
                # Check if otherpenalties scoresheet already exists
                existing_otherpenalties = existing_mappings.filter(sheetType=5).exists()
                if not existing_otherpenalties:
                    sheet = create_base_score_sheet_otherpenalties()
                    map_data = {"teamid": team.id, "judgeid": judge_id, "scoresheetid": sheet.id, "sheetType": 5}
                    map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                    if map_serializer.is_valid():
                        map_serializer.save()
                        created_score_sheets.append({
                            "team_id": team.id,
                            "judge_id": judge_id,
                            "scoresheet_id": sheet.id,
                            "sheetType": 5
                        })
                    else:
                        raise ValidationError(map_serializer.errors)
                else:
                    pass
            if presentation:
                # Check if presentation scoresheet already exists
                existing_presentation = existing_mappings.filter(sheetType=1).exists()
                if not existing_presentation:
                    sheet = create_base_score_sheet(1)
                    map_data = {"teamid": team.id, "judgeid": judge_id, "scoresheetid": sheet.id, "sheetType": 1}
                    map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                    if map_serializer.is_valid():
                        map_serializer.save()
                        created_score_sheets.append({
                            "team_id": team.id,
                            "judge_id": judge_id,
                            "scoresheet_id": sheet.id,
                            "sheetType": 1
                        })
                    else:
                        raise ValidationError(map_serializer.errors)
            if journal:
                # Check if journal scoresheet already exists
                existing_journal = existing_mappings.filter(sheetType=2).exists()
                if not existing_journal:
                    sheet = create_base_score_sheet(2)
                    map_data = {"teamid": team.id, "judgeid": judge_id, "scoresheetid": sheet.id, "sheetType": 2}
                    map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                    if map_serializer.is_valid():
                        map_serializer.save()
                        created_score_sheets.append({
                            "team_id": team.id,
                            "judge_id": judge_id,
                            "scoresheet_id": sheet.id,
                            "sheetType": 2
                        })
                    else:
                        raise ValidationError(map_serializer.errors)
            if redesign:
                # Check if redesign scoresheet already exists
                existing_redesign = existing_mappings.filter(sheetType=6).exists()
                if not existing_redesign:
                    sheet = create_base_score_sheet_Redesign()
                    map_data = {"teamid": team.id, "judgeid": judge_id, "scoresheetid": sheet.id, "sheetType": 6}
                    map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                    if map_serializer.is_valid():
                        map_serializer.save()
                        created_score_sheets.append({
                            "team_id": team.id,
                            "judge_id": judge_id,
                            "scoresheet_id": sheet.id,
                            "sheetType": 6
                        })
                    else:
                        raise ValidationError(map_serializer.errors)
                else:
                    pass
            if mdo:
                # Check if MDO scoresheet already exists
                existing_mdo = existing_mappings.filter(sheetType=3).exists()
                if not existing_mdo:
                    sheet = create_base_score_sheet(3)
                    map_data = {"teamid": team.id, "judgeid": judge_id, "scoresheetid": sheet.id, "sheetType": 3}
                    map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                    if map_serializer.is_valid():
                        map_serializer.save()
                        created_score_sheets.append({
                            "team_id": team.id,
                            "judge_id": judge_id,
                            "scoresheet_id": sheet.id,
                            "sheetType": 3
                        })
                    else:
                        raise ValidationError(map_serializer.errors)
                else:
                    pass
            if championship:
                # Check if championship scoresheet already exists
                existing_championship = existing_mappings.filter(sheetType=7).exists()
                if not existing_championship:
                    try:
                        sheet = create_base_score_sheet_Championship()
                        map_data = {"teamid": team.id, "judgeid": judge_id, "scoresheetid": sheet.id, "sheetType": 7}
                        map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                        if map_serializer.is_valid():
                            map_serializer.save()
                            created_score_sheets.append({
                                "team_id": team.id,
                                "judge_id": judge_id,
                                "scoresheet_id": sheet.id,
                                "sheetType": 7
                            })
                        else:
                            raise ValidationError(map_serializer.errors)
                    except Exception as e:
                        raise e
                else:
                    pass
            else:
                pass

        return created_score_sheets

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise ValidationError({"detail": str(e)})

def create_score_sheets_for_team(team, judges):
    created_score_sheets = []
    # Check if team has advanced to championship
    team_has_advanced = getattr(team, 'advanced_to_championship', False)
    
    for judge in judges:
        # Create score sheets for each type (Presentation, Journal, Machine Design, Penalties) based on the judge's role
        # Skip preliminary scoresheets (1-5) if team has advanced - only create championship/redesign
        if judge.presentation and not team_has_advanced:
            score_sheet = create_base_score_sheet(ScoresheetEnum.PRESENTATION)
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=score_sheet.id, sheetType=ScoresheetEnum.PRESENTATION
            )
            created_score_sheets.append(score_sheet)
        if judge.journal and not team_has_advanced:
            score_sheet = create_base_score_sheet(ScoresheetEnum.JOURNAL)
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=score_sheet.id, sheetType=ScoresheetEnum.JOURNAL
            )
            created_score_sheets.append(score_sheet)
        if judge.mdo and not team_has_advanced:
            score_sheet = create_base_score_sheet(ScoresheetEnum.MACHINEDESIGN)
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=score_sheet.id, sheetType=ScoresheetEnum.MACHINEDESIGN
            )
            created_score_sheets.append(score_sheet)
        if judge.runpenalties and not team_has_advanced:
            score_sheet = create_base_score_sheet_runpenalties()
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=score_sheet.id, sheetType=ScoresheetEnum.RUNPENALTIES
            )
            created_score_sheets.append(score_sheet)
        if judge.otherpenalties and not team_has_advanced:
            score_sheet = create_base_score_sheet_otherpenalties()
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=score_sheet.id, sheetType=ScoresheetEnum.OTHERPENALTIES
            )
            created_score_sheets.append(score_sheet)
        if judge.redesign:
            score_sheet = create_base_score_sheet_Redesign()
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=score_sheet.id, sheetType=ScoresheetEnum.REDESIGN
            )
        if judge.championship:
            score_sheet = create_base_score_sheet_Championship()
            MapScoresheetToTeamJudge.objects.create(
                teamid=team.id, judgeid=judge.id, scoresheetid=score_sheet.id, sheetType=ScoresheetEnum.CHAMPIONSHIP
            )
            created_score_sheets.append(score_sheet)
    return created_score_sheets

def create_scoresheets_for_judges_in_cluster(cluster_id):
    """
    Create scoresheets for all judges in a cluster when teams are added.
    This is called after teams are moved to championship/redesign clusters.

    IMPORTANT: Only creates scoresheets appropriate for the cluster type:
    - Championship clusters: ONLY championship scoresheets (type 7)
    - Redesign clusters: ONLY redesign scoresheets (type 6)
    - Preliminary clusters: All scoresheets based on judge flags
    """
    try:
        # Get the cluster to check its type
        from ..models import JudgeClusters
        try:
            cluster = JudgeClusters.objects.get(id=cluster_id)
            cluster_type = getattr(cluster, 'cluster_type', 'preliminary')
        except JudgeClusters.DoesNotExist:
            cluster_type = 'preliminary'

        # Get all judges in this cluster
        judge_mappings = MapJudgeToCluster.objects.filter(clusterid=cluster_id)

        # Get all teams in this cluster
        team_mappings = MapClusterToTeam.objects.filter(clusterid=cluster_id)

        if len(judge_mappings) == 0:
            return []

        if len(team_mappings) == 0:
            return []

        created_scoresheets = []

        for judge_mapping in judge_mappings:
            try:
                judge = Judge.objects.get(id=judge_mapping.judgeid)

                # Determine which scoresheets to create based on cluster type
                if cluster_type == 'championship':
                    # Championship clusters: ONLY create championship scoresheets (type 7)
                    # Do NOT create any preliminary scoresheets (1-5) or redesign (6)
                    sheets = create_sheets_for_teams_in_cluster(
                        judge.id,
                        cluster_id,
                        False,  # presentation
                        False,  # journal
                        False,  # mdo
                        False,  # runpenalties
                        False,  # otherpenalties
                        False,  # redesign
                        True    # championship ONLY
                    )
                elif cluster_type == 'redesign':
                    # Redesign clusters: ONLY create redesign scoresheets (type 6)
                    # Do NOT create any preliminary scoresheets (1-5) or championship (7)
                    sheets = create_sheets_for_teams_in_cluster(
                        judge.id,
                        cluster_id,
                        False,  # presentation
                        False,  # journal
                        False,  # mdo
                        False,  # runpenalties
                        False,  # otherpenalties
                        True,   # redesign ONLY
                        False   # championship
                    )
                else:
                    # Preliminary clusters: create all scoresheets based on judge flags
                    sheets = create_sheets_for_teams_in_cluster(
                        judge.id,
                        cluster_id,
                        judge.presentation,
                        judge.journal,
                        judge.mdo,
                        judge.runpenalties,
                        judge.otherpenalties,
                        judge.redesign,
                        judge.championship
                    )

                created_scoresheets.extend(sheets)

            except Judge.DoesNotExist:
                continue
            except Exception as e:
                continue

        return created_scoresheets

    except Exception as e:
        raise ValidationError({"detail": str(e)})

def get_scoresheet_id(judge_id, team_id, scoresheet_type):
    try:
        mapping = MapScoresheetToTeamJudge.objects.get(judgeid=judge_id, teamid=team_id, sheetType=scoresheet_type)
        scoresheet = Scoresheet.objects.get(id=mapping.scoresheetid)
        return scoresheet.id
    except Scoresheet.DoesNotExist:
        raise ValidationError({"error": "No scoresheet found"})

def delete_sheets_for_teams_in_cluster(judge_id, cluster_id, presentation, journal, mdo, runpenalties, otherpenalties, redesign, championship):
    """
    Delete scoresheets for a judge in a cluster based on the flags provided.
    Only deletes scoresheet types that match the flags to preserve scoresheets from other cluster types.
    """
    try:
        cluster_team_mappings = MapClusterToTeam.objects.filter(clusterid=cluster_id)
        
        if cluster_team_mappings.exists():
            team_ids = list(cluster_team_mappings.values_list('teamid', flat=True))
        else:
            try:
                contest_mapping = MapContestToCluster.objects.filter(clusterid=cluster_id).first()
                if contest_mapping:
                    contest_team_mappings = MapContestToTeam.objects.filter(contestid=contest_mapping.contestid)
                    if contest_team_mappings.exists():
                        team_ids = list(contest_team_mappings.values_list('teamid', flat=True))
                    else:
                        return
                else:
                    return
            except Exception:
                return
        
        if not team_ids:
            return
        
        scoresheet_mappings = MapScoresheetToTeamJudge.objects.filter(
            judgeid=judge_id,
            teamid__in=team_ids
        )
        
        sheet_types_to_delete = []
        if presentation:
            sheet_types_to_delete.append(1)
        if journal:
            sheet_types_to_delete.append(2)
        if mdo:
            sheet_types_to_delete.append(3)
        if runpenalties:
            sheet_types_to_delete.append(4)
        if otherpenalties:
            sheet_types_to_delete.append(5)
        if redesign:
            sheet_types_to_delete.append(6)
        if championship:
            sheet_types_to_delete.append(7)
        
        if not sheet_types_to_delete:
            return
        
        scoresheet_mappings = scoresheet_mappings.filter(sheetType__in=sheet_types_to_delete)
        
        if not scoresheet_mappings.exists():
            return
        
        scoresheet_ids = list(scoresheet_mappings.values_list('scoresheetid', flat=True).distinct())
        scoresheet_mappings.delete()
        
        if scoresheet_ids:
            Scoresheet.objects.filter(id__in=scoresheet_ids).delete()
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise ValidationError({"detail": str(e)})
  
def make_sheets_for_team(teamid, clusterid):
    created_score_sheets = []
    try:
        # Get the team to check if it has advanced
        try:
            team = Teams.objects.get(id=teamid)
            team_has_advanced = getattr(team, 'advanced_to_championship', False)
        except Teams.DoesNotExist:
            team_has_advanced = False
        
        judges = MapJudgeToCluster.objects.filter(clusterid=clusterid)  # get list of judge mappings
        for judge_map in judges:
            # Create score sheets for each type (Presentation, Journal, Machine Design, Run Penalties, Other Penalties) based on the judge's role
            judge = Judge.objects.get(id=judge_map.judgeid)  # get judge from judge mapping
            
            # Skip preliminary scoresheets (1-5) if team has advanced - only create championship/redesign
            if judge.presentation and not team_has_advanced:
                sheet = create_base_score_sheet(1)
                map_data = {"teamid": teamid, "judgeid": judge.id, "scoresheetid": sheet.id, "sheetType": 1}
                map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                if map_serializer.is_valid():
                    map_serializer.save()
                    created_score_sheets.append({
                        "team_id": teamid,
                        "judge_id": judge.id,
                        "scoresheet_id": sheet.id,
                        "sheetType": 1
                    })
                else:
                    raise ValidationError(map_serializer.errors)
            if judge.journal and not team_has_advanced:
                sheet = create_base_score_sheet(2)
                map_data = {"teamid": teamid, "judgeid": judge.id, "scoresheetid": sheet.id, "sheetType": 2}
                map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                if map_serializer.is_valid():
                    map_serializer.save()
                    created_score_sheets.append({
                        "team_id": teamid,
                        "judge_id": judge.id,
                        "scoresheet_id": sheet.id,
                        "sheetType": 2
                    })
                else:
                    raise ValidationError(map_serializer.errors)
            if judge.mdo and not team_has_advanced:
                sheet = create_base_score_sheet(3)
                map_data = {"teamid": teamid, "judgeid": judge.id, "scoresheetid": sheet.id, "sheetType": 3}
                map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                if map_serializer.is_valid():
                    map_serializer.save()
                    created_score_sheets.append({
                        "team_id": teamid,
                        "judge_id": judge.id,
                        "scoresheet_id": sheet.id,
                        "sheetType": 3
                    })
                else:
                    raise ValidationError(map_serializer.errors)
            if judge.runpenalties and not team_has_advanced:
                sheet = create_base_score_sheet_runpenalties()
                map_data = {"teamid": teamid, "judgeid": judge.id, "scoresheetid": sheet.id, "sheetType": 4}
                map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                if map_serializer.is_valid():
                    map_serializer.save()
                    created_score_sheets.append({
                        "team_id": teamid,
                        "judge_id": judge.id,
                        "scoresheet_id": sheet.id,
                        "sheetType": 4
                    })
                else:
                    raise ValidationError(map_serializer.errors)
            if judge.otherpenalties and not team_has_advanced:
                sheet = create_base_score_sheet_otherpenalties()
                map_data = {"teamid": teamid, "judgeid": judge.id, "scoresheetid": sheet.id, "sheetType": 5}
                map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
                if map_serializer.is_valid():
                    map_serializer.save()
                    created_score_sheets.append({
                        "team_id": teamid,
                        "judge_id": judge.id,
                        "scoresheet_id": sheet.id,
                        "sheetType": 5
                    })
                else:
                    raise ValidationError(map_serializer.errors)
                created_score_sheets.append({
                    "team_id": teamid,
                    "judge_id": judge.id,
                    "scoresheet_id": sheet.id,
                    "sheetType": 5
                })
            else:
                raise ValidationError(map_serializer.errors)
        if judge.redesign:
            sheet = create_base_score_sheet_Redesign()
            map_data = {"teamid": teamid, "judgeid": judge.id, "scoresheetid": sheet.id, "sheetType": 6}
            map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
            if map_serializer.is_valid():
                map_serializer.save()
                created_score_sheets.append({
                    "team_id": teamid,
                    "judge_id": judge.id,
                    "scoresheet_id": sheet.id,
                    "sheetType": 6
                })
        if judge.championship:
            sheet = create_base_score_sheet_Championship()
            map_data = {"teamid": teamid, "judgeid": judge.id, "scoresheetid": sheet.id, "sheetType": 7}
            map_serializer = MapScoreSheetToTeamJudgeSerializer(data=map_data)
            if map_serializer.is_valid():
                map_serializer.save()
                created_score_sheets.append({
                    "team_id": teamid,
                    "judge_id": judge.id,
                    "scoresheet_id": sheet.id,
                    "sheetType": 7
                })
            else:
                raise ValidationError(map_serializer.errors)

    except Exception as e:
        raise e

    return created_score_sheets


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_scoresheet_details_by_team(request, team_id):
    scoresheet_mappings = MapScoresheetToTeamJudge.objects.filter(teamid=team_id)
    scoresheets = Scoresheet.objects.filter(id__in=scoresheet_mappings.values_list('scoresheetid', flat=True))
    presentation_scoresheet_details = [[] for _ in range(9)]
    journal_scoresheet_details = [[] for _ in range(9)]
    machinedesign_scoresheet_details = [[] for _ in range(9)]
    run_penalties_scoresheet_details = [[] for _ in range(16)]
    other_penalties_scoresheet_details = [[] for _ in range(7)]
    redesign_scoresheet_details = [[] for _ in range(8)]
    championship_scoresheet_details = [[] for _ in range(42)]  # Fields 1-42 (including penalty fields 19-42)
    for sheet in scoresheets:
      if sheet.sheetType == 1:
        presentation_scoresheet_details[0].append(sheet.field1)
        presentation_scoresheet_details[1].append(sheet.field2)
        presentation_scoresheet_details[2].append(sheet.field3)
        presentation_scoresheet_details[3].append(sheet.field4)
        presentation_scoresheet_details[4].append(sheet.field5)
        presentation_scoresheet_details[5].append(sheet.field6)
        presentation_scoresheet_details[6].append(sheet.field7)
        presentation_scoresheet_details[7].append(sheet.field8)
        presentation_scoresheet_details[8].append(sheet.field9)
      elif sheet.sheetType == 2:
        journal_scoresheet_details[0].append(sheet.field1)
        journal_scoresheet_details[1].append(sheet.field2)
        journal_scoresheet_details[2].append(sheet.field3)
        journal_scoresheet_details[3].append(sheet.field4)
        journal_scoresheet_details[4].append(sheet.field5)
        journal_scoresheet_details[5].append(sheet.field6)
        journal_scoresheet_details[6].append(sheet.field7)
        journal_scoresheet_details[7].append(sheet.field8)
        journal_scoresheet_details[8].append(sheet.field9)
      elif sheet.sheetType == 3:
        machinedesign_scoresheet_details[0].append(sheet.field1)
        machinedesign_scoresheet_details[1].append(sheet.field2)
        machinedesign_scoresheet_details[2].append(sheet.field3)
        machinedesign_scoresheet_details[3].append(sheet.field4)
        machinedesign_scoresheet_details[4].append(sheet.field5)
        machinedesign_scoresheet_details[5].append(sheet.field6)
        machinedesign_scoresheet_details[6].append(sheet.field7)
        machinedesign_scoresheet_details[7].append(sheet.field8)
        machinedesign_scoresheet_details[8].append(sheet.field9)
      elif sheet.sheetType == 4:
        run_penalties_scoresheet_details[0].append(sheet.field1)
        run_penalties_scoresheet_details[1].append(sheet.field2)
        run_penalties_scoresheet_details[2].append(sheet.field3)
        run_penalties_scoresheet_details[3].append(sheet.field4)
        run_penalties_scoresheet_details[4].append(sheet.field5)
        run_penalties_scoresheet_details[5].append(sheet.field6)
        run_penalties_scoresheet_details[6].append(sheet.field7)
        run_penalties_scoresheet_details[7].append(sheet.field8)
        run_penalties_scoresheet_details[8].append(sheet.field10)
        run_penalties_scoresheet_details[9].append(sheet.field11)
        run_penalties_scoresheet_details[10].append(sheet.field12)
        run_penalties_scoresheet_details[11].append(sheet.field13)
        run_penalties_scoresheet_details[12].append(sheet.field14)
        run_penalties_scoresheet_details[13].append(sheet.field15)
        run_penalties_scoresheet_details[14].append(sheet.field16)
        run_penalties_scoresheet_details[15].append(sheet.field17)
      
      elif sheet.sheetType == 5:
        other_penalties_scoresheet_details[0].append(sheet.field1)
        other_penalties_scoresheet_details[1].append(sheet.field2)
        other_penalties_scoresheet_details[2].append(sheet.field3)
        other_penalties_scoresheet_details[3].append(sheet.field4)
        other_penalties_scoresheet_details[4].append(sheet.field5)
        other_penalties_scoresheet_details[5].append(sheet.field6)
        other_penalties_scoresheet_details[6].append(sheet.field7)
      elif sheet.sheetType == 6:
        redesign_scoresheet_details[0].append(sheet.field1)
        redesign_scoresheet_details[1].append(sheet.field2)
        redesign_scoresheet_details[2].append(sheet.field3)
        redesign_scoresheet_details[3].append(sheet.field4)
        redesign_scoresheet_details[4].append(sheet.field5)
        redesign_scoresheet_details[5].append(sheet.field6)
        redesign_scoresheet_details[6].append(sheet.field7)
        redesign_scoresheet_details[7].append(sheet.field9)
      elif sheet.sheetType == 7:
        
        # Machine Design fields 1-8 (field9 is CharField for comments)
        championship_scoresheet_details[0].append(sheet.field1)
        championship_scoresheet_details[1].append(sheet.field2)
        championship_scoresheet_details[2].append(sheet.field3)
        championship_scoresheet_details[3].append(sheet.field4)
        championship_scoresheet_details[4].append(sheet.field5)
        championship_scoresheet_details[5].append(sheet.field6)
        championship_scoresheet_details[6].append(sheet.field7)
        championship_scoresheet_details[7].append(sheet.field8)
        championship_scoresheet_details[8].append(sheet.field9)  # Machine Design comment
        # Presentation fields 10-17 (field18 is CharField for comments)
        championship_scoresheet_details[9].append(sheet.field10)
        championship_scoresheet_details[10].append(sheet.field11)
        championship_scoresheet_details[11].append(sheet.field12)
        championship_scoresheet_details[12].append(sheet.field13)
        championship_scoresheet_details[13].append(sheet.field14)
        championship_scoresheet_details[14].append(sheet.field15)
        championship_scoresheet_details[15].append(sheet.field16)
        championship_scoresheet_details[16].append(sheet.field17)
        championship_scoresheet_details[17].append(sheet.field18)  # Presentation comment
        
        # Penalty fields 19-42 (General Penalties: 19-25, Run Penalties: 26-42)
        championship_scoresheet_details[18].append(sheet.field19)  # General Penalty 1
        championship_scoresheet_details[19].append(sheet.field20)  # General Penalty 2
        championship_scoresheet_details[20].append(sheet.field21)  # General Penalty 3
        championship_scoresheet_details[21].append(sheet.field22)  # General Penalty 4
        championship_scoresheet_details[22].append(sheet.field23)  # General Penalty 5
        championship_scoresheet_details[23].append(sheet.field24)  # General Penalty 6
        championship_scoresheet_details[24].append(sheet.field25)  # General Penalty 7
        championship_scoresheet_details[25].append(sheet.field26)  # Run Penalty 1
        championship_scoresheet_details[26].append(sheet.field27)  # Run Penalty 2
        championship_scoresheet_details[27].append(sheet.field28)  # Run Penalty 3
        championship_scoresheet_details[28].append(sheet.field29)  # Run Penalty 4
        championship_scoresheet_details[29].append(sheet.field30)  # Run Penalty 5
        championship_scoresheet_details[30].append(sheet.field31)  # Run Penalty 6
        championship_scoresheet_details[31].append(sheet.field32)  # Run Penalty 7
        championship_scoresheet_details[32].append(sheet.field33)  # Run Penalty 8
        championship_scoresheet_details[33].append(sheet.field34)  # Run Penalty 9
        championship_scoresheet_details[34].append(sheet.field35)  # Run Penalty 10
        championship_scoresheet_details[35].append(sheet.field36)  # Run Penalty 11
        championship_scoresheet_details[36].append(sheet.field37)  # Run Penalty 12
        championship_scoresheet_details[37].append(sheet.field38)  # Run Penalty 13
        championship_scoresheet_details[38].append(sheet.field39)  # Run Penalty 14
        championship_scoresheet_details[39].append(sheet.field40)  # Run Penalty 15
        championship_scoresheet_details[40].append(sheet.field41)  # Run Penalty 16
        championship_scoresheet_details[41].append(sheet.field42)  # Run Penalty 17

    presentation_scoresheet_response = {
      "1": presentation_scoresheet_details[0],
      "2": presentation_scoresheet_details[1],
      "3": presentation_scoresheet_details[2],
      "4": presentation_scoresheet_details[3],
      "5": presentation_scoresheet_details[4],
      "6": presentation_scoresheet_details[5],
      "7": presentation_scoresheet_details[6],
      "8": presentation_scoresheet_details[7],
      "9": presentation_scoresheet_details[8],
    }
    journal_scoresheet_response = {
      "1": journal_scoresheet_details[0],
      "2": journal_scoresheet_details[1],
      "3": journal_scoresheet_details[2],
      "4": journal_scoresheet_details[3],
      "5": journal_scoresheet_details[4],
      "6": journal_scoresheet_details[5],
      "7": journal_scoresheet_details[6],
      "8": journal_scoresheet_details[7],
      "9": journal_scoresheet_details[8],
    }
    machinedesign_scoresheet_response = {
      "1": machinedesign_scoresheet_details[0],
      "2": machinedesign_scoresheet_details[1],
      "3": machinedesign_scoresheet_details[2],
      "4": machinedesign_scoresheet_details[3],
      "5": machinedesign_scoresheet_details[4],
      "6": machinedesign_scoresheet_details[5],
      "7": machinedesign_scoresheet_details[6],
      "8": machinedesign_scoresheet_details[7],
      "9": machinedesign_scoresheet_details[8],
    }

    runpenalties_scoresheet_response = {
      "1": run_penalties_scoresheet_details[0],
      "2": run_penalties_scoresheet_details[1],
      "3": run_penalties_scoresheet_details[2],
      "4": run_penalties_scoresheet_details[3],
      "5": run_penalties_scoresheet_details[4],
      "6": run_penalties_scoresheet_details[5],
      "7": run_penalties_scoresheet_details[6],
      "8": run_penalties_scoresheet_details[7],
      "10": run_penalties_scoresheet_details[8],
      "11": run_penalties_scoresheet_details[9],
      "12": run_penalties_scoresheet_details[10],
      "13": run_penalties_scoresheet_details[11],
      "14": run_penalties_scoresheet_details[12],
      "15": run_penalties_scoresheet_details[13],
      "16": run_penalties_scoresheet_details[14],
      "17": run_penalties_scoresheet_details[15],
  }
    otherpenalties_scoresheet_response = {
      "1": other_penalties_scoresheet_details[0],
      "2": other_penalties_scoresheet_details[1],
      "3": other_penalties_scoresheet_details[2],
      "4": other_penalties_scoresheet_details[3],
      "5": other_penalties_scoresheet_details[4],
      "6": other_penalties_scoresheet_details[5],
      "7": other_penalties_scoresheet_details[6],
    }
    redesign_scoresheet_response = {
      "1": redesign_scoresheet_details[0],
      "2": redesign_scoresheet_details[1],
      "3": redesign_scoresheet_details[2],
      "4": redesign_scoresheet_details[3],
      "5": redesign_scoresheet_details[4],
      "6": redesign_scoresheet_details[5],
      "7": redesign_scoresheet_details[6],
      "8": redesign_scoresheet_details[7],
    }

    championship_scoresheet_response = {
      "field1": championship_scoresheet_details[0],   # Machine Design 1
      "field2": championship_scoresheet_details[1],   # Machine Design 2
      "field3": championship_scoresheet_details[2],   # Machine Design 3
      "field4": championship_scoresheet_details[3],   # Machine Design 4
      "field5": championship_scoresheet_details[4],   # Machine Design 5
      "field6": championship_scoresheet_details[5],   # Machine Design 6
      "field7": championship_scoresheet_details[6],   # Machine Design 7
      "field8": championship_scoresheet_details[7],   # Machine Design 8
      "field9": championship_scoresheet_details[8],   # Machine Design Comment
      "field10": championship_scoresheet_details[9],  # Presentation 1
      "field11": championship_scoresheet_details[10], # Presentation 2
      "field12": championship_scoresheet_details[11], # Presentation 3
      "field13": championship_scoresheet_details[12], # Presentation 4
      "field14": championship_scoresheet_details[13], # Presentation 5
      "field15": championship_scoresheet_details[14], # Presentation 6
      "field16": championship_scoresheet_details[15], # Presentation 7
      "field17": championship_scoresheet_details[16], # Presentation 8
      "field18": championship_scoresheet_details[17], # Presentation Comment
      # Penalty fields 19-42
      "field19": championship_scoresheet_details[18],  # General Penalty 1
      "field20": championship_scoresheet_details[19],  # General Penalty 2
      "field21": championship_scoresheet_details[20],  # General Penalty 3
      "field22": championship_scoresheet_details[21],  # General Penalty 4
      "field23": championship_scoresheet_details[22],  # General Penalty 5
      "field24": championship_scoresheet_details[23],  # General Penalty 6
      "field25": championship_scoresheet_details[24],  # General Penalty 7
      "field26": championship_scoresheet_details[25],  # Run Penalty 1
      "field27": championship_scoresheet_details[26],  # Run Penalty 2
      "field28": championship_scoresheet_details[27],  # Run Penalty 3
      "field29": championship_scoresheet_details[28],  # Run Penalty 4
      "field30": championship_scoresheet_details[29],  # Run Penalty 5
      "field31": championship_scoresheet_details[30],  # Run Penalty 6
      "field32": championship_scoresheet_details[31],  # Run Penalty 7
      "field33": championship_scoresheet_details[32],  # Run Penalty 8
      "field34": championship_scoresheet_details[33],  # Run Penalty 9
      "field35": championship_scoresheet_details[34],  # Run Penalty 10
      "field36": championship_scoresheet_details[35],  # Run Penalty 11
      "field37": championship_scoresheet_details[36],  # Run Penalty 12
      "field38": championship_scoresheet_details[37],  # Run Penalty 13
      "field39": championship_scoresheet_details[38],  # Run Penalty 14
      "field40": championship_scoresheet_details[39],  # Run Penalty 15
      "field41": championship_scoresheet_details[40],  # Run Penalty 16
      "field42": championship_scoresheet_details[41],  # Run Penalty 17
    }
    

    return Response({
      "1": presentation_scoresheet_response,
      "2": journal_scoresheet_response,
      "3": machinedesign_scoresheet_response,
      "4": runpenalties_scoresheet_response,
      "5": otherpenalties_scoresheet_response,
      "6": redesign_scoresheet_response,
      "7": championship_scoresheet_response
    }, status=status.HTTP_200_OK)

@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def get_scoresheet_details_for_contest(request):
    try:
        contestid = int(request.query_params.get("contestid", ""))
        if contestid <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"detail": "contestid must be a positive integer"}, status=status.HTTP_400_BAD_REQUEST)
    contest = get_object_or_404(Contest, id=contestid)
    team_mappings = MapContestToTeam.objects.filter(contestid=contest.id)
    
    # Get all clusters for this contest
    contest_cluster_ids = MapContestToCluster.objects.filter(contestid=contest.id).values_list('clusterid', flat=True)
    
    # Get all judges who are still assigned to clusters in this contest
    active_judge_ids = MapJudgeToCluster.objects.filter(clusterid__in=contest_cluster_ids).values_list('judgeid', flat=True).distinct()
    
    team_responses = {}
    for mapping in team_mappings:
        team = get_object_or_404(Teams, id=mapping.teamid)
        # Only include scoresheets from judges who are still in clusters for this contest
        scoresheet_mappings = MapScoresheetToTeamJudge.objects.filter(
            teamid=team.id,
            judgeid__in=active_judge_ids
        )
        scoresheets = Scoresheet.objects.filter(id__in=scoresheet_mappings.values_list('scoresheetid', flat=True))
        presentation_scoresheet_details = [[] for _ in range(9)]
        journal_scoresheet_details = [[] for _ in range(9)]
        machinedesign_scoresheet_details = [[] for _ in range(9)]
        run_penalties_scoresheet_details = [[] for _ in range(16)]
        other_penalties_scoresheet_details = [[] for _ in range(7)]
        redesign_scoresheet_details = [[] for _ in range(8)]
        championship_scoresheet_details = [[] for _ in range(42)]  # Fields 1-42 (including penalty fields 19-42)
        for sheet in scoresheets:
            if sheet.sheetType == 1:
                presentation_scoresheet_details[0].append(sheet.field1)
                presentation_scoresheet_details[1].append(sheet.field2)
                presentation_scoresheet_details[2].append(sheet.field3)
                presentation_scoresheet_details[3].append(sheet.field4)
                presentation_scoresheet_details[4].append(sheet.field5)
                presentation_scoresheet_details[5].append(sheet.field6)
                presentation_scoresheet_details[6].append(sheet.field7)
                presentation_scoresheet_details[7].append(sheet.field8)
                presentation_scoresheet_details[8].append(sheet.field9)
            elif sheet.sheetType == 2:
                journal_scoresheet_details[0].append(sheet.field1)
                journal_scoresheet_details[1].append(sheet.field2)
                journal_scoresheet_details[2].append(sheet.field3)
                journal_scoresheet_details[3].append(sheet.field4)
                journal_scoresheet_details[4].append(sheet.field5)
                journal_scoresheet_details[5].append(sheet.field6)
                journal_scoresheet_details[6].append(sheet.field7)
                journal_scoresheet_details[7].append(sheet.field8)
                journal_scoresheet_details[8].append(sheet.field9)
            elif sheet.sheetType == 3:
                machinedesign_scoresheet_details[0].append(sheet.field1)
                machinedesign_scoresheet_details[1].append(sheet.field2)
                machinedesign_scoresheet_details[2].append(sheet.field3)
                machinedesign_scoresheet_details[3].append(sheet.field4)
                machinedesign_scoresheet_details[4].append(sheet.field5)
                machinedesign_scoresheet_details[5].append(sheet.field6)
                machinedesign_scoresheet_details[6].append(sheet.field7)
                machinedesign_scoresheet_details[7].append(sheet.field8)
                machinedesign_scoresheet_details[8].append(sheet.field9)
            elif sheet.sheetType == 4:
                run_penalties_scoresheet_details[0].append(sheet.field1)
                run_penalties_scoresheet_details[1].append(sheet.field2)
                run_penalties_scoresheet_details[2].append(sheet.field3)
                run_penalties_scoresheet_details[3].append(sheet.field4)
                run_penalties_scoresheet_details[4].append(sheet.field5)
                run_penalties_scoresheet_details[5].append(sheet.field6)
                run_penalties_scoresheet_details[6].append(sheet.field7)
                run_penalties_scoresheet_details[7].append(sheet.field8)
                run_penalties_scoresheet_details[8].append(sheet.field10)
                run_penalties_scoresheet_details[9].append(sheet.field11)
                run_penalties_scoresheet_details[10].append(sheet.field12)
                run_penalties_scoresheet_details[11].append(sheet.field13)
                run_penalties_scoresheet_details[12].append(sheet.field14)
                run_penalties_scoresheet_details[13].append(sheet.field15)
                run_penalties_scoresheet_details[14].append(sheet.field16)
                run_penalties_scoresheet_details[15].append(sheet.field17)
            
            elif sheet.sheetType == 5:
                other_penalties_scoresheet_details[0].append(sheet.field1)
                other_penalties_scoresheet_details[1].append(sheet.field2)
                other_penalties_scoresheet_details[2].append(sheet.field3)
                other_penalties_scoresheet_details[3].append(sheet.field4)
                other_penalties_scoresheet_details[4].append(sheet.field5)
                other_penalties_scoresheet_details[5].append(sheet.field6)
                other_penalties_scoresheet_details[6].append(sheet.field7)
            elif sheet.sheetType == 6:
                redesign_scoresheet_details[0].append(sheet.field1)
                redesign_scoresheet_details[1].append(sheet.field2)
                redesign_scoresheet_details[2].append(sheet.field3)
                redesign_scoresheet_details[3].append(sheet.field4)
                redesign_scoresheet_details[4].append(sheet.field5)
                redesign_scoresheet_details[5].append(sheet.field6)
                redesign_scoresheet_details[6].append(sheet.field7)
                redesign_scoresheet_details[7].append(sheet.field9)
            elif sheet.sheetType == 7:
                # Machine Design fields 1-8 (field9 is CharField for comments)
                championship_scoresheet_details[0].append(sheet.field1)
                championship_scoresheet_details[1].append(sheet.field2)
                championship_scoresheet_details[2].append(sheet.field3)
                championship_scoresheet_details[3].append(sheet.field4)
                championship_scoresheet_details[4].append(sheet.field5)
                championship_scoresheet_details[5].append(sheet.field6)
                championship_scoresheet_details[6].append(sheet.field7)
                championship_scoresheet_details[7].append(sheet.field8)
                championship_scoresheet_details[8].append(sheet.field9)  # Machine Design comment
                # Presentation fields 10-17 (field18 is CharField for comments)
                championship_scoresheet_details[9].append(sheet.field10)
                championship_scoresheet_details[10].append(sheet.field11)
                championship_scoresheet_details[11].append(sheet.field12)
                championship_scoresheet_details[12].append(sheet.field13)
                championship_scoresheet_details[13].append(sheet.field14)
                championship_scoresheet_details[14].append(sheet.field15)
                championship_scoresheet_details[15].append(sheet.field16)
                championship_scoresheet_details[16].append(sheet.field17)
                championship_scoresheet_details[17].append(sheet.field18)  # Presentation comment
                
                # Penalty fields 19-42 (General Penalties: 19-25, Run Penalties: 26-42)
                championship_scoresheet_details[18].append(sheet.field19)  # General Penalty 1
                championship_scoresheet_details[19].append(sheet.field20)  # General Penalty 2
                championship_scoresheet_details[20].append(sheet.field21)  # General Penalty 3
                championship_scoresheet_details[21].append(sheet.field22)  # General Penalty 4
                championship_scoresheet_details[22].append(sheet.field23)  # General Penalty 5
                championship_scoresheet_details[23].append(sheet.field24)  # General Penalty 6
                championship_scoresheet_details[24].append(sheet.field25)  # General Penalty 7
                championship_scoresheet_details[25].append(sheet.field26)  # Run Penalty 1
                championship_scoresheet_details[26].append(sheet.field27)  # Run Penalty 2
                championship_scoresheet_details[27].append(sheet.field28)  # Run Penalty 3
                championship_scoresheet_details[28].append(sheet.field29)  # Run Penalty 4
                championship_scoresheet_details[29].append(sheet.field30)  # Run Penalty 5
                championship_scoresheet_details[30].append(sheet.field31)  # Run Penalty 6
                championship_scoresheet_details[31].append(sheet.field32)  # Run Penalty 7
                championship_scoresheet_details[32].append(sheet.field33)  # Run Penalty 8
                championship_scoresheet_details[33].append(sheet.field34)  # Run Penalty 9
                championship_scoresheet_details[34].append(sheet.field35)  # Run Penalty 10
                championship_scoresheet_details[35].append(sheet.field36)  # Run Penalty 11
                championship_scoresheet_details[36].append(sheet.field37)  # Run Penalty 12
                championship_scoresheet_details[37].append(sheet.field38)  # Run Penalty 13
                championship_scoresheet_details[38].append(sheet.field39)  # Run Penalty 14
                championship_scoresheet_details[39].append(sheet.field40)  # Run Penalty 15
                championship_scoresheet_details[40].append(sheet.field41)  # Run Penalty 16
                championship_scoresheet_details[41].append(sheet.field42)  # Run Penalty 17
            


        presentation_scoresheet_response = {
          "1": presentation_scoresheet_details[0],
          "2": presentation_scoresheet_details[1],
          "3": presentation_scoresheet_details[2],
          "4": presentation_scoresheet_details[3],
          "5": presentation_scoresheet_details[4],
          "6": presentation_scoresheet_details[5],
          "7": presentation_scoresheet_details[6],
          "8": presentation_scoresheet_details[7],
          "9": presentation_scoresheet_details[8],
        }
        journal_scoresheet_response = {
          "1": journal_scoresheet_details[0],
          "2": journal_scoresheet_details[1],
          "3": journal_scoresheet_details[2],
          "4": journal_scoresheet_details[3],
          "5": journal_scoresheet_details[4],
          "6": journal_scoresheet_details[5],
          "7": journal_scoresheet_details[6],
          "8": journal_scoresheet_details[7],
          "9": journal_scoresheet_details[8],
        }
        machinedesign_scoresheet_response = {
          "1": machinedesign_scoresheet_details[0],
          "2": machinedesign_scoresheet_details[1],
          "3": machinedesign_scoresheet_details[2],
          "4": machinedesign_scoresheet_details[3],
          "5": machinedesign_scoresheet_details[4],
          "6": machinedesign_scoresheet_details[5],
          "7": machinedesign_scoresheet_details[6],
          "8": machinedesign_scoresheet_details[7],
          "9": machinedesign_scoresheet_details[8],
        }
        runpenalties_scoresheet_response = {
          "1": run_penalties_scoresheet_details[0],
          "2": run_penalties_scoresheet_details[1],
          "3": run_penalties_scoresheet_details[2],
          "4": run_penalties_scoresheet_details[3],
          "5": run_penalties_scoresheet_details[4],
          "6": run_penalties_scoresheet_details[5],
          "7": run_penalties_scoresheet_details[6],
          "8": run_penalties_scoresheet_details[7],
          "10": run_penalties_scoresheet_details[8],
          "11": run_penalties_scoresheet_details[9],
          "12": run_penalties_scoresheet_details[10],
          "13": run_penalties_scoresheet_details[11],
          "14": run_penalties_scoresheet_details[12],
          "15": run_penalties_scoresheet_details[13],
          "16": run_penalties_scoresheet_details[14],
          "17": run_penalties_scoresheet_details[15],
        }
        otherpenalties_scoresheet_response = {
          "1": other_penalties_scoresheet_details[0],
          "2": other_penalties_scoresheet_details[1],
          "3": other_penalties_scoresheet_details[2],
          "4": other_penalties_scoresheet_details[3],
          "5": other_penalties_scoresheet_details[4],
          "6": other_penalties_scoresheet_details[5],
          "7": other_penalties_scoresheet_details[6],
        }
        redesign_scoresheet_response = {
            "1": redesign_scoresheet_details[0],
            "2": redesign_scoresheet_details[1],
            "3": redesign_scoresheet_details[2],
            "4": redesign_scoresheet_details[3],
            "5": redesign_scoresheet_details[4],
            "6": redesign_scoresheet_details[5],
            "7": redesign_scoresheet_details[6],
            "8": redesign_scoresheet_details[7],
        }
        championship_scoresheet_response = {
            "field1": championship_scoresheet_details[0],   # Machine Design 1
            "field2": championship_scoresheet_details[1],   # Machine Design 2
            "field3": championship_scoresheet_details[2],   # Machine Design 3
            "field4": championship_scoresheet_details[3],   # Machine Design 4
            "field5": championship_scoresheet_details[4],   # Machine Design 5
            "field6": championship_scoresheet_details[5],   # Machine Design 6
            "field7": championship_scoresheet_details[6],   # Machine Design 7
            "field8": championship_scoresheet_details[7],   # Machine Design 8
            "field9": championship_scoresheet_details[8],   # Machine Design Comment
            "field10": championship_scoresheet_details[9],  # Presentation 1
            "field11": championship_scoresheet_details[10], # Presentation 2
            "field12": championship_scoresheet_details[11], # Presentation 3
            "field13": championship_scoresheet_details[12], # Presentation 4
            "field14": championship_scoresheet_details[13], # Presentation 5
            "field15": championship_scoresheet_details[14], # Presentation 6
            "field16": championship_scoresheet_details[15], # Presentation 7
            "field17": championship_scoresheet_details[16], # Presentation 8
            "field18": championship_scoresheet_details[17], # Presentation Comment
            # Penalty fields 19-42
            "field19": championship_scoresheet_details[18],  # General Penalty 1
            "field20": championship_scoresheet_details[19],  # General Penalty 2
            "field21": championship_scoresheet_details[20],  # General Penalty 3
            "field22": championship_scoresheet_details[21],  # General Penalty 4
            "field23": championship_scoresheet_details[22],  # General Penalty 5
            "field24": championship_scoresheet_details[23],  # General Penalty 6
            "field25": championship_scoresheet_details[24],  # General Penalty 7
            "field26": championship_scoresheet_details[25],  # Run Penalty 1
            "field27": championship_scoresheet_details[26],  # Run Penalty 2
            "field28": championship_scoresheet_details[27],  # Run Penalty 3
            "field29": championship_scoresheet_details[28],  # Run Penalty 4
            "field30": championship_scoresheet_details[29],  # Run Penalty 5
            "field31": championship_scoresheet_details[30],  # Run Penalty 6
            "field32": championship_scoresheet_details[31],  # Run Penalty 7
            "field33": championship_scoresheet_details[32],  # Run Penalty 8
            "field34": championship_scoresheet_details[33],  # Run Penalty 9
            "field35": championship_scoresheet_details[34],  # Run Penalty 10
            "field36": championship_scoresheet_details[35],  # Run Penalty 11
            "field37": championship_scoresheet_details[36],  # Run Penalty 12
            "field38": championship_scoresheet_details[37],  # Run Penalty 13
            "field39": championship_scoresheet_details[38],  # Run Penalty 14
            "field40": championship_scoresheet_details[39],  # Run Penalty 15
            "field41": championship_scoresheet_details[40],  # Run Penalty 16
            "field42": championship_scoresheet_details[41],  # Run Penalty 17
        }

        team_responses[team.id] = {
            "team_id": team.id,
            "1": presentation_scoresheet_response,
            "2": journal_scoresheet_response,
            "3": machinedesign_scoresheet_response,
            "4": runpenalties_scoresheet_response,
            "5": otherpenalties_scoresheet_response,
            "6": redesign_scoresheet_response,
            "7": championship_scoresheet_response
        }

    return Response({"teams": team_responses}, status=status.HTTP_200_OK)


def create_scoresheets_for_judges_in_cluster(cluster_id):
    """
    Create scoresheets for all judges in a cluster when teams are added.
    This is called after teams are moved to championship/redesign clusters.
    
    IMPORTANT: Only creates scoresheets appropriate for the cluster type:
    - Championship clusters: ONLY championship scoresheets (type 7)
    - Redesign clusters: ONLY redesign scoresheets (type 6)
    - Preliminary clusters: All scoresheets based on judge flags
    """
    try:
        # Get the cluster to check its type
        from ..models import JudgeClusters
        try:
            cluster = JudgeClusters.objects.get(id=cluster_id)
            cluster_type = getattr(cluster, 'cluster_type', 'preliminary')
        except JudgeClusters.DoesNotExist:
            cluster_type = 'preliminary'
        
        # Get all judges in this cluster
        judge_mappings = MapJudgeToCluster.objects.filter(clusterid=cluster_id)
        
        # Get all teams in this cluster
        team_mappings = MapClusterToTeam.objects.filter(clusterid=cluster_id)
        
        if len(judge_mappings) == 0:
            return []
        
        if len(team_mappings) == 0:
            return []
        
        created_scoresheets = []
        
        for judge_mapping in judge_mappings:
            try:
                judge = Judge.objects.get(id=judge_mapping.judgeid)
                
                # Determine which scoresheets to create based on cluster type
                if cluster_type == 'championship':
                    # Championship clusters: ONLY create championship scoresheets (type 7)
                    # Do NOT create any preliminary scoresheets (1-5) or redesign (6)
                    sheets = create_sheets_for_teams_in_cluster(
                        judge.id,
                        cluster_id,
                        False,  # presentation
                        False,  # journal
                        False,  # mdo
                        False,  # runpenalties
                        False,  # otherpenalties
                        False,  # redesign
                        True    # championship ONLY
                    )
                elif cluster_type == 'redesign':
                    # Redesign clusters: ONLY create redesign scoresheets (type 6)
                    # Do NOT create any preliminary scoresheets (1-5) or championship (7)
                    sheets = create_sheets_for_teams_in_cluster(
                        judge.id,
                        cluster_id,
                        False,  # presentation
                        False,  # journal
                        False,  # mdo
                        False,  # runpenalties
                        False,  # otherpenalties
                        True,   # redesign ONLY
                        False   # championship
                    )
                else:
                    # Preliminary clusters: create all scoresheets based on judge flags
                    sheets = create_sheets_for_teams_in_cluster(
                        judge.id,
                        cluster_id,
                        judge.presentation,
                        judge.journal,
                        judge.mdo,
                        judge.runpenalties,
                        judge.otherpenalties,
                        judge.redesign,
                        judge.championship
                    )
                
                created_scoresheets.extend(sheets)
                
            except Judge.DoesNotExist:
                continue
            except Exception as e:
                continue
        
        return created_scoresheets
        
    except Exception as e:
        raise ValidationError({"detail": str(e)})
    
@api_view(['GET'])
def multi_team_general_penalties(request, judge_id, contest_id):
    """Get all teams assigned to a judge in a contest with their general penalty scoresheets"""
    try:
        
        # Get clusters assigned to this judge
        judge_clusters = MapJudgeToCluster.objects.filter(
            judgeid=judge_id
        ).values_list('clusterid', flat=True)
        print(f"DEBUG: judge_clusters={list(judge_clusters)}")

        # Get clusters in this contest
        contest_clusters = MapContestToCluster.objects.filter(
            contestid=contest_id
        ).values_list('clusterid', flat=True)
        print(f"DEBUG: contest_clusters={list(contest_clusters)}")

        # Get clusters that are both assigned to this judge AND in this contest
        common_clusters = set(judge_clusters) & set(contest_clusters)
        cluster_ids = list(common_clusters)
        print(f"DEBUG: common_clusters={cluster_ids}")
        
        team_mappings = MapClusterToTeam.objects.filter(clusterid__in=cluster_ids)
        
        result = []
        for team_mapping in team_mappings:
            # Get the actual Team object using the teamid integer
            try:
                team = Teams.objects.get(id=team_mapping.teamid)
            except Teams.DoesNotExist:
                continue

            # Get general penalties scoresheet (type 5)
            scoresheet_mapping = MapScoresheetToTeamJudge.objects.filter(
                teamid=team.id,
                judgeid=judge_id,
                sheetType=5
            ).first()

            if scoresheet_mapping:
                scoresheet = Scoresheet.objects.get(id=scoresheet_mapping.scoresheetid)
                result.append({
                    'team_id': team.id,
                    'team_name': team.team_name,
                    'scoresheet': {
                        'id': scoresheet.id,
                        'sheetType': scoresheet.sheetType,
                        'isSubmitted': scoresheet.isSubmitted,
                        'field1': scoresheet.field1 or 0,
                        'field2': scoresheet.field2 or 0,
                        'field3': scoresheet.field3 or 0,
                        'field4': scoresheet.field4 or 0,
                        'field5': scoresheet.field5 or 0,
                        'field6': scoresheet.field6 or 0,
                        'field7': scoresheet.field7 or 0,
                        'field8': scoresheet.field8 or 0,
                        'field9': scoresheet.field9 or "",
                    }
                })
        
        return Response({'teams': result}, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_missing_championship_scoresheets(request):
    """
    Create championship scoresheets for judges who have championship cluster assignments
    but are missing the corresponding scoresheets. This fixes the issue where advancement
    happened before the create_scoresheets_for_judges_in_cluster function existed.
    """
    try:
        judge_id = request.data.get('judge_id')
        if not judge_id:
            return Response({'error': 'judge_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        judge_id = int(judge_id)

        # Get the judge
        try:
            judge = Judge.objects.get(id=judge_id)
        except Judge.DoesNotExist:
            return Response({'error': f'Judge {judge_id} not found'}, status=status.HTTP_404_NOT_FOUND)

        created_scoresheets = []

        # Find all championship clusters this judge is assigned to
        championship_cluster_mappings = MapJudgeToCluster.objects.filter(
            judgeid=judge_id
        ).select_related('clusterid')

        championship_clusters = []
        for mapping in championship_cluster_mappings:
            try:
                cluster = JudgeClusters.objects.get(id=mapping.clusterid_id)
                if (cluster.cluster_type == 'championship' or
                    'championship' in cluster.cluster_name.lower()):
                    championship_clusters.append(cluster)
            except JudgeClusters.DoesNotExist:
                continue

        # For each championship cluster, create missing scoresheets
        for cluster in championship_clusters:
            # Get teams in this cluster
            team_mappings = MapClusterToTeam.objects.filter(clusterid=cluster.id)
            team_ids = [tm.teamid for tm in team_mappings]

            # Get teams that have advanced to championship
            advanced_teams = Teams.objects.filter(
                id__in=team_ids,
                advanced_to_championship=True
            )

            for team in advanced_teams:
                # Check if championship scoresheet already exists
                existing_mapping = MapScoresheetToTeamJudge.objects.filter(
                    teamid=team.id,
                    judgeid=judge.id,
                    sheetType=7  # Championship
                ).first()

                if not existing_mapping:
                    # Create championship scoresheet
                    try:
                        scoresheet = create_base_score_sheet_Championship()
                        MapScoresheetToTeamJudge.objects.create(
                            teamid=team.id,
                            judgeid=judge.id,
                            scoresheetid=scoresheet.id,
                            sheetType=7  # Championship
                        )
                        created_scoresheets.append({
                            'team_id': team.id,
                            'team_name': team.team_name,
                            'cluster_id': cluster.id,
                            'cluster_name': cluster.cluster_name,
                            'scoresheet_id': scoresheet.id
                        })
                    except Exception as e:
                        print(f"Error creating championship scoresheet for judge {judge.id}, team {team.id}: {str(e)}")
                        continue

        return Response({
            'message': f'Created {len(created_scoresheets)} championship scoresheets for judge {judge_id}',
            'created_scoresheets': created_scoresheets
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Error in create_missing_championship_scoresheets: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def multi_team_run_penalties(request, judge_id, contest_id):
    """Get all teams assigned to a judge in a contest with their run penalty scoresheets"""
    try:
        
        # Get clusters assigned to this judge
        judge_clusters = MapJudgeToCluster.objects.filter(
            judgeid=judge_id
        ).values_list('clusterid', flat=True)
        print(f"DEBUG: judge_clusters={list(judge_clusters)}")

        # Get clusters in this contest
        contest_clusters = MapContestToCluster.objects.filter(
            contestid=contest_id
        ).values_list('clusterid', flat=True)
        print(f"DEBUG: contest_clusters={list(contest_clusters)}")

        # Get clusters that are both assigned to this judge AND in this contest
        common_clusters = set(judge_clusters) & set(contest_clusters)
        cluster_ids = list(common_clusters)
        print(f"DEBUG: common_clusters={cluster_ids}")
        
        team_mappings = MapClusterToTeam.objects.filter(clusterid__in=cluster_ids)
        
        result = []
        for team_mapping in team_mappings:
            # Get the actual Team object using the teamid integer
            try:
                team = Teams.objects.get(id=team_mapping.teamid)
            except Teams.DoesNotExist:
                continue

            # Get run penalties scoresheet (type 4)
            scoresheet_mapping = MapScoresheetToTeamJudge.objects.filter(
                teamid=team.id,
                judgeid=judge_id,
                sheetType=4
            ).first()

            if scoresheet_mapping:
                scoresheet = Scoresheet.objects.get(id=scoresheet_mapping.scoresheetid)
                result.append({
                    'team_id': team.id,
                    'team_name': team.team_name,
                    'scoresheet': {
                        'id': scoresheet.id,
                        'sheetType': scoresheet.sheetType,
                        'isSubmitted': scoresheet.isSubmitted,
                        'field1': scoresheet.field1 or 0,
                        'field2': scoresheet.field2 or 0,
                        'field3': scoresheet.field3 or 0,
                        'field4': scoresheet.field4 or 0,
                        'field5': scoresheet.field5 or 0,
                        'field6': scoresheet.field6 or 0,
                        'field7': scoresheet.field7 or 0,
                        'field8': scoresheet.field8 or 0,
                        'field9': scoresheet.field9 or "",
                        'field10': scoresheet.field10 or 0,
                        'field11': scoresheet.field11 or 0,
                        'field12': scoresheet.field12 or 0,
                        'field13': scoresheet.field13 or 0,
                        'field14': scoresheet.field14 or 0,
                        'field15': scoresheet.field15 or 0,
                        'field16': scoresheet.field16 or 0,
                        'field17': scoresheet.field17 or 0,
                    }
                })
        
        return Response({'teams': result}, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_missing_championship_scoresheets(request):
    """
    Create championship scoresheets for judges who have championship cluster assignments
    but are missing the corresponding scoresheets. This fixes the issue where advancement
    happened before the create_scoresheets_for_judges_in_cluster function existed.
    """
    try:
        judge_id = request.data.get('judge_id')
        if not judge_id:
            return Response({'error': 'judge_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        judge_id = int(judge_id)

        # Get the judge
        try:
            judge = Judge.objects.get(id=judge_id)
        except Judge.DoesNotExist:
            return Response({'error': f'Judge {judge_id} not found'}, status=status.HTTP_404_NOT_FOUND)

        created_scoresheets = []

        # Find all championship clusters this judge is assigned to
        championship_cluster_mappings = MapJudgeToCluster.objects.filter(
            judgeid=judge_id
        ).select_related('clusterid')

        championship_clusters = []
        for mapping in championship_cluster_mappings:
            try:
                cluster = JudgeClusters.objects.get(id=mapping.clusterid_id)
                if (cluster.cluster_type == 'championship' or
                    'championship' in cluster.cluster_name.lower()):
                    championship_clusters.append(cluster)
            except JudgeClusters.DoesNotExist:
                continue

        # For each championship cluster, create missing scoresheets
        for cluster in championship_clusters:
            # Get teams in this cluster
            team_mappings = MapClusterToTeam.objects.filter(clusterid=cluster.id)
            team_ids = [tm.teamid for tm in team_mappings]

            # Get teams that have advanced to championship
            advanced_teams = Teams.objects.filter(
                id__in=team_ids,
                advanced_to_championship=True
            )

            for team in advanced_teams:
                # Check if championship scoresheet already exists
                existing_mapping = MapScoresheetToTeamJudge.objects.filter(
                    teamid=team.id,
                    judgeid=judge.id,
                    sheetType=7  # Championship
                ).first()

                if not existing_mapping:
                    # Create championship scoresheet
                    try:
                        scoresheet = create_base_score_sheet_Championship()
                        MapScoresheetToTeamJudge.objects.create(
                            teamid=team.id,
                            judgeid=judge.id,
                            scoresheetid=scoresheet.id,
                            sheetType=7  # Championship
                        )
                        created_scoresheets.append({
                            'team_id': team.id,
                            'team_name': team.team_name,
                            'cluster_id': cluster.id,
                            'cluster_name': cluster.cluster_name,
                            'scoresheet_id': scoresheet.id
                        })
                    except Exception as e:
                        print(f"Error creating championship scoresheet for judge {judge.id}, team {team.id}: {str(e)}")
                        continue

        return Response({
            'message': f'Created {len(created_scoresheets)} championship scoresheets for judge {judge_id}',
            'created_scoresheets': created_scoresheets
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Error in create_missing_championship_scoresheets: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
