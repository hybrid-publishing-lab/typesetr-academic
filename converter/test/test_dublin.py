# -*- encoding: utf-8 -*-
# don't complain about long names pylint: disable=C0103
import datetime

from converter.dublin import * # pylint: disable=W0614,W0401
from converter.xmltools import * # pylint: disable=W0614,W0401
from converter.literal import Multiline, Date, Lang, Uuid

# disable line-length and continuation checks, since we want to look at XML
# pylint: disable=C0301,C0330

def test_standard_metadata_to_dublin():
    head = [('title', 'The document title'),
            ('subtitle', 'the subtitle'),
            ('author', Multiline([
                'Alexander Schmolck',
                u'Hieronymus Carl Friedrich von Münchhausen'])),
            ('project', 'Typesetr'),
            ('client', 'The Client'),
            ('version', '1.3.0'),
            ('date', Date('2013-01-01')),
            ('lang', Lang('en')),
            ('section-numbering-depth', '0'),
            ('recipients', ''),
            ('abstract', []),
            ('bibliography', None),
            ('draft', False),
            ('toc', True),
            ('keywords', ''),
            ('logo', None),
            ('confidential', False),
            ('bibliography-preamble', [])]
    to_dublin = dict(head, uuid=Uuid(bytes='\1'*16, version=5))
    date = datetime.datetime(2001, 2, 3, 4, 5, 6)
    assert (tup2xml(*meta_to_dublin_core(to_dublin, date)) ==
'''\
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title id="title">The document title</dc:title>
  <meta property="title-type" refines="#title">main</meta>
  <meta property="display-seq" refines="#title">1</meta>
  <dc:title id="subtitle">the subtitle</dc:title>
  <meta property="title-type" refines="#subtitle">subtitle</meta>
  <meta property="display-seq" refines="#subtitle">2</meta>
  <dc:creator id="pub-creator-1">Alexander Schmolck</dc:creator>
  <meta property="role" refines="pub-creator-1" scheme="marc:relators">aut</meta>
  <meta property="file-as" refines="pub-creator-1">Schmolck, Alexander</meta>
  <dc:creator id="pub-creator-2">Hieronymus Carl Friedrich von Münchhausen</dc:creator>
  <meta property="role" refines="pub-creator-2" scheme="marc:relators">aut</meta>
  <meta property="file-as" refines="pub-creator-2">von Münchhausen, Hieronymus Carl Friedrich</meta>
  <dc:date>2013-01-01</dc:date>
  <dc:identifier id="uuid">urn:uuid:01010101-0101-5101-8101-010101010101</dc:identifier>
  <dc:language>en</dc:language>
  <meta property="dcterms:modified">2001-02-03T04:05:06Z</meta>
</metadata>
''')


def test_that_bad_things_will_happen_if_you_separate_authors_by_commas():
    date = datetime.datetime(2001, 2, 3, 4, 5, 6)
    authors = u'Alfréd Rényi, Paul Erdős, Endre Szemerédi, Cecil C. Rousseau'
    to_dublin = dict({'author': authors}, uuid=Uuid(bytes='\1'*16, version=5))
    # oops, just saved as a singel author:
    assert (tup2xml(*meta_to_dublin_core(to_dublin, date)) ==
'''\
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator id="pub-creator-1">Alfréd Rényi, Paul Erdős, Endre Szemerédi, Cecil C. Rousseau</dc:creator>
  <meta property="role" refines="pub-creator-1" scheme="marc:relators">aut</meta>
  <meta property="file-as" refines="pub-creator-1">Alfréd Rényi, Paul Erdős, Endre Szemerédi, Cecil C. Rousseau</meta>
  <dc:identifier id="uuid">urn:uuid:01010101-0101-5101-8101-010101010101</dc:identifier>
  <meta property="dcterms:modified">2001-02-03T04:05:06Z</meta>
</metadata>
''')
    # Fix the author list:
    to_dublin['author'] = to_dublin['author'].replace(',', ';')
    assert (tup2xml(*meta_to_dublin_core(to_dublin, date)) ==
'''\
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator id="pub-creator-1">Alfréd Rényi</dc:creator>
  <meta property="role" refines="pub-creator-1" scheme="marc:relators">aut</meta>
  <meta property="file-as" refines="pub-creator-1">Rényi, Alfréd</meta>
  <dc:creator id="pub-creator-2">Paul Erdős</dc:creator>
  <meta property="role" refines="pub-creator-2" scheme="marc:relators">aut</meta>
  <meta property="file-as" refines="pub-creator-2">Erdős, Paul</meta>
  <dc:creator id="pub-creator-3">Endre Szemerédi</dc:creator>
  <meta property="role" refines="pub-creator-3" scheme="marc:relators">aut</meta>
  <meta property="file-as" refines="pub-creator-3">Szemerédi, Endre</meta>
  <dc:creator id="pub-creator-4">Cecil C. Rousseau</dc:creator>
  <meta property="role" refines="pub-creator-4" scheme="marc:relators">aut</meta>
  <meta property="file-as" refines="pub-creator-4">Rousseau, Cecil C.</meta>
  <dc:identifier id="uuid">urn:uuid:01010101-0101-5101-8101-010101010101</dc:identifier>
  <meta property="dcterms:modified">2001-02-03T04:05:06Z</meta>
</metadata>
''')
