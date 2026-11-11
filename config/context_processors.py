from django.conf import settings


def static_version(request):
    """«?v=…» for the CSS and JS links: the newest change time of those files.
    A changed stylesheet gets a new address, so the browser never keeps an old one from its cache."""
    newest = 0
    for folder in settings.STATICFILES_DIRS:
        for path in (*folder.glob('css/*.css'), *folder.glob('js/*.js')):
            newest = max(newest, int(path.stat().st_mtime))
    return {'static_version': newest}
