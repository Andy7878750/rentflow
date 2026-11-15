import hashlib

from django.conf import settings


def static_version(request):
    """«?v=…» for the CSS and JS links: a short fingerprint of those files' change times and sizes.
    A changed stylesheet gets a new address, so the browser never keeps an old one from its cache.
    (2026-11-16: not «the newest time» — a file dated in the future after a clock change froze it.)"""
    stamp = hashlib.md5(usedforsecurity=False)
    for folder in settings.STATICFILES_DIRS:
        for path in sorted((*folder.glob('css/*.css'), *folder.glob('js/*.js'))):
            info = path.stat()
            stamp.update(f'{path.name}:{info.st_mtime_ns}:{info.st_size};'.encode())
    return {'static_version': stamp.hexdigest()[:10]}
