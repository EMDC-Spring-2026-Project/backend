import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest import skipUnless

from django.contrib.auth.models import User
from django.test import Client, LiveServerTestCase
from django.utils.crypto import get_random_string

from ..models import (
    Contest, Judge, MapContestToJudge, MapContestToTeam, MapScoresheetToTeamJudge,
    MapUserToRole, Scoresheet, ScoresheetEnum, Teams,
)
from ..views import scoresheets


@skipUnless(os.environ.get("EMDC_LOAD_TEST") == "1", "Opt-in load test")
class LocalSubmissionLoad(LiveServerTestCase):
    def test_submission_burst_with_public_readers(self):
        contest = Contest.objects.create(
            name="Load test", date=date.today(), is_open=True, is_tabulated=False
        )
        teams = [Teams.objects.create(team_name=f"Team {i}") for i in range(24)]
        for team in teams:
            MapContestToTeam.objects.create(contestid=contest.id, teamid=team.id)
        submit_url = self.live_server_url + "/api/scoreSheet/edit/"
        read_url = self.live_server_url + f"/api/mapping/teamToContest/getTeamsByContest/{contest.id}/"
        groups = []
        for i in range(24):
            judge = Judge.objects.create(first_name="Test", last_name=str(i), contestid=contest.id)
            user = User.objects.create_user(username=f"judge{i}")
            MapUserToRole.objects.create(uuid=user.id, role=3, relatedid=judge.id)
            MapContestToJudge.objects.create(contestid=contest.id, judgeid=judge.id)
            client = Client()
            client.force_login(user)
            csrf = get_random_string(32)
            headers = {
                "Cookie": f"sessionid={client.cookies['sessionid'].value}; csrftoken={csrf}",
                "X-CSRFToken": csrf,
                "Content-Type": "application/json",
            }
            requests = []
            for offset in range(6):
                team = teams[(i + offset) % len(teams)]
                sheet = Scoresheet.objects.create(
                    sheetType=ScoresheetEnum.PRESENTATION, isSubmitted=False
                )
                MapScoresheetToTeamJudge.objects.create(
                    teamid=team.id, judgeid=judge.id, scoresheetid=sheet.id, sheetType=sheet.sheetType
                )
                payload = {"id": sheet.id, "isSubmitted": True}
                payload.update({f"field{number}": 1 for number in range(1, 9)})
                requests.append(Request(submit_url, json.dumps(payload).encode(), headers))
            groups.append(requests)

        def send(request):
            try:
                with urlopen(request, timeout=20) as response:
                    return response.status
            except HTTPError as error:
                return error.code
            except (OSError, TimeoutError) as error:
                return type(error).__name__

        def read_results():
            statuses = []
            while time.monotonic() < deadline:
                statuses.append(send(read_url))
                time.sleep(2)
            return statuses

        deadline = time.monotonic() + 25
        try:
            with ThreadPoolExecutor(max_workers=124) as pool:
                reads = [pool.submit(read_results) for _ in range(100)]
                writes = [pool.submit(lambda group=group: [send(req) for req in group]) for group in groups]
                submit_status = Counter(code for future in writes for code in future.result())
                read_status = Counter(code for future in reads for code in future.result())
            print(f"SUBMITS {submit_status}; READS {read_status}", flush=True)
            self.assertEqual(submit_status, {200: 144})
            self.assertEqual(set(read_status), {200})
            self.assertEqual(Scoresheet.objects.filter(isSubmitted=True).count(), 144)
        finally:
            worker = scoresheets._tabulation_worker
            if worker is not None:
                worker.join(timeout=20)
