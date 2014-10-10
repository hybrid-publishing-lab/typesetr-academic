import hashlib

def hexdigest(data):
    return hashlib.sha512(data).hexdigest()[:32] # pylint: disable=E1101

def doc_digest(meta, parsed_body, transclusions):
    # FIXME(alexander): figure out a more stable way of doing this...
    # ... although stability is probably not that essential
    body_digest = hexdigest(repr(parsed_body))
    return hexdigest(meta.hexdigest() + body_digest + transclusions.hexdigest())
