from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from .Maps.MapUserToRole import create_user_role_map
from .Maps.MapContestToJudge import create_contest_to_judge_map
from .Maps.MapClusterToJudge import map_cluster_to_judge, delete_cluster_judge_mapping
from .scoresheets import create_sheets_for_teams_in_cluster, delete_sheets_for_teams_in_cluster
from ..auth.views import create_user
from ..models import (
    Judge, Scoresheet, MapScoresheetToTeamJudge, MapJudgeToCluster,
    Teams, MapContestToJudge, MapUserToRole, JudgeClusters
)
from ..serializers import JudgeSerializer
from ..auth.serializers import UserSerializer


from django.contrib.auth import get_user_model
from ..auth.password_utils import send_set_password_email

from django.contrib.sessions.models import Session
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError


def _delete_user_sessions(user_id: int) -> None:
    """
    Proactively invalidate all active sessions for the given user id.
    This ensures any existing session cookies become unusable immediately.
    """
    try:
        for session in Session.objects.all():
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) == str(user_id):
                session.delete()
    except Exception:
        pass


@api_view(["GET"])
def judge_by_id(request, judge_id):
    judge = get_object_or_404(Judge, id=judge_id)
    serializer = JudgeSerializer(instance=judge)
    return Response({"Judge": serializer.data}, status=status.HTTP_200_OK)


# Create Judge API View
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def create_judge(request):
    try:
        with transaction.atomic():
            user_response, judge_response = create_user_and_judge(request.data)

            # Map judge to user and contest, create sheets
            role_mapping = create_user_role_map({
                "uuid": user_response.get("user").get("id"),
                "role": 3,
                "relatedid": judge_response.get("id")
            })
            if not role_mapping:
                raise ValidationError('Failed to create judge role mapping.')

            contest_mapping = create_contest_to_judge_map({
                "contestid": request.data["contestid"],
                "judgeid": judge_response.get("id")
            })
            if isinstance(contest_mapping, Response):
                return contest_mapping

            # Support both single clusterid and multiple clusterids
            cluster_entries = request.data.get("clusterids")
            if cluster_entries and isinstance(cluster_entries, list):
                cluster_payloads = cluster_entries
            else:
                # Backward compatibility: single clusterid
                cluster_payloads = [{
                    "clusterid": request.data.get("clusterid"),
                    "presentation": request.data.get("presentation", False),
                    "journal": request.data.get("journal", False),
                    "mdo": request.data.get("mdo", False),
                    "runpenalties": request.data.get("runpenalties", False),
                    "otherpenalties": request.data.get("otherpenalties", False),
                    "redesign": request.data.get("redesign", False),
                    "championship": request.data.get("championship", False),
                }]

            # Process each cluster
            cluster_mappings = []
            score_sheets_list = []

            for payload in cluster_payloads:
                cluster_id = payload.get("clusterid")
                if not cluster_id:
                    continue

                cluster_mapping = map_cluster_to_judge({
                    "judgeid": judge_response.get("id"),
                    "clusterid": cluster_id,
                    "presentation": payload.get("presentation", False),
                    "journal": payload.get("journal", False),
                    "mdo": payload.get("mdo", False),
                    "runpenalties": payload.get("runpenalties", False),
                    "otherpenalties": payload.get("otherpenalties", False),
                    "redesign": payload.get("redesign", False),
                    "championship": payload.get("championship", False),
                })

                if isinstance(cluster_mapping, Response):
                    return cluster_mapping

                cluster_mappings.append(cluster_mapping)

                score_sheets = create_sheets_for_teams_in_cluster(
                    judge_response.get("id"),
                    cluster_id,
                    payload.get("presentation", False),
                    payload.get("journal", False),
                    payload.get("mdo", False),
                    payload.get("runpenalties", False),
                    payload.get("otherpenalties", False),
                    payload.get("redesign", False),
                    payload.get("championship", False),
                )

                if isinstance(score_sheets, Response):
                    return score_sheets

                score_sheets_list.append(score_sheets)

            return Response({
                "user": user_response,
                "judge": judge_response,
                "user_map": role_mapping,
                "contest_map": contest_mapping,
                "cluster_maps": cluster_mappings,
                "score_sheets": score_sheets_list
            }, status=status.HTTP_201_CREATED)

    except ValidationError as e:
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
def _get_delete_flags_for_cluster_type(cluster_id):
    """Get deletion flags based on cluster type to preserve scoresheets from other cluster types."""
    try:
        cluster = JudgeClusters.objects.get(id=cluster_id)
        cluster_type = getattr(cluster, 'cluster_type', 'preliminary')
    except JudgeClusters.DoesNotExist:
        cluster_type = 'preliminary'
    
    delete_presentation = delete_journal = delete_mdo = delete_runpenalties = delete_otherpenalties = False
    delete_redesign = delete_championship = False
    
    if cluster_type == 'preliminary':
        delete_presentation = delete_journal = delete_mdo = delete_runpenalties = delete_otherpenalties = True
    elif cluster_type == 'championship':
        delete_championship = True
    elif cluster_type == 'redesign':
        delete_redesign = True
    
    return (delete_presentation, delete_journal, delete_mdo, delete_runpenalties, 
            delete_otherpenalties, delete_redesign, delete_championship)

@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def edit_judge(request):
    try:
        judge = get_object_or_404(Judge, id=request.data["id"])

        cluster_entries = request.data.get("clusters")
        if cluster_entries and isinstance(cluster_entries, list):
            cluster_payloads = cluster_entries
        else:
            cluster_payloads = [{
                "clusterid": request.data.get("clusterid"),
                "contestid": request.data.get("contestid"),
                "presentation": request.data.get("presentation", False),
                "journal": request.data.get("journal", False),
                "mdo": request.data.get("mdo", False),
                "runpenalties": request.data.get("runpenalties", False),
                "otherpenalties": request.data.get("otherpenalties", False),
                "redesign": request.data.get("redesign", False),
                "championship": request.data.get("championship", False),
            }]

        new_first_name = request.data["first_name"]
        new_last_name = request.data["last_name"]
        new_phone_number = request.data["phone_number"]
        new_username = request.data["username"]
        new_role = request.data["role"]

        updated_cluster_ids = []

        with transaction.atomic():
            # MapUserToRole should always exist for a judge (created during judge creation)
            # If it doesn't exist, try to find the user and create the mapping automatically
            try:
                user_mapping = MapUserToRole.objects.get(role=3, relatedid=judge.id)
                user = get_object_or_404(User, id=user_mapping.uuid)
            except MapUserToRole.DoesNotExist:
                # Try to find the existing user by username to create the missing mapping
                # Note: We're NOT creating a new user, just finding the existing one
                user = User.objects.filter(username=new_username).first()
                if not user:
                    # If user doesn't exist, we can't create the mapping
                    raise ValidationError({
                        "detail": f"Judge {judge.id} is missing a user role mapping and user account not found. This is a data integrity issue. Please contact support."
                    })
                
                # Create the missing MapUserToRole mapping (NOT creating a new user, just the mapping)
                # create_user_role_map only creates the MapUserToRole record, not a User
                try:
                    user_mapping_dict = create_user_role_map({
                        "uuid": user.id,  # Using existing user's ID
                        "role": 3,
                        "relatedid": judge.id
                    })
                    # create_user_role_map returns a dict, extract uuid from it
                    user_uuid = user_mapping_dict.get("uuid") if isinstance(user_mapping_dict, dict) else user_mapping_dict["uuid"]
                    user = get_object_or_404(User, id=user_uuid)
                except Exception as e:
                    raise ValidationError({
                        "detail": f"Failed to create missing user role mapping for judge {judge.id}: {str(e)}"
                    })

            username_changed = (user.username != new_username)
            role_changed = (new_role != judge.role)

            if username_changed:
                try:
                    validate_email(new_username)
                except DjangoValidationError:
                    raise ValidationError({"detail": "Enter a valid email address."})
                if User.objects.filter(username=new_username).exclude(id=user.id).exists():
                    raise ValidationError({"detail": "Email already taken."})
                user.username = new_username
                user.save()
            user_serializer = UserSerializer(instance=user)

            judge.first_name = new_first_name
            judge.last_name = new_last_name
            judge.phone_number = new_phone_number
            judge.role = new_role
            judge.save()

            # Get cluster IDs from payload
            payload_cluster_ids = set()
            for payload in cluster_payloads:
                cluster_id = payload.get("clusterid")
                if cluster_id:
                    payload_cluster_ids.add(cluster_id)

            existing_assignments = MapJudgeToCluster.objects.filter(judgeid=judge.id)
            for assignment in existing_assignments:
                if assignment.clusterid not in payload_cluster_ids:
                    # Don't delete championship or redesign cluster assignments during editing
                    # These should be preserved unless explicitly being changed
                    if not (assignment.championship or assignment.redesign):
                        delete_flags = _get_delete_flags_for_cluster_type(assignment.clusterid)
                        delete_sheets_for_teams_in_cluster(
                            judge.id,
                            assignment.clusterid,
                            *delete_flags
                        )
                        assignment.delete()

            for payload in cluster_payloads:
                cluster_id = payload.get("clusterid")
                if not cluster_id:
                    continue

                contest_id = payload.get("contestid") or judge.contestid
                presentation = payload.get("presentation", False)
                journal = payload.get("journal", False)
                mdo = payload.get("mdo", False)
                runpenalties = payload.get("runpenalties", False)
                otherpenalties = payload.get("otherpenalties", False)
                redesign = payload.get("redesign", False)
                championship = payload.get("championship", False)


                delete_flags = _get_delete_flags_for_cluster_type(cluster_id)
                delete_sheets_for_teams_in_cluster(
                    judge.id,
                    cluster_id,
                    *delete_flags
                )

                map_cluster_to_judge({
                    "judgeid": judge.id,
                    "clusterid": cluster_id,
                    "contestid": contest_id,
                    "presentation": presentation,
                    "journal": journal,
                    "mdo": mdo,
                    "runpenalties": runpenalties,
                    "otherpenalties": otherpenalties,
                    "redesign": redesign,
                    "championship": championship,
                })

                create_sheets_for_teams_in_cluster(
                    judge.id,
                    cluster_id,
                    presentation,
                    journal,
                    mdo,
                    runpenalties,
                    otherpenalties,
                    redesign,
                    championship,
                )

                if contest_id and not MapContestToJudge.objects.filter(judgeid=judge.id, contestid=contest_id).exists():
                    create_contest_to_judge_map({"contestid": contest_id, "judgeid": judge.id})

                updated_cluster_ids.append(cluster_id)

            sync_judge_sheet_flags(judge.id)

            if username_changed or role_changed:
                _delete_user_sessions(user.id)

        serializer = JudgeSerializer(instance=judge)

    except Exception as e:
        raise ValidationError({"detail": str(e)})

    return Response({"judge": serializer.data, "clusterids": updated_cluster_ids, "user": user_serializer.data}, status=status.HTTP_200_OK)


@api_view(["DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def delete_judge(request, judge_id):
    try:
        judge = get_object_or_404(Judge, id=judge_id)
        scoresheet_mappings = MapScoresheetToTeamJudge.objects.filter(judgeid=judge_id)
        scoresheet_ids = scoresheet_mappings.values_list('scoresheetid', flat=True)
        scoresheets = Scoresheet.objects.filter(id__in=scoresheet_ids)
        user_mapping_qs = MapUserToRole.objects.filter(role=3, relatedid=judge_id)
        user = None
        if user_mapping_qs.exists():
            # In rare cases there might be multiple stale rows; use the first safely
            user = User.objects.filter(id=user_mapping_qs.first().uuid).first()
        # There can be zero, one, or many cluster mappings; handle all robustly
        cluster_mappings_qs = MapJudgeToCluster.objects.filter(judgeid=judge_id)
        teams_mappings = MapScoresheetToTeamJudge.objects.filter(judgeid=judge_id)
        contest_mapping = MapContestToJudge.objects.filter(judgeid=judge_id)

        # Invalidate all active sessions for this user before deleting user
        if user:
            _delete_user_sessions(user.id)

        # delete associated user
        if user:
            user.delete()
        if user_mapping_qs.exists():
            user_mapping_qs.delete()

        # delete associated scoresheets
        for scoresheet in scoresheets:
            scoresheet.delete()

        # delete associated judge-teams mappings
        for mapping in teams_mappings:
            mapping.delete()

        # delete associated judge-contest mapping
        contest_mapping.delete()

        # delete associated judge-cluster mapping(s)
        if cluster_mappings_qs.exists():
            cluster_mappings_qs.delete()

        # delete the judge
        judge.delete()

        return Response({"detail": "Judge deleted successfully."}, status=status.HTTP_200_OK)

    except ValidationError as e:  # Catching ValidationErrors specifically
        return Response({"errors": e.detail}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def create_judge_instance(judge_data):
    serializer = JudgeSerializer(data=judge_data)
    if serializer.is_valid():
        serializer.save()
        return serializer.data
    raise ValidationError(serializer.errors)


def create_user_and_judge(data):
    # IMPORTANT: Judges use ONLY the shared judge password (role=3)
    # Check for duplicate account before creating
    username = data.get("username")
    if username:
        existing_user = User.objects.filter(username=username).first()
        if existing_user:
            # Check if this user already has a judge role mapping
            existing_judge_mapping = MapUserToRole.objects.filter(
                uuid=existing_user.id,
                role=3  # Judge role
            ).first()
            if existing_judge_mapping:
                # Get judge details for better error message
                try:
                    existing_judge = Judge.objects.get(id=existing_judge_mapping.relatedid)
                    raise ValidationError({"detail": f'An account already exists under the name "{existing_judge.first_name} {existing_judge.last_name}" with username "{username}".'})
                except Judge.DoesNotExist:
                    raise ValidationError({"detail": f'An account already exists with username "{username}".'})
    
    user_data = {"username": data["username"], "password": data["password"]}
    user_response = create_user(user_data, send_email=False, enforce_unusable_password=True)
    if not user_response.get('user'):
        raise ValidationError({"detail": "User creation failed."})

    # (Email intentionally NOT sent for judges)

    judge_data = {
        "first_name": data["first_name"],
        "last_name": data["last_name"],
        "phone_number": data["phone_number"],
        "contestid": data["contestid"],
        "presentation": data["presentation"],
        "mdo": data["mdo"],
        "journal": data["journal"],
        "runpenalties": data["runpenalties"],
        "otherpenalties": data["otherpenalties"],
        # new optional flags
        "redesign": data.get("redesign", False),
        "championship": data.get("championship", False),
        "role": data["role"]
    }
    judge_response = create_judge_instance(judge_data)
    if not judge_response.get('id'):
        raise ValidationError('Judge creation failed.')
    return user_response, judge_response


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def are_all_score_sheets_submitted(request):
    """
    Check if all score sheets assigned to a list of judges are submitted.
    Expects a JSON body with a list of judge objects.
    Optional query param: ?cluster_id=<id> to restrict to that cluster's teams.
    """
    judges = request.data

    if not judges:
        return Response({"detail": "No judges provided."}, status=status.HTTP_400_BAD_REQUEST)

    results = {}

    # Optional filter by cluster
    cluster_id = request.query_params.get('cluster_id')
    team_ids = None
    if cluster_id:
        from ..models import MapClusterToTeam
        team_ids = list(MapClusterToTeam.objects.filter(clusterid=cluster_id).values_list('teamid', flat=True))

    for judge in judges:
        judge_id = judge.get('id')

        if team_ids is not None:
            mappings = MapScoresheetToTeamJudge.objects.filter(judgeid=judge_id, teamid__in=team_ids)
        else:
            mappings = MapScoresheetToTeamJudge.objects.filter(judgeid=judge_id)

        if not mappings.exists():
            results[judge_id] = False
            continue

        required_sheet_ids = [m.scoresheetid for m in mappings]
        if not required_sheet_ids:
            results[judge_id] = True
            continue

        all_submitted = not Scoresheet.objects.filter(
            id__in=required_sheet_ids,
            isSubmitted=False
        ).exists()
        results[judge_id] = all_submitted

    return Response(results, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def judge_disqualify_team(request):
    team = get_object_or_404(Teams, id=request.data["teamid"])
    team.judge_disqualified = request.data["judge_disqualified"]
    team.save()
    return Response(status=status.HTTP_200_OK)


def sync_judge_sheet_flags(judge_id):
    """
    Sync the judge's global sheet flags based on all their cluster assignments.
    A sheet flag should be True if the judge has that sheet type enabled in ANY of their cluster assignments.
    """
    try:
        judge = Judge.objects.get(id=judge_id)

        # Get all cluster assignments for this judge
        assignments = MapJudgeToCluster.objects.filter(judgeid=judge_id)

        # Aggregate all sheet types across all assignments
        has_presentation = assignments.filter(presentation=True).exists()
        has_journal = assignments.filter(journal=True).exists()
        has_mdo = assignments.filter(mdo=True).exists()
        has_runpenalties = assignments.filter(runpenalties=True).exists()
        has_otherpenalties = assignments.filter(otherpenalties=True).exists()
        has_redesign = assignments.filter(redesign=True).exists()
        has_championship = assignments.filter(championship=True).exists()

        # Update judge flags
        judge.presentation = has_presentation
        judge.journal = has_journal
        judge.mdo = has_mdo
        judge.runpenalties = has_runpenalties
        judge.otherpenalties = has_otherpenalties
        judge.redesign = has_redesign
        judge.championship = has_championship
        judge.save()

    except Judge.DoesNotExist:
        pass  # Judge doesn't exist, nothing to sync
    except Exception as e:
        # Log error but don't fail the operation
        print(f"Error syncing judge sheet flags for judge {judge_id}: {str(e)}")


@api_view(["GET"])
def get_all_judges(request):
    """Get all judges"""
    try:
        judges = Judge.objects.all()
        serializer = JudgeSerializer(judges, many=True)
        return Response({"Judges": serializer.data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
