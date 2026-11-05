def user_display(user):
    """Name used for the user in allauth pages and emails."""
    profile = getattr(user, 'profile', None)
    return (profile.full_name if profile else '') or user.email
