# -*- encoding: utf-8 -*-
ur"""Creates an epub3 file.

The generated epub should look something like this:
(FIXME(alexander): images are currently in the toplevel)

   mimetype
   META-INF/
     container.xml
     com.apple.ibooks.display-options.xml
   css/
     stylesheet.css                        # mandatory!
   images/
     someimage.png
   fonts/
   package.opf
   toc.xhtml
#  toc.ncx
#  titlepage.xhtml
   main.xhtml
   [cover.xtml]
"""
from collections import OrderedDict
from functools import partial
from itertools import count
import zipfile

import regex as re

from converter import html_writer
from converter.xmltools import tup2xml
from converter.internal import mkel
from converter.dublin import meta_to_dublin_core
from converter.literal import doc_uuid
from converter.mimetype import mimetype_of_url
from converter.sectionize import sectionize, make_stable_gensym
from converter.endnotify import endnotify


EPUB_CONTAINER = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="package.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
'''

# pylint: disable=C0301
# http://www.pigsgourdsandwikis.com/2011/04/embedding-fonts-in-epub-ipad-iphone-and.html
# pylint: enable=C0301
IBOOKS_DISPLAY_OPTIONS = '''<?xml version="1.0" encoding="UTF-8"?>
<display_options>
  <platform name="*">
    <option name="specified-fonts">true</option>
  </platform>
</display_options>
'''

FONT_REX = re.compile(r'^\.\./fonts/(.*)(?i:\.(otf|ttf))$')
font_path_to_id = partial(FONT_REX.sub, r'font.\1')  # pylint: disable=C0103

def html_string_from_body(body, title, nsmap={}): # pylint: disable=W0102
    html = ('html', {},
            [('head', {},
              [('title', {}, [title]),
               ('link', {'href': 'css/stylesheet.css',
                         'rel': 'stylesheet', 'type': 'text/css'}, [])]),
             body])
    ns = {None: 'http://www.w3.org/1999/xhtml'}
    ns.update(nsmap)
    return tup2xml(html, nsmap=ns, decl=True, html=True, cleanup=False)

def _opf_item(href, id=None, mime=None, properties=None): #pylint: disable=W0622
    id = id or href.split('.')[0].replace('/', '-')
    attrs = {'id': id, 'href': href,
             'media-type': mime or mimetype_of_url(href)}
    if properties is not None:
        attrs['properties'] = properties
    return mkel('item', attrs, [])


def make_cover_page(src, title):
    return html_string_from_body(
        ('body', {}, [('div', {'class': 'cover-page'},
                       [('img',
                         {'alt': title, # XXX: lang.localize('Cover')?
                          'src': src,
                          'title': title}, [])])]),
        title=title)

def make_cover_opf(image, src):
    return [_opf_item(src, 'cover-image', mime=image.mimetype,
                      properties='cover-image'),
            _opf_item('cover.xhtml')]

def make_opf(head, parts, transclusions, includes, # pylint: disable=R0913,R0914
             cover_image=None, compat=False):
    """Create package.opf contents.

    `compat`: whether to create an epub2 compatible package
              FIXME(alexander): not fully implemented
    """
    title = head['title']
    dublin, dublin_ns = meta_to_dublin_core(head)
    manifest_body = []
    spine_body = []

    manifest_body.extend(_opf_item(inc) for inc in includes)

    if compat:
        manifest_body.append(_opf_item('toc.ncx', 'ncx'))
    manifest_body.append(_opf_item('toc.xhtml', properties='nav'))
    spine_body.append(mkel('itemref', {'idref': 'toc', 'linear': 'no'}, []))
    if cover_image:
        cover_src = transclusions.add_literal_image(cover_image)
        manifest_body.extend(make_cover_opf(cover_image, cover_src))
        spine_body.append(mkel('itemref', {'idref': 'cover', 'linear': 'no'},
                               []))
    else:
        cover_src = None
    for part in parts:
        manifest_body.append(_opf_item(part + '.xhtml'))
        spine_body.append(mkel('itemref', {'idref': part, 'linear': 'yes'}, []))
    # images
    manifest_body.extend(_opf_item(k, id='img-' + k.split('.')[0],
                                   mime=transclusions.get_mimetype(k))
                         for (k, _) in transclusions.iteritems()
                         if k != cover_src)
    package_body = [dublin,
                    mkel('manifest', {}, manifest_body),
                    mkel('spine', {'toc': 'ncx'} if compat else {}, spine_body)]
    if compat:
        package_body.append(('guide', {},
                             [('reference', dict(type='toc',
                                                 title=title,
                                                 href='toc.xhtml'), [])]))
    package = mkel('package', {'version': '3.0', 'unique-identifier': 'uuid'},
                   package_body)
    ns = {(k if k != 'opf' else None): v for (k, v) in dublin_ns.iteritems()}
    return package, ns

# FIXME(alexander): reduce number of args, get rid of pylint disable
def make_epub(out_file, parts, includes, transclusions, # pylint: disable=R0913
              toc, opf):
    transclusions.provide()
    # FIXME(alexander): use ZIP_DEFLATED for non-image content
    with zipfile.ZipFile(out_file, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', EPUB_CONTAINER)
        archive.writestr('META-INF/com.apple.ibooks.display-options.xml',
                         IBOOKS_DISPLAY_OPTIONS)
        # FIXME(alexander): should toc and package just be parts?
        archive.writestr('toc.xhtml', toc)
        archive.writestr('package.opf', opf)
        for n, part_s in parts.iteritems():
            archive.writestr(n + '.xhtml', part_s)
        for n, path in includes.iteritems():
            archive.write(arcname=n, filename=path)
        for n, data in transclusions.iteritems():
            archive.writestr(n, data)


def endnotify_epub(body):
    # add the noteref class to the link, so that we can use same
    # CSS for epub and html; also had no luck w/ epub:type css selector
    # with ibooks at least
    section_attrs = {
        'epub:type': 'footnotes',
        'class': ['endnotes'],
    }
    aside_attrs = {
        'epub:type': 'footnote',
        'class': ['endnote'],
    }
    a_attrs = {
        'epub:type': 'noteref',
        'class': ['noteref'],
    }
    return endnotify(body, aside_attrs, a_attrs, section_attrs)


def write(out_file, style_template, bib, # pylint: disable=R0913,R0914,W0613
          meta, parsed_body, transclusions):
    uuid = doc_uuid(meta, parsed_body, transclusions)
    sectioned, toc = sectionize(parsed_body, gensym=make_stable_gensym(uuid))
    head = meta.items()
    head['uuid'] = uuid
    endnoted = endnotify_epub(sectioned)
    body_s = html_writer.write_body(endnoted, indent='',
                                    transclusions=transclusions,
                                    h_shift=style_template.h_shift,
                                    epub_clean=True)
    main = html_string_from_body(
        ('body', {}, ['REPLACEME']),
        title=head['title'],
        nsmap={'epub': 'http://www.idpf.org/2007/ops'}).replace(
            'REPLACEME', body_s).encode('utf-8')
    assert isinstance(main, str)
    parts = OrderedDict([('main', main)])
    cover_image = head.get('cover-image')
    if cover_image:
        src = transclusions.add_literal_image(cover_image)
        parts['cover'] = make_cover_page(src, head['title'])
    include_dict = dict(style_template.includes_for('epub'))
    opf = tup2xml(*make_opf(head, includes=include_dict.keys(),
                            parts=['main'], transclusions=transclusions,
                            cover_image=cover_image),
                  decl=True)
    make_epub(out_file, parts,
              includes=include_dict,
              # FIXME(alexander): hardcoded toc-depth
              toc=make_toc(head['title'], head['lang'], toc, toc_depth=1),
              opf=opf,
              transclusions=transclusions)

# run gdoc-to --lofi ./test/data/comprehensive-test.odt foo.epub
#html.xpath('.//*[self::h1 or self::h2 or self::h3]')
##

def make_landmarks(title, lang):
    # FIXME(alexander): de-hardcode
    return ('nav', {'epub:type': 'landmarks', 'id': 'landmarks'},
            [('h2', {}, [title]), # XXX 'Guide'
             ('ol', {},
              [('li', {}, [('a', {'epub:type': 'toc', 'href': '#toc'},
                            [lang.localize('Table of Contents')])]),
               ('li', {},
                [('a', {'epub:type': 'bodymatter', 'href': 'main.xhtml'},
                  [lang.localize('Start of Contents')])]),
              ])])

def make_toc(title, lang, toc, toc_depth, titlepage=False):
    ns = {None: 'http://www.w3.org/1999/xhtml',
          'epub': 'http://www.idpf.org/2007/ops'}
    toc_ol_body = []

    if titlepage:
        toc_ol_body.append(mkel('li', {'id': 'toc-titlepage'},
                                [('a', {'href': 'titlepage.xhtml'}, [title])]))
    # FIXME(alexander): make this work for arbitrary toc-depth;
    # also don't tie to single-html file layout/name.
    assert toc_depth == 1
    chapter_toc = [h for h in toc if isinstance(h, tuple)]
    toc_ol_body.extend(
        ('li', {'class': 'toc-chapter', 'id': 'toc-chapter-%d' % i},
         [('a', {'href': 'main.xhtml#%s' % a['id']}, [h])])
        for (i, (tag, a, (h,))) in zip(count(1), chapter_toc))
    landmarks = make_landmarks(title, lang)
    return html_string_from_body(
        ('body', {},
         [('section',
           {'class': 'frontmatter toc', 'epub:type': 'frontmatter toc'},
           [('header', {}, [('h1', {}, [lang.localize('Contents')])]),
            ('nav', {'epub:type': 'toc', 'id': 'toc'},
             [('ol', {}, toc_ol_body)]),
            landmarks
           ])]), title=title, nsmap=ns)

# import pickle, tempfile
# p = pickle.load(open('foo.pickle'))
# p.transclusions.out_dir = tempfile.mkdtemp()
# write(open('/tmp/test.epub', 'wb'), p.style_template,
#       p.meta, p.parsed_body, p.transclusions)
