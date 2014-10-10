#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
r"""This module encapsulates a style/ directory entry.
"""
from distutils.dir_util import copy_tree # pylint: disable=E0611,F0401
import glob
import logging as log
import os
import os.path
import sys

import regex as re

from . import exit_code
from . import orderedyaml as yaml # pylint: disable=E0611
from . import metainfo

# pylint: disable=W0622
class StyleTemplate(object): # pylint: disable=R0902
    def __init__(self, base_path, style_name, gdoc_meta):
        self.gdoc_meta = gdoc_meta
        self.base_path = base_path

        self._output_format_supported = {}
        self._already_warned_about = set()

        if style_name[0] in ('.', '/'):
            self.style_path = style_name
        else:
            self.style_path = os.path.join(self.base_path, style_name)
        self.latex_path = os.path.join(self.style_path, 'latex', 'include')
        self.latex_template = os.path.join(self.format_dir('tex'),
                                           'template', 'template.tex')
        self.epub_include = os.path.join(self.style_path, 'epub', 'include')
        # what does h1 correspond to?
        section_file = os.path.join(self.style_path, 'latex',
                                    'section-corresponds-to')
        if os.path.exists(section_file):
            with open(section_file) as f:
                self.section_corresponds_to = f.read()
                log.debug('a section is %s', self.section_corresponds_to)
        else:
            self.section_corresponds_to = 'h1'
        self.h_shift = 0 # hardcode section level shift for html ATM
        # meta info
        meta_file = os.path.join(self.style_path, 'metadata.yml')
        with open(meta_file) as f:
            self.meta_schema = metainfo.MetaSchema(yaml.load(f), self.gdoc_meta)

    @staticmethod
    def format_subdir(format):
        return {'tex': 'latex', 'pdf': 'latex'}.get(format, format)

    def format_dir(self, format):
        """Falls back to a default style if the format is not supported."""
        if self.supports_format(format):
            style_path = self.style_path
        else:
            style_path = os.path.join(self.base_path, 'shared', 'fallbacks')
            warn_key = 'format_dir(%r)' % format
            if warn_key not in self._already_warned_about:
                self._already_warned_about.add(warn_key)
                log.warn('%s not supported by %s; using fallback style %s',
                         format, self.style_path, style_path)
        return os.path.join(style_path, self.format_subdir(format))

    def supports_format(self, format):
        # XXX: premature caching?
        if format not in self._output_format_supported:
            self._output_format_supported[format] = os.path.exists(
                os.path.join(self.style_path, self.format_subdir(format)))
        return self._output_format_supported[format]

    def copy_latex_includes(self, target):
        # Copy all shared and style-specific includes to an 'includes' dir
        # within the target dir.
        target_dir = os.path.join(target, 'include')
        shared_includes = os.path.join(
            self.base_path, 'shared', 'latex', 'include')
        copy_tree(shared_includes, target_dir)
        if os.path.isdir(self.latex_path):
            copy_tree(self.latex_path, target_dir)

    def includes_for(self, format):
        # NB! this needs to be tightened up if the style templates
        # are not trusted to prevent reading random FS content
        ans = {}
        include_dir = os.path.join(self.format_dir(format), "include")
        for d, dirs, files in os.walk(include_dir):
            dirs.sort()
            files.sort()
            rel_d = os.path.relpath(d, include_dir)
            for fn in files:
                ans[os.path.join(rel_d, fn)] = os.path.join(d, fn)
        return ans

    def html_template(self, inline, title, lang, body):
        if isinstance(body, unicode):
            body = body.encode('utf-8')
        if isinstance(title, unicode):
            title = title.encode('utf-8')
        from converter.html_writer import write_body
        wrapper = {
            # pylint: disable=C0326
            'css': [lambda href:    ('link',
                                     {'rel': 'stylesheet', 'href': href}, []),
                    lambda content: ('style', {}, [content])],
            'js':  [lambda href:    ('script', {'src': href}, []),
                    lambda content: ('script', {}, [content])],
        }
        includes = self.includes_for('html')
        assert 'css/stylesheet.css' in includes
        indent = '  '
        head_parts = []
        for href, fn in includes.iteritems():
            wrap = wrapper[href.rsplit('.', 1)[1]][inline]
            if inline:
                with open(fn, 'rb') as f:
                    head_parts.append(wrap(f.read()))
            else:
                head_parts.append(wrap(href))
        html_head = indent + write_body(head_parts, indent=indent)
        with open(os.path.join(self.format_dir('html'),
                               'template', 'template.html')) as f:
            return (f.read() % dict(title=title,
                                    lang=lang,
                                    body=body,
                                    head=html_head,
                                   ))

def available_styles(base):
    return [style
            for style in (f[len(base)+1:] for f in glob.glob(base + '/*/*'))
            if not style.startswith('shared' + os.path.sep)]

def ensure_style_exists(base, style):
    style_path = os.path.join(base, style)
    metadata_path = os.path.join(style_path, 'metadata.yml')
    available = available_styles(base)
    if os.path.exists(metadata_path):
        return style_path

    candidates = [p for p in available
                  if re.search(re.escape(style).replace(r'\/', '.*/.*'), p)]
    if len(candidates) == 1:
        fullstyle, = candidates
        log.warn('Assuming %r means %r, but please specify the full style!',
                 style, fullstyle)
        return fullstyle

    print >> sys.stderr, (
        'ERROR: Style %s does not exist.\n'
        'The following styles are available in %s:\n%s' % (
            style_path, base,
            '\n'.join('   %s %s' % (' *'[a in candidates], a)
                      for a in available)))
    sys.exit(exit_code.USAGE_ERROR_EXIT)
