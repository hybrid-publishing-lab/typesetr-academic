#-*- file-encoding: utf-8 -*-
"""Module for representing images and other transclusions in odt files."""
import logging as log
import os.path
import cStringIO

import PIL.Image

from converter.digest import hexdigest
from converter.mimetype import extension

def to_data_url(data, mimetype):
    return 'data:%s;base64,%s' % (mimetype,
                                  data.encode('base64').replace('\n', ''))

def is_data_url(href):
    return href.startswith('data:')

def from_data_url(href):
    assert is_data_url(href)
    header, data = href.split(',', 1)
    assert header.endswith(';base64')
    mimetype = header.split(':')[1].split(';')[0]
    return data.decode('base64'), mimetype

def href_for_data(data, mimetype):
    new_href = hexdigest(data) + extension(mimetype)
    return new_href


THUMB_PIX = 64
THUMB_QUALITY = 80
class Transclusions(object):
    """All the embedded objects (right now, that's images) in a document.

    Transforms the images as needed (scales down to thumb nail size for
    testing) and allows to access their data in several ways: as a data-url,
    as bytes or by extracting all of them to the filesystem. Also maps the
    original href in the `includes_dict` to one that is a hash of the
    (untransformed) image data and mime type. This is so that several
    documents can be combined without having to worry about name clashes and
    also ensures there will be no "funky" filenames that e.g. LaTeX can't
    handle.
    """
    def __init__(self, includes_dict, out_dir=None, thumb=False):
        """Create a new Transclusions.

        * `includes_dict` maps hrefs to file objects
        * If `thumb` is `True`, scale down all images to thumbnail size.
        """
        self.out_dir = out_dir
        self.thumb = thumb
        self._original_href_to_new = {}
        self.new_href_to_original = {}
        self._transclusions = {}
        self._mimetypes = {}
        self._sizes = {}
        for name in includes_dict:
            raw_data = includes_dict[name].read()
            self.add_raw_data(name, raw_data)

    def _add(self, data, mimetype, original_href=None):
        new_href = href_for_data(data, mimetype)
        if new_href in self._transclusions:
            self._original_href_to_new[original_href] = new_href
            return self.new_href_to_original[new_href]
        if not original_href:
            original_href = new_href
        assert new_href.rsplit('.')[1] in ('jpg', 'png')
        self._transclusions[new_href] = data
        self._mimetypes[new_href] = mimetype
        self._original_href_to_new[original_href] = new_href
        self.new_href_to_original[new_href] = original_href
        return original_href

    def add_data_url(self, url):
        return self._add(*from_data_url(url))

    def add_literal_image(self, img):
        return self._original_href_to_new[self.add_raw_data(None, img.data)]

    def add_raw_data(self, name_or_prefix, raw_data):
        im = PIL.Image.open(cStringIO.StringIO(raw_data))
        size = im.size
        output = cStringIO.StringIO()
        filetype = im.format.lower()
        mimetype = 'image/' + filetype
        if self.thumb:
            im.thumbnail((THUMB_PIX,)*2, PIL.Image.ANTIALIAS)
            dpi = im.info.get('dpi', (72, 72))
            im.save(output, filetype, quality=THUMB_QUALITY,
                    dpi=[int(round(1. * dpi[i] * size[i] / im.size[i]))
                         for i in range(2)])
            data = output.getvalue()
        else:
            data = raw_data

        name = self._add(data, mimetype, original_href=name_or_prefix)
        new_href = self._original_href_to_new[name]
        self._sizes[new_href] = size
        return name


    def hexdigest(self):
        return hexdigest("".join(t.split('.')[0]
                                 for t in sorted(self._transclusions)))

    def normalize_known_transclusion(self, href):
        """Normalize hrefs.

        If `href` is a link to an embedded object in the original document,
        return a new, hash-based href, otherwise return `href`."""
        return self._original_href_to_new.get(href, href)

    def known_transclusion_to_data_url(self, href):
        """Transform (only) `href`s to embeded objects to data urls."""
        if href in self._transclusions:
            return to_data_url(self.get_data(href), self.get_mimetype(href))
        return href

    def handle_href(self, href, never_embed=False):
        new_href = (href if self.out_dir or never_embed
                    else self.known_transclusion_to_data_url(href))
        return new_href, href in self._transclusions

    def get_data(self, href):
        return self._transclusions[href]

    def get_mimetype(self, href):
        return self._mimetypes[href]

    def get_size(self, href):
        return self._sizes[href]

    def extract(self, out_dir):
        """Write all embedded objects to `out_dir`.

        The filename extensions will be derived

        """
        log.info('WRITING EMBEDDED_OBJECTS')
        for name in self._transclusions:
            assert not name[:1] in ['.', '/', '\\']
            dirname = os.path.join(out_dir, os.path.dirname(name))
            if not os.path.exists(dirname):
                os.mkdir(dirname)
            data = self._transclusions[name]
            outpath = os.path.join(out_dir, name)
            with open(outpath, 'wb') as f:
                f.write(data)

    def provide(self):
        if self.out_dir:
            self.extract(self.out_dir)

    def images(self):
        return {t: d for (t, d) in self._transclusions.iteritems()
                if self._mimetypes[t].startswith('image/')}

    def iteritems(self):
        return self._transclusions.iteritems()
