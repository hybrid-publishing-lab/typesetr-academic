# -*- encoding: utf-8 -*-
from collections import OrderedDict, Counter
import datetime
import logging as log

import pybtex
from pybtex.exceptions import PybtexError
import pybtex.database
import regex as re

from converter.internal import mkel
from converter.unparse import unparse_literal

NON_BREAKING_SPACE = u'\u00A0'

DUBLIN_META_NS = {'dc': "http://purl.org/dc/elements/1.1/",
                  'opf': "http://www.idpf.org/2007/opf"}



# FIXME(alexander): deal with company names, too.
# FIXME(alexander): this really needs integration into the MetaSchema
# otherwise, either the dublin core or the actual displayed name will be wrong
# in some cases (e.g. names with suffixes; Chinese names)
class Person(object):
    """Represents a person name.

    Allows entering most Western names either in natural order or in
    sort-order:

    >>> Person("Ludwig van Beethoven") == Person('van Beethoven, Ludwig')
    True
    >>> Person("Ludwig van Beethoven") == Person('Beethoven, van, Ludwig')
    False

    Both the display and sort-name can be accessed:

    >>> Person("Ludwig van Beethoven").display_name
    u'Ludwig van Beethoven'
    >>> Person("Ludwig van Beethoven").sort_name
    u'van Beethoven, Ludwig'

    Names with suffixes require the comma-separated form:

    >>> Person("von Hicks, III, Michael").display_name
    u'Michael von Hicks, III'
    >>> Person("von Hicks, III, Michael").sort_name
    u'von Hicks, III, Michael'
    >>> Person('Steele, Jr, Guy').display_name
    u'Guy Steele, Jr'

    If the name is Chinese the default parsing will be wrong, resulting in an
    incorrect sort_name:

    >>> Person('Mao Tsedong').sort_name
    u'Tsedong, Mao'

    To correct that, use the little endian flag:

    >>> Person('Mao Tsedong', little_endian=False).display_name
    u'Mao Tsedong'
    >>> Person('Mao Tsedong', little_endian=False).sort_name
    u'Mao, Tsedong'
    """
    _initialized = False
    def __init__(self, string, little_endian=True):
        """`little_endian` = Western name order, i.e. key part last."""
        # FIXME(alexander): remove tex parsing
        string = unicode(string)
        self._sanitized = re.sub(r'["^{}[\]]', '', string).replace(
            '~', NON_BREAKING_SPACE)
        self.little_endian = little_endian
        if self._sanitized != string:
            log.warn('Funny characters in name %r', string)
        if not self.little_endian:
            # FIXME(alexander): horrible hack to westernize names
            self._sanitized = " ".join(self._sanitized.split(' ', 1)[::-1])
        try:
            # pylint: disable=C0103
            self._p = pybtex.database.Person(self._sanitized)
            first, particle, last, suffix = (
                self._p.bibtex_first(), self._p.prelast(),
                self._p.last(), self._p.lineage())
            suffixed_last = (last if not suffix
                             else last + [", " + " ".join(suffix)])
            self.sort_name = unicode(self._p)
            parts = [first, particle, suffixed_last]
            self.display_name = " ".join(
                subpart
                for part in (parts if self.little_endian else reversed(parts))
                for subpart in part).replace(' , ', ', ')

            self.parts = OrderedDict([(name, ' '.join(parts[index]))
                                      for index, name in enumerate(['first',
                                                                    'particle',
                                                                    'last'])])
        # degrade, not necessarily gracefully if we can't parse the name
        except PybtexError:
            # FIXME(alexander): make this user-visible
            log.warn("Can't parse name; "
                     "did you mean to use ';' instead of ',' in %r?",
                     self._sanitized.encode('utf-8'))
            self._p = None
            self.display_name = self.sort_name = self._sanitized
        ## those are the two important bits
        self._initialized = True

    def __setattr__(self, n, v):
        if self._initialized:
            return NotImplemented
        self.__dict__[n] = v

    def __unicode__(self):
        return self.display_name

    def __eq__(self, other):
        return type(other) is type(self) and (
            self.sort_name == other.sort_name and
            self.display_name == other.display_name)

    def __ne__(self, other):
        return not self == other

HEAD_TO_CORE = OrderedDict(l.split() for l in '''\
title title
subtitle title
author creator
editor creator
translator contributor
compilation-editor creator
abstract description
date date
keywords subject
publisher publisher
isbn identifier
uuid identifier
copyright rights
license rights
lang language'''.split('\n'))

# http://www.loc.gov/marc/relators/relaterm.html
MARC_RELATOR = {'author': 'aut',
                'editor': 'edt',
                'compilation-editor': 'edc',
                'translator': 'trl',
               }
TITLE_ELEMENTS = ('title', 'subtitle')
UUID_ELEMENTS = ('isbn', 'uuid')
IDED_ELEMENTS = TITLE_ELEMENTS + UUID_ELEMENTS


def meta_to_dublin_core(head, modified=None):
    modified = datetime.datetime.utcnow() if modified is None else modified
    ts = modified.isoformat().split('.')[0] + 'Z'
    assert 'uuid' in head
    dublin = []
    head = head.copy()
    dc = 'dc:'.__add__
    ids = Counter()
    for h, d, v in ((k, d, head[k])
                    for (k, d) in HEAD_TO_CORE.iteritems() if k in head):
        if h in MARC_RELATOR:
            # FIXME(alexander): make authors etc. first class type
            people = (re.split(r'\s*;\s*', v)
                      if isinstance(v, basestring) else v)
            for a in people:
                ids[d] += 1
                person = Person(a)
                pid = "pub-%s-%d" % (d, ids[d])
                dublin.append(mkel(dc(d), {'id': pid}, [person.display_name]))
                dublin.append(mkel('meta', {'refines': pid,
                                            'property': 'role',
                                            'scheme':'marc:relators'},
                                   [MARC_RELATOR[h]]))
                dublin.append(mkel('meta', {'refines': pid,
                                            'property': 'file-as'},
                                   [person.sort_name]))
        else:
            unparsed = unparse_literal(v, roundtrip=False, plain=True)
            if not unparsed:
                continue
            attrs = dict(id=h) if h in IDED_ELEMENTS else {}
            dublin.append(mkel(dc(d), attrs, [unparsed]))
            if h in TITLE_ELEMENTS:
                dublin.append(mkel('meta', {'refines': '#%s' % attrs['id'],
                                            'property': 'title-type'},
                                   [{'title': 'main'}.get(h, h)]))
                dublin.append(mkel('meta', {'refines': '#%s' % attrs['id'],
                                            'property': 'display-seq'},
                                   [str(TITLE_ELEMENTS.index(h) + 1)]))
    dublin.append(mkel('meta', {'property': 'dcterms:modified'}, [ts]))
    return ('metadata', {}, dublin), DUBLIN_META_NS
