#-*- file-encoding: utf-8 -*-
from collections import OrderedDict
import regex as re

from converter import literal
from converter.sectionize import sectionize
from converter.ezmatch import Var
from converter.epub_writer import * # pylint: disable=W0401,W0614

def test_make_cover():
    dummy_image = literal.Image('', 'image/jpeg', OrderedDict())
    assert make_cover_page(src='SOME_HASH.jpg', title='Dummy Title') == \
'''<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Dummy Title</title>
    <link href="css/stylesheet.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <div class="cover-page">
      <img alt="Dummy Title" src="SOME_HASH.jpg" title="Dummy Title"/>
    </div>
  </body>
</html>
'''
    assert make_cover_opf(dummy_image, src='SOME_HASH.jpg') == [
        ('item',
         {'href': Var('_', re.compile(r'.*\.jpg').match),
          'id': 'cover-image',
          'media-type': 'image/jpeg',
          'properties': 'cover-image'},
         []),
        ('item',
         {'href': 'cover.xhtml',
          'id': 'cover',
          'media-type': 'application/xhtml+xml'},
         [])]

BODY = [('h1', {'id': 'sec1'}, ['section 1']),
        'Some text', ('.footnote', {}, ['First footnote']), '.',
        ('h2', {'id': 'sec1.1'}, ['subsection 1.1']),
        'More text', ('.footnote', {}, ['Second footnote']),
        ('h1', {'id': 'sec2'}, ['section 2']),
        'More text', ('.footnote', {}, ['Third footnote']),
       ]
SECTIONED_BODY = sectionize(BODY[:])[0]

def test_endnotify():
    assert endnotify_epub(SECTIONED_BODY) == [
        ('section', {'id': 'sec1'},
         [('h1', {}, ['section 1']),
          'Some text',
          ('a',
           {'class': ['noteref'], 'epub:type': 'noteref', 'href': '#sec1-fn1'},
           ['1']), '.',
          ('section', {'id': 'sec1.1'},
           [('h2', {}, ['subsection 1.1']),
            'More text',
            ('a',
             {'class': ['noteref'], 'epub:type': 'noteref',
              'href': '#sec1-fn2'},
             ['2'])]),
          ('section',
           {'class': ['endnotes'], 'epub:type': 'footnotes'},
           [('aside',
             {'class': ['endnote'], 'epub:type': 'footnote', 'id': 'sec1-fn1'},
             ['First footnote']),
            ('aside',
             {'class': ['endnote'], 'epub:type': 'footnote', 'id': 'sec1-fn2'},
             ['Second footnote'])])]),
        ('section', {'id': 'sec2'},
         [('h1', {}, ['section 2']),
          'More text',
          ('a',
           {'class': ['noteref'], 'epub:type': 'noteref', 'href': '#sec2-fn1'},
           ['1']),
          ('section',
           {'class': ['endnotes'], 'epub:type': 'footnotes'},
           [('aside',
             {'class': ['endnote'], 'epub:type': 'footnote', 'id': 'sec2-fn1'},
             ['Third footnote'])])])]
