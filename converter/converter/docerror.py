#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
"""Utitlies to produce user-facing error messages."""
from collections import OrderedDict
import logging as log

from converter import exit_code
from converter import orderedyaml as yaml # pylint: disable=E0611

ERROR_COUNT = 0

ON_ERROR = 'log'

def _trunc(s, n=50):
    return (s[:n] + u'…') if len(s) > n else s

_DOCPROBLEM_INDENT = '>'
def _parseable_error(d, level):
    assert level in ('error', 'warning', 'info')
    carp = getattr(log, level)
    carp('DOC%s\n%s%s\n\n',
         level.upper(),
         _DOCPROBLEM_INDENT,
         yaml.dump(d).replace(
             '\n', '\n' + _DOCPROBLEM_INDENT))

def missing_include(kind, link):
    exit_code.final_exit_code |= exit_code.MISSING_INCLUDES_EXIT
    _parseable_error(OrderedDict([('type', 'include'),
                                  ('kind', kind),
                                  ('link', link),
                                  ('body',
                                   'The above %s include is missing' % kind),
                                 ]), level='error')
    exit_code.exit()

def docproblem(fmt_string, *args, **kwargs):
    """Create a document formatting error message for the user.

    Returns an integer indiciating the how manieth encountered problem this
    is.

    (2.7-style) `fmt_string` will have `args` interpolated in, truncated if
    necessary (if you want to construct an untruncated).

    """
    fmt = unicode(fmt_string)
    global ERROR_COUNT # pylint: disable=W0603
    level = kwargs.pop('level', 'error')
    ERROR_COUNT += 1
    # make it so a unescaped string alone is not misinterpreted
    # as a format_string; strictly speaking this is a usage error
    # but this is unambiguous and more convenient
    msg = (fmt if not args
           else fmt.format(*map(_trunc, args)).replace('\n', ' '))
    err = OrderedDict(
        [('type', 'body'),
         ('id', 'docproblem%d' % ERROR_COUNT),
         ('body', msg)])
    if level == 'error':
        exit_code.final_exit_code |= exit_code.BODY_ERROR_EXIT
        if ON_ERROR == 'raise':
            raise RuntimeError('%r' % err)
        elif ON_ERROR == 'debug':
            import ipdb
            ipdb.set_trace()
        else:
            assert ON_ERROR == 'log'
    _parseable_error(err, level=level, **kwargs)
    return ERROR_COUNT

def metaproblem(meta):
    exit_code.final_exit_code |= exit_code.META_ERROR_EXIT
    _parseable_error(OrderedDict([('type', 'meta'),
                                  ('meta', meta)]), level='error')

def metainfoinfo(meta):
    _parseable_error(OrderedDict([('type', 'meta'),
                                  ('meta', meta)]), level='info')
