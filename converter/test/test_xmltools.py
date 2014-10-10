# -*- encoding: utf-8 -*-
from converter.xmltools import * # pylint: disable=W0401,W0614

OPF_STRING = '''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf"
   unique-identifier="epub-id-1">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="epub-id-1">SOME_IDENTIFIER</dc:identifier>
    <dc:creator opf:file-as="CREATOR, SOME"
     id="epub-creator-1">SOME CREATOR</dc:creator>
    <meta refines="#epub-creator-1" property="role"
     scheme="marc:relators">aut</meta>
    ...
  </metadata>
  ...
  <guide>
    <reference type="toc" title="SOME_TITLE" href="nav.xhtml" />
  </guide>
</package>
'''

def test_attributes_in_default_ns():
    """If the default NS is also used for attributes, we currently move
    everything to the attribute NS.

    This is not ideal, but at least not broken.
    """
    assert xml2tup(OPF_STRING) == (
        ('opf:package',
         {'unique-identifier': 'epub-id-1', 'version': '3.0'},
         [('opf:metadata',
           {},
           [('dc:identifier', {'id': 'epub-id-1'}, ['SOME_IDENTIFIER']),
            ('dc:creator',
             {'id': 'epub-creator-1', 'opf:file-as': 'CREATOR, SOME'},
             ['SOME CREATOR']),
            ('opf:meta',
             {'property': 'role',
              'refines': '#epub-creator-1',
              'scheme': 'marc:relators'},
             ['aut', '\n    ...\n  ']),
            '\n  ...\n  ']),
          ('opf:guide',
           {},
           [('opf:reference',
             {'href': 'nav.xhtml', 'title': 'SOME_TITLE', 'type': 'toc'},
             []),
            '\n'])]),
        {None: '',
         'dc': 'http://purl.org/dc/elements/1.1/',
         'opf': 'http://www.idpf.org/2007/opf'})

    assert xml2tup(
        '<package version="3.0" xmlns="http://www.idpf.org/2007/opf">'
        '<metadata/></package>') == (
            ('package', {'version': '3.0'}, [('metadata', {}, [])]),
            {None: 'http://www.idpf.org/2007/opf'})
