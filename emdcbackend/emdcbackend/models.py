from django.db import models
from django.core.exceptions import ValidationError as ModelValidationError


class Contest(models.Model):
    name = models.CharField(max_length=99)
    date = models.DateField()
    is_open = models.BooleanField()
    is_tabulated = models.BooleanField()

    def __str__(self):
        return f"{self.id} - {self.name}"


class MapContestToJudge(models.Model):
    contestid = models.IntegerField(db_index=True)
    judgeid = models.IntegerField(db_index=True)


class MapContestToTeam(models.Model):
    contestid = models.IntegerField(db_index=True)
    teamid = models.IntegerField(db_index=True)


class MapContestToOrganizer(models.Model):
    contestid = models.IntegerField(db_index=True)
    organizerid = models.IntegerField(db_index=True)


class MapContestToCluster(models.Model):
    contestid = models.IntegerField(db_index=True)
    clusterid = models.IntegerField(db_index=True)


class Judge(models.Model):
    class JudgeRoleEnum(models.IntegerChoices):
        LEAD = 1
        TECHNICAL = 2
        GENERAL = 3
        JOURNAL = 4

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=20)
    contestid = models.IntegerField(db_index=True)
    presentation=models.BooleanField(default=False)
    mdo=models.BooleanField(default=False)
    journal=models.BooleanField(default=False)
    runpenalties=models.BooleanField(default=False)
    otherpenalties=models.BooleanField(default=False)
    redesign=models.BooleanField(default=False)
    championship=models.BooleanField(default=False)
    role = models.IntegerField(choices=JudgeRoleEnum.choices, null=True, blank=True)

    def __str__(self):
        return f"{self.id} - {self.first_name} {self.last_name}"


class MapJudgeToCluster(models.Model):
    judgeid = models.IntegerField(db_index=True)
    clusterid = models.IntegerField(db_index=True)
    contestid = models.IntegerField(null=True, blank=True, db_index=True)
    presentation = models.BooleanField(default=False)
    mdo = models.BooleanField(default=False)
    journal = models.BooleanField(default=False)
    runpenalties = models.BooleanField(default=False)
    otherpenalties = models.BooleanField(default=False)
    redesign = models.BooleanField(default=False)
    championship = models.BooleanField(default=False)

    class Meta:
        unique_together = ("judgeid", "clusterid")


class JudgeClusters(models.Model):
    cluster_name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    cluster_type = models.CharField(max_length=20, default='preliminary', choices=[
        ('preliminary', 'Preliminary'),
        ('championship', 'Championship'),
        ('redesign', 'Redesign')
    ])

    def __str__(self):
        return f"{self.id} - {self.cluster_name}"


class MapClusterToTeam(models.Model):
    clusterid = models.IntegerField(db_index=True)
    teamid = models.IntegerField(db_index=True)


class Teams(models.Model):
    team_name = models.CharField(max_length=99)
    school_name = models.CharField(max_length=255, default='MNSU')
    journal_score = models.FloatField(default=0.0)
    presentation_score = models.FloatField(default=0.0)
    machinedesign_score = models.FloatField(default=0.0)
    penalties_score = models.FloatField(default=0.0)
    redesign_score = models.FloatField(default=0.0)
    total_score = models.FloatField(default=0.0)
    championship_score = models.FloatField(default=0.0)
    team_rank = models.IntegerField(null=True,blank=True)
    cluster_rank = models.IntegerField(null=True,blank=True)
    judge_disqualified = models.BooleanField(default=False)
    organizer_disqualified = models.BooleanField(default=False)

    # multi-round flags/results
    advanced_to_championship = models.BooleanField(default=False)
    championship_rank = models.IntegerField(null=True, blank=True)
    
    # Preliminary results storage (preserved when advancing)
    preliminary_presentation_score = models.FloatField(default=0.0)
    preliminary_journal_score = models.FloatField(default=0.0)
    preliminary_machinedesign_score = models.FloatField(default=0.0)
    preliminary_penalties_score = models.FloatField(default=0.0)
    preliminary_total_score = models.FloatField(default=0.0)
    
    # Championship results storage
    championship_presentation_score = models.FloatField(default=0.0)
    championship_machinedesign_score = models.FloatField(default=0.0)
    championship_penalties_score = models.FloatField(default=0.0)
    championship_general_penalties_score = models.FloatField(default=0.0)
    championship_run_penalties_score = models.FloatField(default=0.0)
    championship_score = models.FloatField(default=0.0)
    
    # Redesign results storage
    redesign_score = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.id} - {self.team_name}"
    def save(self, *args, **kwargs):
        if not self.team_name or not str(self.team_name).strip():
            raise ValueError("team_name is required and cannot be empty or whitespace.")
        super().save(*args, **kwargs)


class MapUserToRole(models.Model):
    class RoleEnum(models.IntegerChoices):
        ADMIN = 1
        ORGANIZER = 2
        JUDGE = 3
        COACH = 4

    role = models.IntegerField(choices=RoleEnum.choices)
    uuid = models.IntegerField()
    relatedid = models.IntegerField()


class Coach(models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)


class Admin(models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)


class MapCoachToTeam(models.Model):
    teamid = models.IntegerField()
    coachid = models.IntegerField()


class Organizer(models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)


class ScoresheetEnum(models.IntegerChoices):
    PRESENTATION = 1
    JOURNAL = 2
    MACHINEDESIGN = 3
    RUNPENALTIES = 4
    OTHERPENALTIES = 5
    REDESIGN = 6
    CHAMPIONSHIP = 7

class Scoresheet(models.Model):
    sheetType = models.IntegerField(choices=ScoresheetEnum.choices)
    isSubmitted = models.BooleanField()
    field1 = models.FloatField(null=True, blank=True)
    field2 = models.FloatField(null=True, blank=True)
    field3 = models.FloatField(null=True, blank=True)
    field4 = models.FloatField(null=True, blank=True)
    field5 = models.FloatField(null=True, blank=True)
    field6 = models.FloatField(null=True, blank=True)
    field7 = models.FloatField(null=True, blank=True)
    field8 = models.FloatField(null=True, blank=True)
    field9 = models.CharField(null=True, blank=True, max_length=500)
    field10 = models.FloatField(null=True, blank=True)
    field11 = models.FloatField(null=True, blank=True)
    field12 = models.FloatField(null=True, blank=True)
    field13 = models.FloatField(null=True, blank=True)
    field14 = models.FloatField(null=True, blank=True)
    field15 = models.FloatField(null=True, blank=True)
    field16 = models.FloatField(null=True, blank=True)
    field17 = models.FloatField(null=True, blank=True)
    field18 = models.CharField(null=True, blank=True, max_length=500)
    # Championship penalty fields (19-42)
    field19 = models.FloatField(null=True, blank=True)
    field20 = models.FloatField(null=True, blank=True)
    field21 = models.FloatField(null=True, blank=True)
    field22 = models.FloatField(null=True, blank=True)
    field23 = models.FloatField(null=True, blank=True)
    field24 = models.FloatField(null=True, blank=True)
    field25 = models.FloatField(null=True, blank=True)
    field26 = models.FloatField(null=True, blank=True)
    field27 = models.FloatField(null=True, blank=True)
    field28 = models.FloatField(null=True, blank=True)
    field29 = models.FloatField(null=True, blank=True)
    field30 = models.FloatField(null=True, blank=True)
    field31 = models.FloatField(null=True, blank=True)
    field32 = models.FloatField(null=True, blank=True)
    field33 = models.FloatField(null=True, blank=True)
    field34 = models.FloatField(null=True, blank=True)
    field35 = models.FloatField(null=True, blank=True)
    field36 = models.FloatField(null=True, blank=True)
    field37 = models.FloatField(null=True, blank=True)
    field38 = models.FloatField(null=True, blank=True)
    field39 = models.FloatField(null=True, blank=True)
    field40 = models.FloatField(null=True, blank=True)
    field41 = models.FloatField(null=True, blank=True)
    field42 = models.FloatField(null=True, blank=True)

    def clean(self):
        if self.sheetType == ScoresheetEnum.RUNPENALTIES:
            required_fields = {
                'field1': 'Field 1 is required for PENALTIES.',
                'field2': 'Field 2 is required for PENALTIES.',
                'field3': 'Field 3 is required for PENALTIES.',
                'field4': 'Field 4 is required for PENALTIES.',
                'field5': 'Field 5 is required for PENALTIES.',
                'field6': 'Field 6 is required for PENALTIES.',
                'field7': 'Field 7 is required for PENALTIES.',
                'field8': 'Field 8 is required for PENALTIES.',
                'field10': 'Field 10 is required for PENALTIES.',
                'field11': 'Field 11 is required for PENALTIES.',
                'field12': 'Field 12 is required for PENALTIES.',
                'field13': 'Field 13 is required for PENALTIES.',
                'field14': 'Field 14 is required for PENALTIES.',
                'field15': 'Field 15 is required for PENALTIES.',
                'field16': 'Field 16 is required for PENALTIES.',
                'field17': 'Field 17 is required for PENALTIES.',
            }
            errors = {}
            for field, error_message in required_fields.items():
                if getattr(self, field) is None:
                    errors[field] = error_message
            if errors:
                raise ModelValidationError(errors)
        elif self.sheetType in (ScoresheetEnum.OTHERPENALTIES, ScoresheetEnum.REDESIGN):
            required_fields = ['field1', 'field2', 'field3', 'field4', 'field5', 'field6', 'field7']
            for field in required_fields:
                if getattr(self, field) is None:
                    raise ModelValidationError({field: f'{field.capitalize()} is required.'})
        elif self.sheetType == ScoresheetEnum.CHAMPIONSHIP:
            # Championship: Machine Design fields 1-8, Presentation fields 10-17 required
            # Comment fields 9, 18 are optional
            required_fields = ['field1', 'field2', 'field3', 'field4', 'field5', 'field6', 'field7', 'field8',
                             'field10', 'field11', 'field12', 'field13', 'field14', 'field15', 'field16', 'field17']
            for field in required_fields:
                if getattr(self, field) is None:
                    raise ModelValidationError({field: f'{field.capitalize()} is required for Championship.'})
        else:
            # Presentation / Journal / Machine Design: fields 1..8 required
            required_fields = ['field1', 'field2', 'field3', 'field4', 'field5', 'field6', 'field7', 'field8']
            for field in required_fields:
                if getattr(self, field) is None:
                    raise ModelValidationError({field: f'{field.capitalize()} is required.'})

    def save(self, *args, **kwargs):
        # Only run validation if the scoresheet is being submitted (not just saved as draft)
        if self.isSubmitted:
            self.clean()
        super().save(*args, **kwargs)


class MapScoresheetToTeamJudge(models.Model):
    teamid = models.IntegerField()
    judgeid = models.IntegerField()
    scoresheetid = models.IntegerField()
    sheetType = models.IntegerField(choices=ScoresheetEnum.choices)


class SpecialAward(models.Model):
    teamid = models.IntegerField()
    award_name = models.CharField(max_length=255)
    isJudge = models.BooleanField(default=False)

class Ballot(models.Model):
    contestid = models.IntegerField()
    isSubmitted = models.BooleanField(default=False)

class Votes(models.Model):
    votedteamid = models.IntegerField()

class MapBallotToVote(models.Model):
    ballotid = models.IntegerField()
    voteid = models.IntegerField()

class MapVoteToAward(models.Model):
    awardid = models.IntegerField()
    voteid = models.IntegerField()

class MapTeamToVote(models.Model):
    teamid = models.IntegerField()
    voteid = models.IntegerField()

class MapAwardToContest(models.Model):
    contestid = models.IntegerField()
    awardid = models.IntegerField()


# === ADDED: Global shared password storage for Organizer & Judge ===
class RoleSharedPassword(models.Model):
    """
    Stores a single, shared hashed password for a role.
    GLOBAL scope (not per contest).
    Applies to roles:
      2 = ORGANIZER
      3 = JUDGE
    """
    ROLE_CHOICES = (
        (2, "ORGANIZER"),
        (3, "JUDGE"),
    )

    role = models.PositiveSmallIntegerField(choices=ROLE_CHOICES, unique=True)
    password_hash = models.CharField(max_length=200)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Shared Password for {self.get_role_display()}"
