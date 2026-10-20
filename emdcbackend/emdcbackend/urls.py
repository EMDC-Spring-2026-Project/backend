from django.urls import path
from .auth import views

# Added password-set/reset endpoints 
from .auth.password_views import (
    request_set_password,
    request_password_reset,
    validate_password_token,
    complete_password_set,
)

from .views.Maps.MapClusterToContest import all_clusters_by_contest_id
from .views.Maps.MapClusterToTeam import (
    create_cluster_team_mapping, delete_cluster_team_mapping_by_id,
    teams_by_cluster_id, cluster_by_team_id, get_teams_by_cluster_rank, teams_by_judge_id)
from .views.Maps.MapScoreSheet import create_score_sheet_mapping, score_sheet_by_judge_team, \
    delete_score_sheet_mapping_by_id, score_sheets_by_judge, score_sheets_by_judge_and_cluster, submit_all_penalty_sheets_for_judge, all_sheets_submitted_for_contests, all_submitted_for_team
from .views.judge import create_judge, judge_by_id, edit_judge, delete_judge, are_all_score_sheets_submitted, judge_disqualify_team, get_all_judges
from .views.organizer import create_organizer, organizer_by_id, edit_organizer, delete_organizer, \
    organizer_disqualify_team, get_all_organizers

from .views.coach import create_coach, coach_by_id, edit_coach, delete_coach, coach_get_all
from .views.contest import contest_by_id, contest_get_all, create_contest, edit_contest, delete_contest
from .views.team import (
    create_team, team_by_id, edit_team, delete_team_by_id, get_teams_by_team_rank,
    create_team_after_judge, is_team_disqualified, get_all_teams
)
from .views.Maps.MapCoachToTeam import (
    create_coach_team_mapping, coach_by_team_id, delete_coach_team_mapping_by_id,
    teams_by_coach_id, coaches_by_teams
)
from .views.clusters import cluster_by_id, create_cluster, clusters_get_all, delete_cluster, edit_cluster
from .views.Maps.MapContestToJudge import create_contest_judge_mapping, get_all_judges_by_contest_id, get_contest_id_by_judge_id, delete_contest_judge_mapping_by_id
from .views.Maps.AssignJudgeToContest import assign_judge_to_contest, get_judge_contests, remove_judge_from_contest, remove_judge_from_cluster
from .views.Maps.MapContestToOrganizer import create_contest_organizer_mapping, get_organizers_by_contest_id, get_contests_by_organizer_id, delete_contest_organizer_mapping, \
    get_all_contests_by_organizer, get_organizer_names_by_contests
from .views.Maps.MapContestToTeam import create_contest_team_mapping, get_teams_by_contest_id, \
    get_contest_id_by_team_id, delete_contest_team_mapping_by_id, get_contests_by_team_ids

from .views.scoresheets import (
    create_score_sheet, edit_score_sheet, scores_by_id, delete_score_sheet,
    edit_score_sheet_field, update_scores, get_scoresheet_details_by_team, get_scoresheet_details_for_contest,  multi_team_general_penalties, multi_team_run_penalties
)
from .views.admin import create_admin, admins_get_all, admin_by_id, delete_admin, edit_admin
from .views.Maps.MapUserToRole import create_user_role_mapping, delete_user_role_mapping, get_user_by_role
from .views.Maps.MapClusterToJudge import create_cluster_judge_mapping, delete_cluster_judge_mapping_by_id, cluster_by_judge_id, judges_by_cluster_id, all_clusters_by_judge_id
from .views.tabulation import tabulate_scores, preliminary_results, championship_results, redesign_results, set_advancers, list_advancers
from .views.advance import advance_to_championship, undo_championship_advancement
from .views.Maps.MapAwardToTeam import create_award_team_mapping, get_award_id_by_team_id, delete_award_team_mapping_by_id, update_award_team_mapping, get_all_awards, get_awards_by_role
from .views.Maps.MapBallotToVote import create_map_ballot_to_vote
from .views.Maps.MapTeamToVote import create_map_team_to_vote
from .views.Maps.MapVoteToAward import create_map_vote_to_award, create_map_award_to_contest
from .views.votes import create_vote, get_all_votes
from .views.ballot import create_ballot, get_all_ballots, delete_ballot
from django.urls import path
from .auth.views import login_view, logout_view, csrf_view


# Added shared-password API import 
from .views.shared_passwords import set_shared_password

urlpatterns = [
    # Admins
    path('api/admin/get/<int:admin_id>/', admin_by_id, name='admin_by_id'),
    path('api/admin/getAll/', admins_get_all, name='admins_get_all'),
    path('api/admin/create/', create_admin, name='create_admin'),
    path('api/admin/edit/', edit_admin, name='edit_admin'),
    path('api/admin/delete/<int:admin_id>/', delete_admin, name='delete_admin'),

    # Authentication
    path('api/login/', login_view, name='login'),
    path('api/logout/', logout_view, name='logout'),
    path('api/auth/csrf/', csrf_view, name='csrf'),
    path('api/signup/', views.signup, name='signup'),
    path('api/testToken/', views.test_token, name='test_token'),

    # Added password set/reset endpoints 
    path('api/auth/send-set-password/', request_set_password, name='request_set_password'),
    path('api/auth/forgot-password/', request_password_reset, name='request_password_reset'),
    path('api/auth/password-token/validate/', validate_password_token, name='validate_password_token'),
    path('api/auth/password/complete/', complete_password_set, name='complete_password_set'),

    # Added global shared password set API 
    path('api/auth/set-shared-password/', set_shared_password, name='set_shared_password'),

    # Users
    path('api/user/get/<int:user_id>/', views.user_by_id, name='user_by_id'),
    path('api/user/edit/', views.edit_user, name='edit_user'),
    path('api/user/delete/<int:user_id>/', views.delete_user_by_id, name='delete_user_by_id'),

    # Judges
    path('api/judge/get/<int:judge_id>/', judge_by_id, name='judge_by_id'),
    path('api/judge/getAll/', get_all_judges, name='get_all_judges'),
    path('api/judge/create/', create_judge, name='create_judge'),
    path('api/judge/edit/', edit_judge, name='edit_judge'),
    path('api/judge/delete/<int:judge_id>/', delete_judge, name='delete_judge'),
    path('api/judge/allScoreSheetsSubmitted/', are_all_score_sheets_submitted, name='are_all_score_sheets_submitted'),
    path('api/judge/disqualifyTeam/', judge_disqualify_team, name='judge_disqualify_team'),

    # Organizers
    path('api/organizer/get/<int:organizer_id>/', organizer_by_id, name='organizer_by_id'),
    path('api/organizer/create/', create_organizer, name='create_organizer'),
    path('api/organizer/edit/', edit_organizer, name='edit_organizer'),
    path('api/organizer/delete/<int:organizer_id>/', delete_organizer, name='delete_organizer'),
    path('api/organizer/disqualifyTeam/', organizer_disqualify_team, name='organizer_disqualify_team'),
    path('api/organizer/getAll/', get_all_organizers, name='get_all_organizers'),

    # Coaches
    path('api/coach/get/<int:coach_id>/', coach_by_id, name='coach_by_id'),
    path('api/coach/getAll/', coach_get_all, name='coach_get_all'),
    path('api/coach/create/', create_coach, name='create_coach'),
    path('api/coach/edit/', edit_coach, name='edit_coach'),
    path('api/coach/delete/<int:coach_id>/', delete_coach, name='delete_coach'),

    # Teams
    path('api/team/get/<int:team_id>/', team_by_id, name='team_by_id'),
    path('api/team/create/', create_team, name='create_team'),
    path('api/team/createAfterJudge/', create_team_after_judge, name='create_team_after_judge'),
    path('api/team/edit/', edit_team, name='edit_team'),
    path('api/team/delete/<int:team_id>/', delete_team_by_id, name='delete_team_by_id'),
    path('api/team/rankedteams/', get_teams_by_team_rank, name='get_teams_by_team_rank'),
    path('api/team/isDisqualified/<int:team_id>/', is_team_disqualified, name='is_team_disqualified'),
    path('api/team/getAllTeams/', get_all_teams, name='get_all_teams'),

    # Maps
    path('api/mapping/coachToTeam/create/', create_coach_team_mapping, name='create_coach_team_mapping'),
    path('api/mapping/coachToTeam/getCoachByTeam/<int:team_id>/', coach_by_team_id, name='coach_by_team_id'),
    path('api/mapping/coachToTeam/delete/<int:map_id>/', delete_coach_team_mapping_by_id, name='delete_coach_team_mapping'),
    path('api/mapping/coachToTeam/teamsByCoach/<int:coach_id>/', teams_by_coach_id, name='teams_by_coach_id'),
    path('api/mapping/coachToTeam/coachesByTeams/', coaches_by_teams, name='coaches_by_teams'),

    path('api/mapping/contestToJudge/create/', create_contest_judge_mapping, name='create_contest_judge_mapping'),
    path('api/mapping/contestToJudge/getContestByJudge/<int:judge_id>/', get_contest_id_by_judge_id, name='get_contest_id_by_judge_id'),
    path('api/mapping/contestToJudge/delete/<int:map_id>/', delete_contest_judge_mapping_by_id, name='delete_contest_judge_mapping'),
    
    # Multi-contest judge assignment endpoints
    path('api/mapping/contestToJudge/assign/', assign_judge_to_contest, name='assign_judge_to_contest'),
    path('api/mapping/contestToJudge/judge-contests/<int:judge_id>/', get_judge_contests, name='get_judge_contests'),
    path('api/mapping/contestToJudge/remove/<int:judge_id>/<int:contest_id>/', remove_judge_from_contest, name='remove_judge_from_contest'),
    path('api/mapping/clusterToJudge/remove/<int:judge_id>/<int:cluster_id>/', remove_judge_from_cluster, name='remove_judge_from_cluster'),

    path('api/mapping/contestToTeam/create/', create_contest_team_mapping, name='create_contest_team_mapping'),
    path('api/mapping/contestToTeam/getContestByTeam/<int:team_id>/', get_contest_id_by_team_id, name='get_contest_id_by_team_id'),
    path('api/mapping/contestToTeam/delete/<int:map_id>/', delete_contest_team_mapping_by_id, name='delete_contest_team_mapping'),
    path('api/mapping/contestToTeam/contestsByTeams/', get_contests_by_team_ids, name='get_contests_by_team_ids'),

    path('api/mapping/contestToOrganizer/create/', create_contest_organizer_mapping, name='create_contest_organizer_mapping'),
    path('api/mapping/contestToOrganizer/getByOrganizer/<int:organizer_id>/', get_contests_by_organizer_id, name='get_contests_by_organizer_id'),
    path('api/mapping/contestToOrganizer/delete/<int:organizer_id>/<int:contest_id>/', delete_contest_organizer_mapping, name='delete_contest_organizer_mapping'),
    path('api/mapping/contestToOrganizer/getAllContestsPerOrganizer/', get_all_contests_by_organizer, name='get_all_contests_by_organizer'),
    path('api/mapping/contestToOrganizer/getOrganizerNames/', get_organizer_names_by_contests, name='get_organizer_names_by_contests'),
    path('api/mapping/organizerToContest/getOrganizersByContest/<int:contest_id>/', get_organizers_by_contest_id, name='get_organizers_by_contest_id'),

    path('api/mapping/judgeToContest/getAllJudges/<int:contest_id>/', get_all_judges_by_contest_id, name='get_all_judges_by_contest_id'),
    path('api/mapping/teamToContest/getTeamsByContest/<int:contest_id>/', get_teams_by_contest_id, name='get_teams_by_contest_id'),

    path('api/mapping/userToRole/create/', create_user_role_mapping, name='create_user_role_mapping'),
    path('api/mapping/userToRole/delete/<int:mapping_id>/', delete_user_role_mapping, name='delete_user_role_mapping'),
    path('api/mapping/userToRole/getUserByRole/<int:relatedid>/<int:roleType>/', get_user_by_role, name='get_user_by_role'),

    path('api/mapping/clusterToTeam/create/', create_cluster_team_mapping, name='create_cluster_team_mapping'),
    path('api/mapping/clusterToTeam/delete/<int:map_id>/', delete_cluster_team_mapping_by_id, name='delete_cluster_team_mapping'),
    path('api/mapping/clusterToTeam/getAllTeamsByCluster/<int:cluster_id>/', teams_by_cluster_id, name='teams_by_cluster'),
    path('api/mapping/clusterToTeam/getClusterByTeam/<int:team_id>/', cluster_by_team_id, name='cluster_by_team'),
    path('api/mapping/clusterToTeam/getTeamsByClusterRank/', get_teams_by_cluster_rank, name='get_teams_by_cluster_rank'),
    path('api/mapping/clusterToTeam/getTeamsByJudge/<int:judge_id>/', teams_by_judge_id, name='teams_by_judge'),

    path('api/mapping/clusterToJudge/create/', create_cluster_judge_mapping, name='create_cluster_judge_mapping'),
    path('api/mapping/clusterToJudge/delete/<int:map_id>/', delete_cluster_judge_mapping_by_id, name='delete_cluster_judge_mapping'),
    path('api/mapping/clusterToJudge/getAllJudgesByCluster/<int:cluster_id>/', judges_by_cluster_id, name='judges_by_cluster'),
    path('api/mapping/clusterToJudge/getClusterByJudge/<int:judge_id>/', cluster_by_judge_id, name='cluster_by_judge'),
    path('api/mapping/clusterToJudge/getAllClustersByJudge/<int:judge_id>/', all_clusters_by_judge_id, name='all_clusters_by_judge'),

    path('api/mapping/clusterToContest/getAllClustersByContest/<int:contest_id>/', all_clusters_by_contest_id, name='all_clusters_by_contest_id'),

    path('api/mapping/scoreSheet/create/', create_score_sheet_mapping, name='create_score_sheet_mapping'),
    path('api/mapping/scoreSheet/getByTeamJudge/<int:sheetType>/<int:judge_id>/<int:team_id>/', score_sheet_by_judge_team, name='score_sheets_by_judge_team'),
    path('api/mapping/scoreSheet/delete/<int:map_id>/', delete_score_sheet_mapping_by_id, name='delete_score_sheet_mapping_by_id'),
    path('api/mapping/scoreSheet/getSheetsByJudge/<int:judge_id>/', score_sheets_by_judge, name='score_sheets_by_judge'),
    path('api/mapping/scoreSheet/getSheetsByJudgeAndCluster/<int:judge_id>/<int:cluster_id>/', score_sheets_by_judge_and_cluster, name='score_sheets_by_judge_and_cluster'),
    path('api/mapping/scoreSheet/submitAllPenalties/', submit_all_penalty_sheets_for_judge, name='submit_all_penalty_sheets_for_judge'),
    path('api/mapping/scoreSheet/allSheetsSubmittedForContests/', all_sheets_submitted_for_contests, name="all_sheets_submitted_for_contests"),
    path('api/mapping/scoreSheet/allSubmittedForTeam/<int:team_id>/', all_submitted_for_team, name='all_submitted_for_team'),

    # Clusters
    path('api/cluster/get/<int:cluster_id>/', cluster_by_id, name='cluster_by_id'),
    path('api/cluster/getAll/', clusters_get_all, name='clusters_get_all'),
    path('api/cluster/create/', create_cluster, name='create_cluster'),
    path('api/cluster/edit/', edit_cluster, name='edit_cluster'),
    path('api/cluster/delete/<int:cluster_id>/', delete_cluster, name='delete_cluster'),

    # Contests
    path('api/contest/get/<int:contest_id>/', contest_by_id, name='contest_by_id'),
    path('api/contest/getAll/', contest_get_all, name='contest_get_all'),
    path('api/contest/create/', create_contest, name='create_contest'),
    path('api/contest/edit/', edit_contest, name='edit_contest'),
    path('api/contest/delete/<int:contest_id>/', delete_contest, name='delete_contest'),

    # ScoreSheets
    path('api/scoreSheet/get/<int:scores_id>/', scores_by_id, name='scores_by_id'),
    path('api/scoreSheet/create/', create_score_sheet, name='create_score_sheets'),
    path('api/scoreSheet/edit/', edit_score_sheet, name='edit_score_sheets'),
    path('api/scoreSheet/delete/<int:scores_id>/', delete_score_sheet, name='delete_score_sheets'),
    path('api/scoreSheet/edit/editField/', edit_score_sheet_field, name='edit_score_sheet_field'),
    path('api/scoreSheet/edit/updateScores/', update_scores, name='update_scores'),
    path('api/scoreSheet/getDetails/<int:team_id>/', get_scoresheet_details_by_team, name='get_score_sheets_by_team_id'),
    path('api/scoreSheet/getMasterDetails/', get_scoresheet_details_for_contest, name='get_scoresheet_details_for_contest'),
    path('api/scoreSheet/multiTeamGeneralPenalties/<int:judge_id>/<int:contest_id>/', multi_team_general_penalties, name='multi_team_general_penalties'),
    path('api/scoreSheet/multiTeamRunPenalties/<int:judge_id>/<int:contest_id>/', multi_team_run_penalties, name='multi_team_run_penalties'),

    # Tabulation
    path('api/tabulation/tabulateScores/', tabulate_scores, name='tabulate_scores'),
    path('api/tabulation/preliminaryResults/', preliminary_results, name='preliminary_results'),

    # advancement endpoints
    path('api/tabulation/championshipResults/', championship_results, name='championship_results'),
    path('api/tabulation/redesignResults/', redesign_results, name='redesign_results'),
    path('api/tabulation/setAdvancers/', set_advancers, name='set_advancers'),
    path('api/tabulation/listAdvancers/', list_advancers, name='list_advancers'),
    path('api/advance/advanceToChampionship/', advance_to_championship, name='advance_to_championship'),
    path('api/advance/undoChampionshipAdvancement/', undo_championship_advancement, name='undo_championship_advancement'),

    # Special Awards
    path('api/mapping/awardToTeam/getAllAwards/', get_all_awards, name='get_all_awards'),
    path('api/mapping/awardToTeam/create/', create_award_team_mapping, name='create_award_team_mapping'),
    path('api/mapping/awardToTeam/getAwardByTeam/<int:team_id>/', get_award_id_by_team_id, name='get_award_id_by_team_id'),
    path('api/mapping/awardToTeam/delete/<int:team_id>/<str:award_name>/', delete_award_team_mapping_by_id, name='delete_award_team_mapping_by_id'),
    path('api/mapping/awardToTeam/update/<int:team_id>/<str:award_name>/', update_award_team_mapping, name='update_award_team_mapping'),
    path('api/mapping/awardToTeam/getAwardByRole/<str:isJudge>/', get_awards_by_role, name='get_awards_by_role'),

    # Ballots
    path('api/ballot/create/', create_ballot, name='create_ballot'),
    path('api/ballot/getAll/', get_all_ballots, name='get_all_ballots'),
    path('api/ballot/delete/<int:ballot_id>/', delete_ballot, name='delete_ballot'),

    # Votes
    path('api/vote/create/', create_vote, name='create_vote'),
    path('api/vote/getAll/', get_all_votes, name='get_all_votes'),

    # Mapping ballot/vote/award
    path('api/map/ballotToVote/create/', create_map_ballot_to_vote, name='create_map_ballot_to_vote'),
    path('api/map/voteToAward/create/', create_map_vote_to_award, name='create_map_vote_to_award'),
    path('api/map/teamToVote/create/', create_map_team_to_vote, name='create_map_team_to_vote'),
    path('api/map/awardToContest/create/', create_map_award_to_contest, name='create_map_award_to_contest'),
]
