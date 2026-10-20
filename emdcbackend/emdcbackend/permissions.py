from .models import MapUserToRole


def is_admin_user(user):
    """Return whether the authenticated account has an EMDC admin role."""
    return user.is_superuser or MapUserToRole.objects.filter(
        uuid=user.id, role=MapUserToRole.RoleEnum.ADMIN
    ).exists()
