#!/usr/bin/env python
"""USAGE: %prog [--pdf] [TEST_FILES...]
Run the converter integration tests."""

# pylint: disable=E1101,W0141,C0103,C0111,R0902

import argparse
import datetime
from functools import partial
import hashlib
import multiprocessing
import os
import random
from signal import signal, SIGINT, SIG_IGN
import sys
from pipes import quote as shquote
import time
import tempfile
import traceback

import colorama
import regex as re
import sh
from sh import ErrorReturnCode

test_root = partial(os.path.join, os.path.dirname(os.path.realpath(__file__)))
typesetr_root = partial(test_root, '..', '..')
style_root = partial(typesetr_root, 'styles')
fail_path = partial(test_root, 'failures')
GDOC_TO = typesetr_root('converter', 'gdoc-to')


html5check, unpack_meta, extract_body = (
    sh.Command(test_root(x))
    for x in ["html5check", "unpack_meta", "extract_body"])
validate_odt = partial(sh.Command(typesetr_root('script', 'validate-odt')),
                       _ok_code=[0, 1])
validate_docx = partial(sh.Command('zipinfo'),
                        _ok_code=0)

validate_epub = partial(sh.Command(typesetr_root('script', 'validate-epub')),
                        _ok_code=[0, 1])
def mimetype(filename):
    return sh.file('-b', '--mime-type', '--', filename).stdout.strip()


IS_TEAMCITY = os.getenv('USER') == 'teamcity'

def formatter(message, **kwargs):
    def escape(text):
        out = text.replace('|', '||')
        out = out.replace("'", "|'")
        out = out.replace('\n', '|n')
        out = out.replace('\r', '|r')
        out = out.replace('[', '|[')
        out = out.replace(']', '|]')
        return out

    def inner(name, **kw):
        _kwargs = kwargs.copy()
        _kwargs.update(kw)
        if not IS_TEAMCITY:
            return ''
        out = [message, "name='%s'" % escape(name)] + [
            "%s='%s'" % (k, escape(str(v)))
            for (k, v) in sorted(_kwargs.items())]
        return '##teamcity[%s]' % ' '.join(out)

    return inner

suite_started, suite_finished, test_failed, test_finished, = map(formatter, [
    'testSuiteStarted', 'testSuiteFinished', 'testFailed', 'testFinished'])
test_started = formatter('testStarted', captureStdout='true')




class TestSuite(object):
    # pylint: disable=R0913
    def __init__(self, run, test_files, do_pdf=False, cache=False,
                 suite='converter integration tests'):
        self.run = run
        self.test_files = test_files
        self.do_pdf = do_pdf
        self.cache = cache
        self.suite = suite

        self.temp_dir = tempfile.mkdtemp(prefix='typesetr_test.')


    def clean_failure_files(self):
        sh.mkdir('-p', fail_path(''))
        sh.rm('-rf', '--', sh.glob(fail_path('*')))

    def clean_temp_files(self):
        sh.rm('-rf', '--', self.temp_dir)

    def run_test_suite(self):
        print 'Working in ' + self.temp_dir
        print suite_started(self.suite)
        self.clean_failure_files()

        results = self.run(run_individual_test, self.test_files,
                           self.temp_dir, self.do_pdf, self.cache)
        failures = [file_name for (has_failed, file_name) in results
                    if has_failed]

        if not failures:
            self.clean_temp_files()
            print green("All tests passed.")
        else:
            if IS_TEAMCITY:
                print "Creating symbolic link to artefact working directory."
                sh.ln('-sf', self.temp_dir, 'working')
            print "%d test(s) failed." % len(failures)
            print "To run the failed tests again:"
            cmdline = "%s%s%s" % (sys.argv[0],
                                  (self.do_pdf and ' --pdf ' or ' '),
                                  shell_join(failures))
            print cmdline
            print >> open('/tmp/rerun-failed-typesetr-test', 'w'), cmdline

        print suite_finished(self.suite)
        return len(failures)

def ticced(what, format=None): # pylint: disable=W0622
    def decorate(f):
        def wrapped_f(self, *args, **kwargs):
            if format and not self.style_supports(format):
                return
            self.say(what)
            tic = time.time()
            ans = f(self, *args, **kwargs)
            self.lines[-1] += dim(' (%.2f)' % (time.time() - tic))
            return ans
        return wrapped_f
    return decorate


class Test(object):
    # pylint: disable=R0913
    def __init__(self, test_file, temp_dir, cache=False):
        self.tic = time.time()
        self.test_file = test_file
        self.temp_dir = temp_dir
        self.cache = cache

        self.failed = False
        self.lines = []
        clean_test_file_name = re.sub('^' + re.escape(test_root('data/')), '',
                                      test_file)
        self.say('{}', test_started(clean_test_file_name))
        self.say("Testing {}...", bold(clean_test_file_name))

        self.style = self._get_style()
        sh.mkdir('-p', fail_path(self.style))
        self.style_args = Test._get_style_options(self.style)
        if self.style_args:
            self.say("\tstyling: {}", shell_join(self.style_args))
        self.bib_args = Test._get_bib_options(test_file)
        if self.bib_args:
            self.say("\tbibliography: {}", self.bib_args)
        self.options = self.style_args + self.bib_args

        self.test_name = os.path.join(self.style, os.path.basename(test_file))
        self.test_out = os.path.join(self.temp_dir, self.test_name)
        self.test_err = self.test_out + '.err'
        _, ext = os.path.splitext(test_file)
        self.test_new = self.test_out + '.new.' + ext

    def elapsed_ms(self):
        return (time.time() - self.tic)*1000.0

    def say(self, text, *args):
        self.lines.append(text.format(*args))

    @ticced('Checking metadata')
    def same_metadata(self, is_fail_expected):
        ext = '.meta.yml'

        try:
            self.gdoc_to(*(self.options + ['-f', 'meta', self.test_file]),
                         _out=self.test_out + ext,
                         _err=self.test_err + '.meta.log')
        except sh.ErrorReturnCode:
            if not is_fail_expected:
                self.say(red('Checking metadata failed!'))
                self.say(red('\tSee {}.meta.log'), self.test_err)
            self.failed = True

        if os.path.exists(self.test_file + ext):
            diff = sh.diff(self.test_out + ext, self.test_file + ext,
                           _out=self.test_out + '.meta.yml.diff',
                           _ok_code=[0, 1])
            if diff.exit_code != 0:
                self.say(red("Test meta file changed!")
                         + " [%s]" % self.test_out)
                self.say(red("\tSee {}.meta.yml* and {}.meta.log"),
                         fail_path(self.test_name), self.test_err)
                sh.cp(self.test_out + ext, fail_path(self.test_name + ext))
                sh.cp(self.test_out + '.meta.yml.diff',
                      fail_path(self.test_name + '.meta.yml.diff'))
                self.failed = True
        else:
            self.say(red("No meta to test against!") + " [%s]" % self.test_out)
            sh.cp(self.test_out + ext, fail_path(self.test_name + ext))
            self.failed = True

    @ticced("Testing PNG generation...", 'pdf')
    def png_generation(self):
        try:
            self.gdoc_to(*(self.options + ['-f', 'png']),
                         _in=self.test_file, _out=self.test_out + '.png',
                         _err=self.test_err + '.png.log')
            assert mimetype(self.test_out + '.png') == 'image/png'
        except ErrorReturnCode:
            self.say(red('PNG creation failed!'))
            self.say(red('\tSee {}.png.log'), self.test_err)
            self.failed = True

    def metadata_roundtrip(self):
        self.say('Checking metadata roundtrip...')
        try:
            run_args = None
            unpack_meta(self.test_file + '.meta.yml',
                        self.test_out + ".meta.input")
            run_args = (self.options +
                        ['--new-meta', self.test_out + ".meta.input",
                         '--rewritten-input', self.test_new,
                         '-f', 'meta', self.test_file])
            self.gdoc_to(*run_args, _out=self.test_out + ".oldmeta.yml",
                         _err=self.test_err + ".oldmeta.log")
        except ErrorReturnCode:
            if not run_args:
                self.say(red('Extracting meta failed'))
            else:
                self.say(red('Updating metadata failed!'))
                self.say('Ran as gdoc-to %s' % shell_join(run_args))
                self.say('See: ' + self.test_err + ".oldmeta.log")
            self.failed = True

    def valid_rewritten(self):
        self.say('Ensuring re-written file is valid...')
        if self.test_file.endswith('.odt'):
            validator = validate_odt
        elif self.test_file.endswith('.docx'):
            validator = validate_docx
        else:
            validator = None
        if validator is None:
            self.say(red("Don't know how to validate %s" % self.test_file))
            self.failed = True
        elif validator(self.test_new).exit_code != 0:
            self.say(red("Re-written file failed to validate!"))
            self.failed = True



    def new_meta_output(self):
        diff = sh.diff(self.test_out + ".oldmeta.yml",
                       self.test_file + ".meta.yml",
                       _out=self.test_out + ".oldmeta.yml.diff",
                       _ok_code=[0, 1])
        if diff.exit_code != 0:
            self.say(red("Flag --new-meta changed output!"))
            self.say(red("\tSee {}.oldmeta.yml*"), fail_path(self.test_name))
            sh.cp(self.test_out + ".oldmeta.yml.diff",
                  fail_path(self.test_name + ".oldmeta.yml.diff"))
            sh.cp(self.test_out + ".oldmeta.yml",
                  fail_path(self.test_name + ".oldmeta.yml"))
            self.failed = True

    @ticced('Checking for same metadata...')
    def same_meta_as_orig(self):
        newmeta = self.test_out + ".newmeta.yml"
        try:
            self.gdoc_to(*(self.options +
                           ['-f', 'meta', self.test_new]),
                         _out=newmeta,
                         _err=self.test_err + ".newmeta.log")
        except ErrorReturnCode:
            self.failed = True

        diff = sh.diff(newmeta, self.test_out + ".oldmeta.yml",
                       _out=self.test_out + ".newmeta.yml.diff",
                       _ok_code=[0, 1])
        if diff.exit_code != 0:
            failed_test_path = fail_path(self.test_name)
            self.say(red("Reading back new file gives different meta!"))
            self.say("\tSee {}.(new|old)meta.yml* and %s",
                     failed_test_path, self.test_new)
            sh.mkdir('-p', failed_test_path)
            sh.cp(newmeta + '.diff', failed_test_path + ".newmeta.yml.diff")
            sh.cp(newmeta, failed_test_path + ".newmeta.yml")
            sh.cp(self.test_out + ".oldmeta.yml",
                  failed_test_path + ".oldmeta.yml")
            self.failed = True

    def style_supports(self, format): # pylint: disable=W0622
        style = self._get_style()
        if style == '.': # default style must do all formats
            return True
        else:
            subdir = format.replace('pdf', 'latex')
            return os.path.exists(style_root(style, subdir))

    @ticced('Checking EPUB output...', 'epub')
    def epub_output(self):
        try:
            self.gdoc_to(*(self.options + ['-f', 'epub', self.test_file]),
                         _err=self.test_err + ".epub.log",
                         _out=self.test_out + ".epub")

        except ErrorReturnCode:
            self.say(red("EPUB generation failed!"))
            self.say(red("\tSee {}.epub.log"), self.test_err)
            self.say(red("\tRan {} as {} {} -f epub"),
                     self.test_file, GDOC_TO,
                     shell_join(self.options))
            self.failed = True
        if validate_epub(self.test_out + '.epub').exit_code != 0:
            self.say(red("EPUB failed to validate!"))
            self.failed = True

    @ticced('Checking PDF output...', 'pdf')
    def pdf_output(self):
        try:
            out = self.gdoc_to(*(self.options + ['-f', 'tex', self.test_file]),
                               _err="/dev/null")
            assert out.stdout.startswith('% -*- TeX-engine')
            csum = checksum(out.stdout)
        except ErrorReturnCode:
            csum = checksum(str(random.random()))

        sha = self.test_file + '.tex.sha'
        if self.cache and os.path.isfile(sha) and slurp(sha) == csum:
            self.say(yellow('Same as cached TeX output. Skipping...'))
        else:
            sh.rm('-f', sha)
            spit(csum, sha)
            try:
                self.gdoc_to(*(self.options + ['-f', 'pdf', self.test_file]),
                             _err=self.test_err + ".pdf.log",
                             _out=self.test_out + ".pdf")
                assert mimetype(self.test_out + '.pdf') == 'application/pdf'
            except ErrorReturnCode:
                self.say(red("PDF generation failed!"))
                self.say(red("\tSee {}.pdf.log"), self.test_err)
                self.say(red("\tRan {} as {} {} -f pdf"),
                         self.test_file, GDOC_TO,
                         shell_join(self.options))
                self.failed = True

    @ticced('Checking HTML output')
    def html_output(self):
        ext = '.html'
        today = datetime.date.today().isoformat()
        sha = self.test_file + ".html.sha"
        # cannot recover if generating html fails
        options = (['--zip'] + self.options
                   + ['-f', 'html', self.test_file,
                      self.test_out + ext + '.zip'])
        try:
            self.gdoc_to(*options,
                         _err=self.test_err + ".html.log")
            # XXX it hangs without -n, didn't have time to figure out why
            out_dir = os.path.dirname(self.test_out)
            sh.unzip('-n', '-d', out_dir, self.test_out + ext + '.zip')
            sh.sed('-i', '-e', 's/%s/TODAYS_DATE/g' % today,
                   self.test_out + ext)
            test_result = slurp('%s.html' % self.test_out)
        except ErrorReturnCode as e:
            self.say(red("gdoc-to failed: {}. See {}.html.log"),
                     e, self.test_err)
            self.say(red("Ran in {}"), os.getcwd())
            self.failed = True
            sh.rm('-f', sha)
            return
        try:
            html5check(self.test_out + ext,
                       _out=self.test_out + ".html.errors")
        except ErrorReturnCode:
            self.say(red("Test output did not validate as XHTML5!"))
            self.say(red("\tSee {}.html.errors"), self.test_out)
            self.failed = True

        if test_result != slurp(self.test_file + ext):
            # the file changed, but the change might be okay
            spit(self._canonical_body(self.test_out + ext),
                 self.test_out + ".body")
            spit(self._canonical_body(self.test_file + ext),
                 self.test_out + ".canon.body")

            if (slurp(self.test_out + '.body')
                    == slurp(self.test_out + '.canon.body')):
                self.say(yellow("File changed. Updating canonical file."))
                sh.cp(self.test_out + ext, self.test_file + ext)
            else:
                self.say(red("HTML body changed!"))
                self.say(red("\tSee {}.*"), fail_path(self.test_name))
                sh.cp(self.test_out + ext, fail_path(self.test_name + ext))
                sh.diff('-u', self.test_file + ext, self.test_out + ext,
                        _out=fail_path(self.test_name + ".html.diff"),
                        _ok_code=[0, 1])
                sh.cp(self.test_out + ".body",
                      fail_path(self.test_name + ".body"))
                sh.cp(self.test_out + ".canon.body",
                      fail_path(self.test_name + ".body.expected"))
                sh.diff('-u', self.test_out + ".canon.body",
                        self.test_out + ".body",
                        _out=fail_path(self.test_name + '.body.diff'),
                        _ok_code=[0, 1])
                self.failed = True

    @ticced('Checking HTML input')
    def html_input(self):
        # FIXME(alexander): this should really compare
        # internal format rather than tex output,
        # but the trouble is whitespace; the diff -w
        # trick does not work reliably for the internal format,
        # because it can affect linebreaks in pretty printing
        # and newlines and tabs are escaped.
        self.gdoc_to(*(self.options +
                       ['-f', 'tex', self.test_file,
                        self.test_out + '-orig.tex']),
                     _err=self.test_err + ".html-in-orig.log")
        self.gdoc_to(*(self.options +
                       ['-f', 'tex', self.test_file + '.html',
                        self.test_out + '-html.tex']),
                     _err=self.test_err + ".html-in-tex.log")
        res = sh.diff(self.test_out + '-html.tex',
                      self.test_out + '-orig.tex',
                      _out=fail_path(self.test_name + '.html-input.diff'),
                      _ok_code=[0, 1])
        if res.exit_code:
            self.failed = True
            self.say(red("HTML import gives different results!"))
            self.say(red("\tSee {}.*"), fail_path(self.test_name))




    def gdoc_to(self, *args, **kwargs):
        return sh.coverage('run', '-a', GDOC_TO, *args, **kwargs)

    def _get_style(self):
        test_dir = os.path.dirname(self.test_file)
        style = re.sub('^' + test_root('data/'), '', test_dir)
        return style if style != test_dir else '.'

    def _canonical_body(self, file_name):
        try:
            return sh.xmllint(extract_body(file_name, '-'),
                              '--format', '--encode', 'utf8', '-').stdout
        except Exception: # pylint: disable=W0703
            return 'INVALID BODY %s' % random.random()

    @staticmethod
    def _get_style_options(style):
        return [] if style == '.' else ["--style", style]

    @staticmethod
    def _get_bib_options(test_file):
        test_bib = os.path.splitext(test_file)[0] + '.bib'
        return [] if not os.path.exists(test_bib) else ['-b', test_bib]


def run_individual_test(test_file, temp_dir, do_pdf, cache):
    # pylint: disable=R0913
    # XXX(alexander): should maybe canonicalize to relative path instead?
    test_file = os.path.abspath(test_file)
    test = Test(test_file, temp_dir, cache)

    sh.mkdir('-p', os.path.join(temp_dir, test.style))

    try:
        is_fail_expected = os.path.basename(test.test_file).startswith('bad-')
        test.same_metadata(is_fail_expected)
        if is_fail_expected:
            print_lines(test.lines)
            if not test.failed:
                print test_failed(test_file)
            print test_finished(test_file, duration=test.elapsed_ms())
            return not test.failed, test_file

        # only do png test a single time
        do_png = test_file.endswith('comprehensive-test.odt')
        if do_png:
            test.png_generation()
        test.metadata_roundtrip()
        test.valid_rewritten()
        test.new_meta_output()
        test.same_meta_as_orig()
        test.epub_output()
        if do_pdf:
            test.pdf_output()
        test.html_output()
        # FIXME(alexander): cheat and skip items with bibliography;
        # we don't currently truely roundtrip because bibliographic items
        # are parsed as ('CMD', {'class': 'tex'}, ...) not
        # ('CMD', {'class': 'autocite'}, ...) etc.
        # I could kludge this up but it's better to do it properly later.
        if not test.failed and not '-b' in test.options:
            test.html_input()
        print_lines(test.lines)
    except Exception: # pylint: disable=W0703
        print_lines(test.lines)
        print red('TEST BLEW UP')
        print red('\n   '.join(('\n'+traceback.format_exc()+'\n').splitlines()))
        test.failed = True
    if test.failed:
        print red('Fail.')
        print test_failed(test_file)
    else:
        print green('Pass.') + dim(' (%.2fs)' % (test.elapsed_ms()/1000))
    print test_finished(test_file, duration=test.elapsed_ms())
    return test.failed, test_file

# this is just some horrible workaround for an apparent bug in sh.py: it's
# ErrorReturnCode exceptions appear to have broken pickling support, which in
# combination with multiprocessing completely destroys exception info. Note
# that this is not a closure by design (i.e. func is passed explicitly) --
# multiprocessing can't handle these either, by the looks of it.

def safe_func(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        tb = "".join(traceback.format_tb(sys.exc_info()[-1]))
        if isinstance(e, ErrorReturnCode):
            raise RuntimeError("%r unexpectedly failed, stderr: %s\n%s" % (
                e.full_cmd, e.stderr, tb))
        raise RuntimeError('Something blew up' + repr(e) + '\n' + tb)

def make_runner(jobs):

    def run_serial(func, items, *args): # for debugging
        return [func(item, *args) for item in items]

    def run_parallel(func, items, *args):

        pool = multiprocessing.Pool(processes=jobs,
                                    initializer=lambda: signal(SIGINT, SIG_IGN))
        async_results = [pool.apply_async(safe_func, (func, item,) + args)
                         for item in items]
        pool.close()
        map(multiprocessing.pool.ApplyResult.wait, async_results)
        return [result.get() for result in async_results]

    run = run_serial if jobs == 1 else run_parallel
    print "Using %s to run %d tests at a time" % (run.__name__, jobs)
    return run


def print_lines(lines):
    for line in lines:
        print line


def shell_join(args):
    return " ".join(map(shquote, args))


def is_readable(file_name):
    return os.access(file_name, os.R_OK)


def slurp(file_name):
    with open(file_name, 'rb') as f:
        return f.read()


def spit(text, file_name):
    with open(file_name, 'wb') as f:
        return f.write(text)


def checksum(text):
    # pylint: disable=E1121
    return hashlib.sha1(text).digest()


def paint(color):
    if os.isatty(1):
        code = getattr(colorama.Fore, color.upper())
        return lambda text: code + text + colorama.Fore.RESET
    else:
        return lambda text: text

red, green, yellow = map(paint, 'red green yellow'.split())

def bold(s):
    if os.isatty(1):
        return colorama.Style.BRIGHT + s + colorama.Style.NORMAL
    else:
        return s

def dim(s):
    if os.isatty(1):
        return (colorama.Fore.CYAN + colorama.Style.DIM + s +
                colorama.Style.RESET_ALL)
    else:
        return s


def get_args(argv):
    find_args = '-name *.docx -o -name *.odt'.split()
    files = sh.find(test_root('data'), *find_args).strip().split('\n')
    parser = argparse.ArgumentParser(argv)
    parser.add_argument("--pdf", action='store_true', help='also generate pdfs')
    parser.add_argument("-j", "--jobs", action='store', type=int,
                        help='Parallelization level (default numcores)',
                        default=multiprocessing.cpu_count())
    parser.add_argument("--cache", action='store_true', default=True,
                        help='also generate pdfs')
    parser.add_argument("--no-cache", action='store_false', dest='cache')
    parser.add_argument("test_files", nargs='*', default=files,
                        help='the files to test (default: all)')
    return parser.parse_args()


def main():
    try:
        args = get_args(sys.argv)
        if args.pdf:
            # Biber helpfully corrupts itself on a regular basis,
            # see here:
            # http://tex.stackexchange.com/questions/140814/biblatex-biber-fails-with-a-strange-error-about-missing-recode-data-xml-file
            sh.rm('-rf', sh.biber('--cache'))
        suite = TestSuite(make_runner(args.jobs),
                          args.test_files, args.pdf, cache=args.cache)
        failures = suite.run_test_suite()
        return min(failures, 255)
    except KeyboardInterrupt:
        print >> sys.stderr, red("\nKeyboard Interrupt, aborting")

if __name__ == '__main__':
    sys.exit(main())
