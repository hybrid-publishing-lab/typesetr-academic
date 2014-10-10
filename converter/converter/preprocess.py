#-*- file-encoding: utf-8 -*-
"""Utilities shared by *_parser.py files."""
from converter.internal import mkel

def maybe_anchorize_id(tag, attrs, body):
    """DESTRUCTIVELY push the id into an anchor in the body, in most cases.

    Anything w/ an id should be linkable; the id should not be used
    otherwise.
    """
    if 'id' in attrs:
        if tag not in ('dl', 'ol', 'ul', 'aside'):
            body.insert(0, mkel('a', dict(name=attrs['id']), []))
            del attrs['id']
