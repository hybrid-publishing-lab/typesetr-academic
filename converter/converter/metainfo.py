#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
from collections import OrderedDict
import copy
import logging as log

from converter.digest import hexdigest
from converter.docerror import metaproblem, metainfoinfo
from converter.literal import (parse_literal, Bibliography,
                               PY_TYPE_TO_TYPESETR_TYPES)
from converter.unparse import unparse_literal
from converter import postprocess
from converter import spellsuggest


TYPE_EXAMPLES = {
    'boolean': '"yes" or "no"',
    'multiline': ('text separated by semicolons, e.g. '
                  '"James Bond; MI 6; A3036 Lambeth; London"'),
    'date': 'e.g. "1999-12-31" for the last day of the old millennium',
    'text': 'any text, no formatting',
    'rich-text': (
        'any text, with optional basic formatting, like bold or italic'),
    'bibliography': 'A link to a zotero bibliography',
    'lang': 'a language code, e.g. "en" for English',
    'image': 'a google docs image or drawing',
    }

_BAD_VALS = (set(x for tup in PY_TYPE_TO_TYPESETR_TYPES.values()
                 for x in tup).symmetric_difference(set(TYPE_EXAMPLES)))
assert not _BAD_VALS, ('broken types: %r' % _BAD_VALS)


class MetaInfo(object):
    def __init__(self, d):
        assert isinstance(d, OrderedDict)
        self.d = d # pylint: disable=C0103
        if self.has_errors():
            metaproblem(self.d)
        else:
            metainfoinfo(self.d)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, self.d)

    @staticmethod
    def _parse(v):
        return parse_literal((v['canonical'] if 'canonical' in v
                              else v['supplied']),
                             v.get('type', 'text'))


    def raw_items(self):
        """Get the metadata as supplied in input document"""
        return OrderedDict((k, self._parse(v))
                           for k, v in self.d.iteritems() if 'supplied' in v)

    def items(self):
        return OrderedDict((k, self._parse(v))
                           for k, v in self.d.iteritems()
                           if 'error' not in v or 'canonical' in v)

    def hexdigest(self):
        return hexdigest(repr("".join(self.items())))

    def has_errors(self):
        return any('error' in v for v in self.d.itervalues())



class MetaSchema(object):
    def __init__(self, h, gdoc_meta={}): # pylint: disable=W0102
        # treat the the default value for title specially -- use gdoc title if
        # no value is supplied. Note that we still mark title as a required
        # field in many styles -- a seeming contradiction to having a default
        # value. The answer is that it makes sense to treat the title
        # specially because it's pervasive and we don't want user documents to
        # blow up if they don't have a title given that we can infer a
        # sensible default from the document name. OTOH, we *do* want to
        # require the title in the new document entry mask.
        # pylint: disable=C0330
        h = copy.deepcopy(h)
        if 'title' in h and 'default' not in h['title']:
            h['title']['default'] = gdoc_meta.get('title', '')
        self._info = dict((k, self._canonicalize(k, v))
                          for (k, v) in ([
                                  ('lang', dict(type='lang',
                                                default='en',
                                                label='Language')),
                              ] + h.items()))
        # bake in lang for all styles irrespective of metadata.yml
        self._defaults = dict(
            (k, v['default']) for k, v in self._info.iteritems()
            if 'default' in v)
        self._required = dict(
            (k, v['type']) for (k, v) in self._info.iteritems()
            if v['required'])

    @staticmethod
    def default_label(k):
        return k.capitalize()

    @staticmethod
    def metatype_to_default(t):
        return {'text'        : '',
                'rich-text'   : '',
                'bibliography': '',
                'boolean'     : 'no',
                'date'        : 'today',
                'image'       : '',
                'multiline'   : '',
                'lang'        : 'en',
               }[t]

    @classmethod
    def _canonicalize(cls, k, v):
        defaults = dict(required=False,
                        label=cls.default_label(k))
        if not v:
            v = defaults
        v = v.copy()
        for dk, dv in defaults.iteritems():
            if dk not in v:
                v[dk] = dv
        if 'type' not in v:
            v['type'] = 'text'
        if 'default' not in v: # even required values get a default
            v['default'] = cls.metatype_to_default(v['type'])
        assert isinstance(v['default'], basestring)
        return v

    def augment_with_defaults(self, meta):
        return dict(self._defaults.iteritems(),
                    **meta)

    def validate_and_augment(self, meta): # pylint: disable=R0912
        canonical_meta = copy.deepcopy(meta)

        parsed = {}
        errors = OrderedDict()
        def error(problem, k, supplied=None):
            errors[k] = OrderedDict([('error', problem)])
            if supplied is not None:
                errors[k]['supplied'] = unparse_literal(supplied)
            if k in self._info:
                errors[k]['canonical'] = self._info[k]['default']

        def check_supplied(): # pylint: disable=R0912
            def try_to_reify(v, parse):
                try:
                    return parse(v)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as ex:
                    # pylint: disable=W0631
                    log.info('Meta conversion error on %s, %s', k, ex)
                    error('Not a valid %s format (expected %s)' % (
                        right_type, TYPE_EXAMPLES[right_type]),
                          k,
                          supplied=meta[k])

            for k in meta:
                canonical_meta[k] = meta[k] # default
                if k not in self._info:
                    maybe_meants = spellsuggest.spell_suggest(
                        k, self._info.keys())
                    suggestion = (" (did you mean '%s'?)" % maybe_meants[0]
                                  if maybe_meants else '')
                    if k not in ('title', 'subtitle'):
                        error("Unexpected field '%s'%s" % (k, suggestion),
                              k, meta[k])
                    else:
                        error("This document type does not have a %s" % k,
                              k, meta[k])
                    continue
                potential_types = PY_TYPE_TO_TYPESETR_TYPES[type(meta[k])]
                right_type = self._info[k]['type']
                if right_type in potential_types:
                    if right_type == 'bibliography':
                        parsed[k] = try_to_reify(meta[k], Bibliography)

                else:
                    if 'rich-text' in potential_types:
                        if not isinstance(meta[k], basestring):
                            meta[k] = postprocess.plaintextify(meta[k])
                        potential_types = ('text',)
                    if potential_types == ('text',):
                        parsed[k] = try_to_reify(
                            meta[k],
                            # pylint: disable=W0640
                            lambda v: parse_literal(v, right_type))
                    else:
                        error("Expected meta field '%s:' to be"
                              " of type '%s', not '%s'" % (
                                  k, right_type, potential_types[0]),
                              k, supplied=meta[k])

        def check_required():
            for k in self._required:
                if k == 'title':
                    continue
                    # see __init__ comment
                ## assert 'default' not in self._info[k], \
                ##        "metadata.yml error -- %s has a required default" % k
                if k not in meta:
                    right_type = self._info[k]['type']
                    if right_type == 'text':
                        error('This field is required', '', k)
                    else:
                        error('This field (of type %s)'
                              ' is required' % right_type, k)

        check_supplied()
        check_required()
        meta_ans = OrderedDict()
        for k in meta.keys() + [k for k in self._info.keys() if k not in meta]:
            if k not in errors:
                meta_ans[k] = OrderedDict()
                if k in meta:
                    meta_ans[k]['supplied'] = unparse_literal(meta[k])
                # the canonical form is a string representation (for now) but
                # we don't just want to use the string that was supplied (e.g.
                # 'YES'), we want to canonicalize it. We achieve that by
                # unparsing the parsed version if any; unparsing a string is
                # idempotent hence values that are already strings are left as
                # is
                canonical = unparse_literal(
                    parsed.get(k, meta.get(k, self._defaults[k])))
                if canonical != meta_ans[k].get('supplied'):
                    meta_ans[k]['canonical'] = canonical
            else:
                meta_ans[k] = errors[k]
            if (self._info.get(k, {}).get('label', self.default_label(k)) !=
                self.default_label(k)): # pylint: disable=C0330
                meta_ans[k]['label'] = self._info[k]['label']
            if k in self._info and self._info[k]['type'] != 'text':
                meta_ans[k]['type'] = self._info[k]['type']
        return MetaInfo(meta_ans)
