#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
r"""Code for writing (currently only updating existing) odt files."""
from __future__ import division

import cgi
import logging as log
import regex as re

from converter.internal import COLOR_TYPES

from converter import literal
from converter.unparse import unparse_literal
from converter import lxmlutil
from converter.xml_namespaces import odt_ns as ns
from converter.postprocess import whack

def t(s): # pylint: disable=C0103
    def interpolate(*a, **kwargs):
        a = a or kwargs
        return s % a
    return interpolate

ODT_TEXT_STYLE_TEMPLATE = t('''\
<style:style style:name="%s" style:family="text" style:parent-style-name="Standard">\
%s
</style:style>\
''')
ODT_IMAGE_STYLE_TEMPLATE = ('''\
<style:style style:name="%s" style:family="graphic"\
 style:parent-style-name="Standard">\
<style:graphic-properties draw:stroke="none" draw:fill-color="#ffffff"\
 fo:background-color="#ffffff" fo:border-top="none" fo:margin-top="0.053cm"\
 fo:border-bottom="none" fo:margin-bottom="0.053cm" fo:border-left="none"\
 fo:margin-left="0.053cm" fo:border-right="none" fo:margin-right="0.053cm"\
 style:flow-with-text="false" style:run-through="foreground"\
 draw:auto-grow-height="false" draw:auto-grow-width="false"/></style:style>''')
# pylint: disable=C0301
ODT_MINIMAL_STYLES = dict(
    Underlined='<style:text-properties style:text-underline-style="solid" style:text-underline-color="font-color"/>',
    Bold='<style:text-properties  fo:font-weight="bold" style:font-weight-asian="bold" style:font-weight-complex="bold"/>',
    Italic='<style:text-properties fo:font-style="italic" style:font-style-asian="italic" style:font-style-complex="italic"/>',
    Strikethrough='<style:text-properties style:text-line-through-style="solid"/>',
    Fixed='<style:text-properties style:font-name="Courier New" style:font-name-asian="Courier New" style:font-name-complex="Courier New" />',
    Superscript='<style:text-properties style:text-position="super 58%"/>',
    Subscript='<style:text-properties style:text-position="sub 58%"/>',
    Image=ODT_IMAGE_STYLE_TEMPLATE,
)
def create_color_style(fg, bg):
    return '<style:text-properties%s%s/>' % tuple(
        (t % s) if s else '' for (t, s) in [(' fo:color="#%s"', fg),
                                            (' fo:background-color="#%s"', bg)])
# pylint: enable=C0301

ODT_TITLE_TEMPLATE = t('<text:p text:style-name="Title">%s</text:p>')
ODT_SUBTITLE_TEMPLATE = t('<text:p text:style-name="Subtitle">%s</text:p>')
ODT_META_FIELD_TEMPLATE = t('<text:p><text:span text:style-name="Underlined">'
                            '%s:</text:span> %s</text:p>')

ODT_LINK_TEMPLATE = t(
    '<text:a xlink:type="simple" xlink:href="%s" >%s</text:a>')
ODT_PARAGRAPH_TEMPLATE = t('<text:p>%s</text:p>')
ODT_BOOKMARK_TEMPLATE = lambda h: (
    '<text:bookmark-start text:name="%(h)s"/>'
    '<text:bookmark-end text:name="%(h)s"/>' % {'h':h})

ODT_SPAN_TEMPLATE = t('<text:span text:style-name="%s">%s</text:span>')
ODT_PLAIN_SPAN_TEMPLATE = t('<text:span>%s</text:span>')

# svg:width="%(width)s" svg:height="%(height)s"
ODT_IMAGE_TEMPLATE = t('''\
<draw:frame svg:x="0cm" svg:y="0cm"\
 svg:width="%(width)scm" svg:height="%(height)scm"\
 draw:style-name="Image" text:anchor-type="%(anchor)s" draw:z-index="0">\
<draw:image xlink:href="%(href)s" xlink:type="simple" xlink:show="embed"\
 xlink:actuate="onLoad"/>\
</draw:frame>''')


COLOR_SPAN_REX = re.compile(
    r'^SpanColorFg((?:[0-9a-f]{6})?)Bg((?:[0-9a-f]{6})?)$')
def make_color_style_name(fg, bg):
    ans = 'SpanColorFg%sBg%s' % (fg[1:], bg[1:])
    assert COLOR_SPAN_REX.match(ans)
    return ans


def make_odt_span(style=None): # pylint: disable=W0613
    def odt_span(a, b, required_styles, images):
        assert not a or not style
        if style or a:
            if a and a.values():
                assert a.keys() == ['style']
                sty = a['style']
                assert not set(sty) - set(COLOR_TYPES)
                addme = make_color_style_name(*(sty.get(k, '')
                                                for k in COLOR_TYPES))
            else:
                addme = style
            required_styles.add(addme)
            return ODT_SPAN_TEMPLATE(addme, odtify(b, required_styles, images))
        else:
            return ODT_PLAIN_SPAN_TEMPLATE(odtify(b, required_styles, images))
    return odt_span

def odt_link_or_bookmark(a, b, required_styles, images):
    if 'name' in a:
        return ODT_BOOKMARK_TEMPLATE(a['name'])
    return ODT_LINK_TEMPLATE(a['href'], odtify(b, required_styles, images))

def odt_para(a, b, required_styles, images):
    assert not a
    return ODT_PARAGRAPH_TEMPLATE(odtify(b, required_styles, images))

HTML_TO_ODT = {
    'b': make_odt_span('Bold'),
    'i': make_odt_span('Italic'),
    's': make_odt_span('Strikethrough'),
    'u': make_odt_span('Underlined'),
    'sub': make_odt_span('Subscript'),
    'sup': make_odt_span('Superscript'),
    'a': odt_link_or_bookmark,
    'p': odt_para,
    'span': make_odt_span(),
    }

def cleanse_internal(frags):
    return whack(lambda e: e not in HTML_TO_ODT, frags)

def odtify_basestring(s):
    return (cgi.escape(s)
            .replace(' ', '<text:s/>')
            .replace('\t', '<text:tab>'))

def odt_image(image, images):
    href = images.add_raw_data('Pictures/', image.data)
    pw, ph = images.get_size(images.normalize_known_transclusion(href))
    scale = float(image.style['width'].rstrip('%'))/100
    width = scale * images.textwidth_cm
    height = width * ph/pw
    anchor = 'as-char'
    # anchor = ('as-char' if image.style.get('display', 'inline') == 'inline'
    #           else 'paragraph')
    return ODT_IMAGE_TEMPLATE(href=href, width=width, height=height,
                              anchor=anchor)



def odtify(tree, required_styles, images):
    # FIXME(alexander): remove this disgusting crap;
    # how do Images work ATM?
    if isinstance(tree, literal.Bibliography):
        return odtify(tree.data, required_styles, images)
    if isinstance(tree, basestring):
        return odtify_basestring(tree)
    if isinstance(tree, list):
        return "".join(odtify(e, required_styles, images) for e in tree)
    if isinstance(tree, tuple):
        t, a, b = tree
        return HTML_TO_ODT[t](a, b, required_styles, images)
    if isinstance(tree, literal.Image):
        return odt_image(tree, images)
    else:
        log.warn('Fallthrough: %r', tree)
        return odtify(unparse_literal(tree), required_styles, images)



def meta_to_odt_xml(meta, transclusions):
    images = transclusions
    xml_frags = []
    required_styles = set()
    if meta:
        required_styles.add('Underlined')
    meta_copy = meta.copy()
    def add_frag(tmpl, *stuff):
        xml_frags.append(tmpl(odtify(list(stuff), required_styles, images)))
    title, subtitle = (meta_copy.pop(k, None) for k in ['title', 'subtitle'])
    if title:
        add_frag(ODT_TITLE_TEMPLATE, title)
    if subtitle:
        add_frag(ODT_SUBTITLE_TEMPLATE, subtitle)
    for k, v in meta_copy.iteritems():
        xml_frags.append(ODT_META_FIELD_TEMPLATE(
            *([odtify(x, required_styles, images) for x in [k, v]])))
    return parse_odt_frags(xml_frags), sorted(list(required_styles)), images

def ensure_minimal_styles(styles, required_styles):
    common_styles = styles.find(ns.office('styles'))
    for name in required_styles:
        if not common_styles.find(ns.style('style')+
                                  '[@'+ns.style('name')+'="%s"]' % name):
            style = (ODT_MINIMAL_STYLES.get(name) or
                     create_color_style(*COLOR_SPAN_REX.match(name).groups()))
            templated = (style(name) if name == 'Image'
                         else ODT_TEXT_STYLE_TEMPLATE(name, style))
            lxmlutil.extend(common_styles, parse_odt_frags(templated))

def parse_odt_frags(xml_frags):
    return lxmlutil.fromstringlist(xml_frags, ns)
