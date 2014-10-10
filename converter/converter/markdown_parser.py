#-*- file-encoding: utf-8 -*-
from cStringIO import StringIO
import regex as re

import misaka

from converter import orderedyaml as yaml # pylint: disable=E0611

def to_html(infilename):
    html_file = StringIO()
    with open(infilename, 'rb') as f:
        s = f.read()
    if s.startswith('---\n'):
        headyaml, body = re.split('(?m)^[.-]{3}$', s, 2)[1:]
        update_meta = yaml.load(headyaml)
    else:
        body = s
        update_meta = None
    html_file.write(misaka.html(body)) # pylint: disable=E1101
    html_file.seek(0)
    return update_meta, html_file
