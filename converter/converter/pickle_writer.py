# -*- encoding: utf-8 -*-
"""Internal state to a pickle writer – intended for debugging and development.
"""
from collections import namedtuple
import cPickle as pickle


InternalState = namedtuple('InternalState', [ # pylint: disable=C0103
    'meta', 'parsed_body', 'transclusions', 'style_template'])

def write(out_file, style_template, bib, # pylint: disable=R0913,W0613
          meta, parsed_body, transclusions):
    pickle.dump(InternalState(
        style_template=style_template,
        meta=meta,
        parsed_body=parsed_body,
        transclusions=transclusions),
                out_file,
                protocol=2)
