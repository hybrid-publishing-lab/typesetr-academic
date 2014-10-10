#-*- file-encoding: utf-8 -*-
from converter.internal import mkel
from converter.html_writer import _indent, write_body
from converter.sectionize import sectionize

# don't complain about long names: pylint: disable=C0103
BODY = [
    ('h1', {'id': 'sec1'}, ['1']),
    ('p', {}, ['some paragraph']),
    ('h1', {'id': 'sec2'}, ['2']),
    'a plain string',
    ('h2', {'id': 'sec2.1'}, ['2.1']),
    ('p', {}, ['a para with some', ('i', {}, 'italic'), 'text']),
    ('p', {}, ['One more para']),
    ('h2', {'id': 'sec2.1'}, ['2.2']),
    ('h3', {'id': 'sec2.1.1'}, ['2.2.1']),
    'There was no text before this heading',
    ('h1', {'id': 'sec3'}, ['3']),
    'Stuff at doc end',
    ]

def test_sectionize_on_well_structured_data():
    assert sectionize(['blah'], h_less_section=None) == (['blah'], [])
    assert sectionize(['blah']) == (
        [('section', {'id': 'pre-section'}, ['blah'])], [])
    assert sectionize([('h1', {'id': 'someid1'}, ['1'])]) == (
        [('section', {'id': 'someid1'}, [('h1', {}, ['1'])])],
        [('h1', {'id': 'someid1'}, ['1'])])
    assert sectionize(BODY[:]) == (
        [('section', {'id': 'sec1'},
          [('h1', {}, ['1']), ('p', {}, ['some paragraph'])]),
         ('section', {'id': 'sec2'},
          [('h1', {}, ['2']),
           'a plain string',
           ('section', {'id': 'sec2.1'},
            [('h2', {}, ['2.1']),
             ('p', {}, ['a para with some', ('i', {}, 'italic'), 'text']),
             ('p', {}, ['One more para'])]),
           ('section', {'id': 'sec2.1'},
            [('h2', {}, ['2.2']),
             ('section', {'id': 'sec2.1.1'},
              [('h3', {}, ['2.2.1']),
               'There was no text before this heading'])])]),
         ('section', {'id': 'sec3'}, [('h1', {}, ['3']), 'Stuff at doc end'])],
        [('h1', {'id': 'sec1'}, ['1']),
         ('h1', {'id': 'sec2'}, ['2']),
         [('h2', {'id': 'sec2.1'}, ['2.1']),
          ('h2', {'id': 'sec2.1'}, ['2.2']),
          [('h3', {'id': 'sec2.1.1'}, ['2.2.1'])]],
         ('h1', {'id': 'sec3'}, ['3'])])

WEIRD_BODY = [
    'Stuff at doc beginning',
    ('h4', {'id': 'sec0.0.0.1'}, ['1']),
    ('p', {}, ['some paragraph']),
    ('h1', {'id': 'sec1'}, ['2']),
    'a plain string',
    ('h2', {}, [('a', {'name': 'sec1.1'}, []),
                ('a', {'name': 'sec1.1-alias'}, []),
                '1.1']),
    ('p', {}, ['a para with some', ('i', {}, 'italic'), 'text']),
    ('p', {}, ['One more para']),
    ('h2', {'id': 'sec1.2'}, [('a', {'name': 'sec1.2-alias'}, []), '1.2']),
    ('h4', {'id': 'sec1.2.0.1'}, ['1.2.0.1']),
    ('h3', {'id': 'sec1.2.1'}, ['1.2.1']),
    ('h2', {'id': 'sec1.3'}, ['1.3']),
    'There was no text before this heading',
    ('h1', {'id': 'sec2'}, ['2']),
    'Stuff at doc end',
    ]

def test_sectionize_on_badly_structured_data():
    """This is more about documenting existing behavior...

    .. than expressing desirability."""
    assert sectionize(WEIRD_BODY[:]) == (
        ([('section', {'id': 'pre-section'}, ['Stuff at doc beginning']),
          ('section', {'id': 'sec0.0.0.1'},
           [('h4', {}, ['1']), ('p', {}, ['some paragraph'])]),
          ('section', {'id': 'sec1'},
           [('h1', {}, ['2']),
            'a plain string',
            ('section', {'id': 'sec1.1'},
             [('h2', {}, [('a', {'name': 'sec1.1-alias'}, []), '1.1']),
              ('p', {}, ['a para with some', ('i', {}, 'italic'), 'text']),
              ('p', {}, ['One more para'])]),
            ('section', {'id': 'sec1.2'},
             [('h2', {}, [('a', {'name': 'sec1.2-alias'}, []), '1.2']),
              ('section', {'id': 'sec1.2.0.1'}, [('h4', {}, ['1.2.0.1'])]),
              ('section', {'id': 'sec1.2.1'}, [('h3', {}, ['1.2.1'])])]),
            ('section', {'id': 'sec1.3'},
             [('h2', {}, ['1.3']), 'There was no text before this heading'])]),
          ('section', {'id': 'sec2'}, [('h1', {}, ['2']), 'Stuff at doc end'])],
         [('h4', {'id': 'sec0.0.0.1'}, ['1']),
          ('h1', {'id': 'sec1'}, ['2']),
          [('h2', {'id': 'sec1.1'}, ['1.1']),
           ('h2', {'id': 'sec1.2'}, ['1.2']),
           [('h4', {'id': 'sec1.2.0.1'}, ['1.2.0.1']),
            ('h3', {'id': 'sec1.2.1'}, ['1.2.1'])],
           ('h2', {'id': 'sec1.3'}, ['1.3'])],
          ('h1', {'id': 'sec2'}, ['2'])]))

def test_indent():
    "Empty lines are not indented, everything else including WS only lines are."
    assert _indent('a\n\nb\n  \n  c', '  ') == '  a\n\n  b\n    \n    c'

def test_write_body():
    assert write_body([mkel('script', {}, [])])
