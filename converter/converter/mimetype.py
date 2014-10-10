# -*- encoding: utf-8 -*-
"""Wraps/replaces the builtin mimetypes module.

Reasons:

    1. `mimetypes.guess_type` can return ``(None, None)``,
       for our purposes this should always be a failure

    2. We never need the encoding

    3. `mimetypes.guess_extension` is non-deterministic (!)

"""
import mimetypes

MIME_TYPES = {
    'epub': 'application/epub+zip',
    'woff': 'application/font-woff',
    # IANA mimetype for otf & ttf is application/font-sfnt,
    # <http://www.iana.org/assignments/media-types/application/font-sfnt>
    # but EPUB3 specifies these:
    'otf': 'application/vnd.ms-opentype',
    'ttf': 'application/vnd.ms-opentype',
    'ncx': 'application/x-dtbncx+xml',
}

# we only need this for images, ATM
MIME_TYPE_TO_EXTENSION = {
    'image/jpeg' : '.jpg',
    'image/png' : '.png',
    }

def mimetype_of_url(url):
    mtype, _ = mimetypes.guess_type(url)  # pylint: disable=E1101
    return mtype or MIME_TYPES[url.split('.', 1)[1]]

def extension(mimetype):
    return MIME_TYPE_TO_EXTENSION[mimetype]
