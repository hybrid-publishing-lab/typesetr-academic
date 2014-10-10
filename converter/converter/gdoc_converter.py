#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
r"""Converts odt to an internal representation, latex or (x)html5.

Bugs of this converter:

- The following items are not handled correctly:

  - indented text (treated as a list)

  - background color (adjacent background color blocks always will need to be
    merged, because trailing or leading whitespace won't be colored even if
    w/in a block w/ a particurlar color; also should probably use <mark> for
    this)

  - more than one level of sub and super(script) -- can't occur in Google Docs.

"""
# shut up about redefining format, basically
# pylint: disable=W0622

import argparse
from cStringIO import StringIO
from functools import partial
import glob
import json
import logging as log
import os
import pprint
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from pybtex.database.input import bibtex
import regex as re

from .docerror import missing_include
from . import docerror
from . import exit_code
from .internal import shared
from . import orderedyaml as yaml # pylint: disable=E0611
from . import postprocess
from . import stytempl
from .transclusions import Transclusions

from . import html_parser
from . import docx_parser
from . import odt_parser
from . import markdown_parser

from . import epub_writer
from . import html_writer
from . import internal_writer
from . import latex_writer
from . import meta_writer
from . import pickle_writer

from .docxlite import is_possibly_docx


WRITERS = dict((m.__name__.split('.')[-1].split('_')[0].replace('latex', 'tex'),
                m.write)
               for m in [epub_writer, html_writer, internal_writer,
                         meta_writer, latex_writer, pickle_writer])



def parsed_body_to_internal(head, parsed_body, out_file):
    print >> out_file, pprint.pformat((head, parsed_body))


def process(infilename, meta_schema, # pylint: disable=R0913,R0914
            make_transclusions,
            bibliography,
            asides,
            update_meta,
            rewritten_input):
    if infilename.lower().endswith('.docx'):
        pmod = docx_parser
    elif infilename.lower().endswith('.odt'):
        pmod = odt_parser
    elif infilename.lower().endswith('.html'):
        pmod = html_parser
    elif infilename.lower().rsplit('.', 1)[1] in ('md', 'txt', 'markdown'):
        maybe_meta, infilename = markdown_parser.to_html(infilename)
        update_meta = update_meta or maybe_meta
        pmod = html_parser
    else:
        assert False, "Unknown input type %s" % infilename.split('.')[-1]
    raw_body, transclusions, rewrite_info = pmod.parse_to_raw_body(
        infilename, rewritten_input, make_transclusions)
    unaugmented_meta, body = postprocess.postprocess(
        raw_body, transclusions, bibliography=bibliography, asides=asides)
    if update_meta is None:
        meta = meta_schema.validate_and_augment(unaugmented_meta)
    else:
        meta = meta_schema.validate_and_augment(update_meta)
        # FIXME(alexander): not sure why this is called on `update_meta`
        # and not *just* on `rewritten_input`
        pmod.rewrite_input(meta, unaugmented_meta, transclusions,
                           asides, rewrite_info)
    # FIXME(alexander): useful for now, but should be removed at some point
    assert not shared(body), "Ooopsy, accidentally caused some aliasing"

    if meta.items().get('bibliography') and not bibliography:
        link = meta.items()['bibliography'].to_string()
        missing_include('bibliography', link)
    transclusions.provide()
    return meta, body, transclusions

def make_pdf(tex_filename, style_template):
    out_dir = os.path.dirname(tex_filename)
    out_filename = tex_filename.replace('.tex', '.pdf')
    log.debug('make_pdf %s to %s', tex_filename, out_filename)

    makepdf_path = write_build_pdf_script(style_template, tex_filename)
    try:
        subprocess.check_call([makepdf_path], cwd=out_dir, stdout=sys.stderr)
    except:
        subprocess.call(['cat', tex_filename.replace('.tex', '.log')],
                        cwd=out_dir,
                        stdout=sys.stderr)
        raise
    return out_filename

def write_build_pdf_script(style_template, tex_filename):
    script_name = 'makepdf'
    styles_base = style_template.base_path
    script_template = os.path.join(styles_base, 'shared', 'latex', script_name)
    script_file = os.path.join(os.path.dirname(tex_filename), script_name)
    target_tex = os.path.basename(tex_filename)

    with open(script_template) as template:
        script_tmpl = template.read().decode('utf-8')
        interpolated = script_tmpl.replace('INTERPOLATETARGET', target_tex)
        with open(script_file, 'wb') as out_file:
            print >> out_file, interpolated.encode('utf-8')

    permissions = stat.S_IXUSR | stat.S_IRUSR
    os.chmod(script_file, permissions)
    return script_file

def make_png(pdf_filename, page_number, size):
    out_dir = os.path.dirname(pdf_filename)
    out_pattern, _ = os.path.splitext(pdf_filename)
    log.debug('make_png %s to %s', pdf_filename, out_pattern)
    subprocess.check_call(['pdftoppm', '-f', str(page_number),
                           '-l', str(page_number),
                           '-scale-to', str(size), '-png',
                           pdf_filename, out_pattern],
                          cwd=out_dir,
                          stdout=sys.stderr)
    #fix pdftoppm sometimes putting 0s before the page number (01 -> 1)
    files = glob.glob(out_pattern + '-*%d.png' % page_number)
    out_file = out_pattern + '-%d.png' % page_number

    assert len(files) != 0, \
        'Cannot locate generated preview file - expected %s' % out_file
    if len(files) > 1:
        log.error('Expected one preview picture, got %s', str(files))

    preview = files[0]
    if preview != out_file:
        shutil.move(preview, out_file)
    return out_file

def _should_update_meta(new_meta):
    if not new_meta:
        return None
    with open(new_meta) as nm:
        update_meta = yaml.load(nm.read())
    if update_meta is None:
        log.fatal("--new-meta file %s can't be empty; need at least {}",
                  new_meta)
        sys.exit(exit_code.USAGE_ERROR_EXIT)
    return update_meta

def _should_rewrite_input(rewritten_input, new_meta):
    if not rewritten_input:
        return None
    if new_meta is None: # NB: ``{}`` *is* valid!
        print >> sys.stderr, "Can't have --rewritten-input without --new-meta"
        sys.exit(exit_code.USAGE_ERROR_EXIT)
    return open(rewritten_input, 'wb')
# <http://docs.oasis-open.org/office/v1.2/os/
#  OpenDocument-v1.2-os-part3.html#a3_3MIME_Media_Type>
# this does not mention the \3\4 part, but this is confirmed in multiple sources
odt_check = re.compile('^PK\3\4.{26}' # pylint: disable=C0103
                       'mimetypeapplication/vnd.oasis.opendocument.text',
                       re.DOTALL).match


def _provide_infile(infile, tmp_dir):
    if infile == '-':
        infile = sys.stdin
    elif infile is not sys.stdin:
        return infile
    contents = sys.stdin.read()
    if odt_check(contents):
        suffix = '.odt'
    elif is_possibly_docx(contents):
        suffix = '.docx'
    elif contents.startswith('<'):
        suffix = '.html'
    else:
        suffix = '.md'
    with tempfile.NamedTemporaryFile(dir=tmp_dir,
                                     suffix=suffix,
                                     delete=False) as infile:
        infile.write(contents)
        return infile.name

def _write_archive(out_file, format, style_template, tmp_dir):
    # NB: special case writing a zip to stdout, since stdout is not
    # seekable but ZipFile requires that, so we pass a StringIO instead
    sio, out_file = ((False, out_file) if out_file != sys.stdout else
                     (True, StringIO()))
    # FIXME(alexander):
    # fix this so zip does not include crap for tex etc.
    # although this is helpful for development
    with zipfile.ZipFile(out_file, 'w') as archive:
        for root, dirs, fns in os.walk(tmp_dir):
            dirs.sort()
            fns.sort()
            for fn in fns:
                archive.write(os.path.join(root, fn), fn)
        if format == 'html': # XXX: abstract that
            for n, path in style_template.includes_for(format).iteritems():
                archive.write(arcname=n, filename=path)
    if sio:
        sys.stdout.write(out_file.getvalue())


def _maybe_clean(clean, tmp_dir, out_file, rewritten_input):
    if out_file is not sys.stdout:
        out_file.close()
    if rewritten_input:
        rewritten_input.close()

    if clean:
        shutil.rmtree(tmp_dir)
    else:
        print >> sys.stderr, "Not cleaning up."
        print >> sys.stderr, "Worked in %s, output to %s." % (
            tmp_dir, out_file.name)

def _provide_outfile(in_filename, out_filename, format, packaging):
    if out_filename and out_filename != '-':
        out_prefix, ext = os.path.splitext(out_filename)
        if ext == '.zip':
            packaging = packaging or 'zip'
            out_prefix, ext = os.path.splitext(out_prefix)
        out_file = open(out_filename, 'wb')
        if not format:
            format = ext[1:] if ext != '.yml' else 'meta'
    else:
        out_prefix, _ = os.path.splitext(in_filename)
        out_file = sys.stdout
        format = format or 'pdf'
    return out_file, out_prefix, format, packaging

def _output_it(mbt, out_file, tmp_dir,  # pylint: disable=R0913
               out_prefix, style_template, args, bib):
    tmp_prefix = os.path.join(tmp_dir, os.path.basename(out_prefix))
    out_ext = args.format if args.format not in ('png', 'pdf') else 'tex'
    tmp_outfilename = tmp_prefix + '.' + out_ext
    with open(tmp_outfilename, 'wb') as tmp_outfile:
        result_f = tmp_outfilename
        if args.format in ('tex', 'pdf', 'png'):
            style_template.copy_latex_includes(tmp_dir)
            if args.bibliography:
                shutil.copy(args.bibliography,
                            os.path.join(tmp_dir, 'bibliography.bib'))
        write = WRITERS[out_ext]
        #log.debug('%s %r to %r', write.__name__, odt_filename, tmp_outfilename)
        write(tmp_outfile, style_template, bib, *mbt)
    if args.format in ('pdf', 'png'):
        result_f = make_pdf(tmp_outfilename, style_template)
        if args.format == 'png':
            result_f = make_png(result_f, args.page, args.pixels)

    if args.packaging == 'zip':
        _write_archive(out_file, args.format, style_template, tmp_dir)
    else:
        with open(result_f, 'rb') as result:
            out_file.write(result.read())



def parse_args():
    parser = argparse.ArgumentParser()
    arg = parser.add_argument

    arg("--format", "-f",
        choices=['tex', 'pdf', 'png', 'html', 'epub', 'meta',
                 'internal', 'pickle'],
        help="The output format you'd like to convert to")
    arg("infile", nargs='?', default=sys.stdin,
        help='The odt file to convert (default: stdin)')
    arg("outfile", nargs='?',
        help='The name of the output file (default: stdout)')
    arg("--style", "-s", default='typesetr/report-pitch',
        help="The style (&type) of document to create")
    arg('--style-base', default='/opt/typesetr/styles',
        help='where to find the styles')
    arg('--page', type=int, default=1,
        help="One-based index of the page to render")
    arg('--pixels', type=int, default=600,
        help="PNG image size")
    arg('--no-clean', action="store_true", default=False,
        help="Do not remove temporary files after success.")
    arg("--gdoc-meta", default='{}',
        help="The metadata from google in JSON form")
    arg("--include", "-i", action='append', default=[],
        help="The gdoc id/url of the include files")
    arg("--new-meta", type=str,
        help="New (YAML) meta data for the document to update")
    arg("--rewritten-input", type=str,
        help=("In combination w/ --new-meta: write out an updated input file"))
    arg("--lofi", action="store_true",
        help="Rescale all images to very low resolution; for testing only.")
    arg("--zip", dest='packaging', action="store_const", const='zip',
        help="Package the output up in a zip archive")
    arg("--bibliography", "-b",
        help="The bibliography to use, if any")
    arg("--comments", action="store_true", dest="asides",
        help="Whether to preserve comments")
    arg("-v", "--verbose", action="count", default=1,
        help="Increase diagnostic output verbosity.")
    arg("-q", "--quiet", help="Never print any diagnostic output.",
        dest='verbose', action="store_false")
    arg("--error", default='log', choices=['log', 'raise', 'debug'],
        help="For debugging: what to do on document errors")
    return parser.parse_args()

def set_log_level(v):
    # wouldn't it be nice if logging just exposed an ordered list of levels?
    log.basicConfig(level=max(log.CRITICAL-v*10, log.DEBUG))

def main():
    exit_code.final_exit_code = 0 # hack for consecutive ipython runs
    args = parse_args()
    set_log_level(args.verbose)

    docerror.ON_ERROR = args.error

    update_meta = _should_update_meta(args.new_meta)
    rewritten_input = _should_rewrite_input(args.rewritten_input, update_meta)

    args.style = stytempl.ensure_style_exists(args.style_base, args.style)

    style_template = stytempl.StyleTemplate(
        args.style_base, args.style, gdoc_meta=json.loads(args.gdoc_meta))

    tmp_dir = tempfile.mkdtemp(prefix='typesetr')
    infilename = _provide_infile(args.infile, tmp_dir)
    out_file, out_prefix, args.format, args.packaging = _provide_outfile(
        infilename, args.outfile, args.format, args.packaging)

    log.info("Using dir %s files: %s %s", tmp_dir, args.infile, args.outfile)

    bib = args.bibliography and (bibtex.Parser().parse_file(args.bibliography))

    # FIXME: Use a proper data structure to keep track of cited entries
    # in a document
    if bib:
        bib.cited = set()

    mbt = process(infilename=infilename,
                  meta_schema=style_template.meta_schema,
                  bibliography=bib,
                  asides=args.asides,
                  update_meta=update_meta,
                  rewritten_input=rewritten_input,
                  make_transclusions=partial(
                      Transclusions,
                      thumb=args.lofi,
                      out_dir=(tmp_dir if (args.format in ('pdf', 'png')
                                           or args.packaging == 'zip')
                               else None)))
    _output_it(mbt, out_file, tmp_dir, out_prefix, style_template, args, bib)
    _maybe_clean(not args.no_clean, tmp_dir=tmp_dir,
                 out_file=out_file, rewritten_input=rewritten_input)
    exit_code.exit()
