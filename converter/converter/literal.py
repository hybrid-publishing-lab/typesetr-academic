#-*- file-encoding: utf-8 -*-
from collections import OrderedDict
import logging as log
import json
import regex as re
import datetime
import uuid
import dateutil.parser

from ._literal import Literal
from . import digest
from .ezmatch import Var
from . import html_parser
# we re-export this; the reason we import at all is cyclic deps
from .lang import Lang
from . import transclusions
import converter
# We only accepts W3C times/dates (see below) with two mods:
#
#  1. we allow substituting ' ' for 'T'
#  2. we allow omitting the mostly useless :mm part of the TZD
#
# The spec is this <http://www.w3.org/TR/NOTE-datetime>:
#    Year:
#       YYYY (eg 1997)
#    Year and month:
#       YYYY-MM (eg 1997-07)
#    Complete date:
#       YYYY-MM-DD (eg 1997-07-16)
#    Complete date plus hours and minutes:
#       YYYY-MM-DDThh:mmTZD (eg 1997-07-16T19:20+01:00)
#    Complete date plus hours, minutes and seconds:
#       YYYY-MM-DDThh:mm:ssTZD (eg 1997-07-16T19:20:30+01:00)
#    Complete date plus hours, minutes, seconds and a decimal fraction of a sec
#       YYYY-MM-DDThh:mm:ss.sTZD (eg 1997-07-16T19:20:30.45+01:00)
# TZD  = time zone designator (Z or +hh:mm or -hh:mm)
TIME_REX = re.compile(r'''(?x)
(?P<hours>\d{2}):(?P<mins>\d{2})(?::(?P<sec>\d{2}(?:[.]\d+)?))?
(?P<tz>Z|[+-]\d{2}(:\d{2})?)?''')

DATE_REX = re.compile(r'''(?x)
(?P<year>-?\d{4})(?:-
                  (?P<month>\d{2})
                   (?:-(?P<day>\d{2}))?)?
''')

DATE_TIME_REX = re.compile(r'''(?x)
%s[T ]%s''' % (DATE_REX, TIME_REX.pattern))

class Image(Literal):
    def __init__(self, data, mimetype, style):
        assert isinstance(style, OrderedDict)
        self.data, self.mimetype, self.style = data, mimetype, style
        assert type(self.data) is str

    def __repr__(self):
        return '%s%r' % (type(self).__name__,
                         (self.data, self.mimetype, self.style))

    @classmethod
    def from_string(cls, s):
        # FIXME(alexander): think about how to represent empty images
        if not s:
            return None
        # FIXME(alexander): why for the love of God am I reading a json string
        # here?
        d = json.JSONDecoder(object_pairs_hook=OrderedDict).decode(s)
        data, mime = transclusions.from_data_url(d['dataurl'])
        style = d['style']
        return cls(data, mime, style)

    def to_string(self):
        return json.dumps(OrderedDict([
            ('style', self.style),
            ('dataurl', transclusions.to_data_url(self.data, self.mimetype)),
            ]), sort_keys=False)

    def get_size(self):
        from cStringIO import StringIO
        import PIL
        return PIL.Image.open(StringIO(self.data)).size


class Multiline(Literal):
    def __init__(self, lines):
        assert isinstance(lines, list)
        self.data = lines
    def __repr__(self):
        return 'Multiline(%r)' % self.data
    def __iter__(self):
        return iter(self.data)
    @classmethod
    def from_string(cls, s):
        return cls([x.strip().replace('\\\\', '\\')
                    for x in re.split(r'(?<!\\)(?:\\\\)*;', s)])
    def to_string(self):
        return "; ".join(x.replace('\\', '\\\\').replace(';', '\\;')
                         for x in self.data)

class Bibliography(Literal):
    def __init__(self, bib):
        # pylint: disable=C0103
        URL = Var('URL')
        NAME = Var('NAME')
        assert bib == [('a', {'href': URL}, [NAME])]
        self.data = bib
    def __repr__(self):
        return 'Bibliography(%r)' % self.data

    @classmethod
    def from_string(cls, s):
        # FIXME(alexander): think about how to represent empty bibliographies
        if not s:
            return None
        return cls(html_parser.parse_chunk(s.strip()))
    def to_string(self):
        # FIXME(alexander): try to break cyclic import
        import converter.html_writer
        return converter.html_writer.write_body(self.data)

class Date(Literal):
    def __init__(self, supplied):
        self.supplied = supplied
        if supplied.lower() == 'today':
            self.parsed = datetime.date.today().isoformat()
        elif re.match(r'^-?[1-9]\d+$', supplied):
            self.parsed = repr(int(supplied))
        else:
            self.parsed = dateutil.parser.parse(supplied).date().isoformat()

    def __repr__(self):
        return 'Date(%r)' % self.supplied

    @classmethod
    def from_string(cls, s):
        return cls(s)
    def to_string(self):
        return 'today' if self.supplied == 'today' else self.parsed
    def to_value(self):
        return self.parsed

class Uuid(Literal, uuid.UUID):
    def to_string(self):
        return self.urn

    def from_string(self, s):
        assert s.startswith('urn:uuid:')
        return type(self)(s)

    def __repr__(self):
        return "Uuid(%r)" % self.to_string()


def doc_uuid(meta, parsed_body, transclusions):
    # pylint: disable=W0622
    bytes = digest.doc_digest(meta, parsed_body, transclusions).decode('hex')
    return converter.literal.Uuid(bytes=bytes, version=5)

PY_TYPE_TO_TYPESETR_TYPES = {
    bool: ('boolean',),

    str: ('text', 'rich-text'),
    unicode: ('text', 'rich-text'),
    list: ('rich-text', 'bibliography'),

    Multiline: ('multiline',),
    Lang: ('lang',),
    Image: ('image',),
    Date: ('date',),
    Bibliography: ('bibliography',)
    }

TYPESETR_TYPE_TO_PY_TYPE = dict((v[0], k)
                                for (k, v) in PY_TYPE_TO_TYPESETR_TYPES.items())
TYPESETR_TYPE_TO_PY_TYPE['text'] = unicode


_LIT_PARSERS = OrderedDict([
    ('boolean',
     (lambda lit: lit.lower() in ('no', 'yes'),
      lambda lit: lit.lower() == 'yes')),
    ('lang',
     (Lang.is_valid_lang,
      Lang))
    ])

class BadLiteral(Exception):
    def __init__(self, lit, expected_type=None):
        self.lit = lit
        self.expected_type = expected_type
        Exception.__init__(self, "Bad literal%s'%r'" % (
            "for type %s" % expected_type if expected_type else "", lit))

def parse_literal(lit, expected_type=None):
    assert isinstance(lit, basestring)
    try:
        if expected_type:
            if expected_type in ('multiline', 'image', 'date', 'bibliography'):
                return TYPESETR_TYPE_TO_PY_TYPE[expected_type].from_string(lit)
            if expected_type == 'text':
                return lit
            if expected_type == 'rich-text':
                return html_parser.parse_chunk(lit)
            valid, parse = _LIT_PARSERS[expected_type]
            if valid(lit):
                return parse(lit)
        else:
            for valid, parse in _LIT_PARSERS.values():
                if valid(lit):
                    return parse(lit)
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        log.debug('Failed to parse literal', exc_info=True)
    raise BadLiteral(lit, expected_type)
