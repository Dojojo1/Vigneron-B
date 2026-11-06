"""Names shown on the site; Discord identities follow the guild member profile."""


def custom_name_allowed(user):
    user_id=str(user['id'])
    return user_id=='local-preview' or user_id.startswith('guest-')


def display_name(user):
    # username is refreshed from nick > global_name > username by Security.
    # Legacy custom names remain stored, but cannot override a Discord nickname.
    return (user['display_name'] if custom_name_allowed(user) else None) or user['username']
