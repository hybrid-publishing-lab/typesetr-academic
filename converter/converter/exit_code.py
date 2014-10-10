#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
""" This module defines exit codes and a globally shared exit_code variable.

The DATA_ERRORs (which have the high bit set) are sum types (i.e. `|`-together
bits) the non-data errors (i.e. bugs) are exclusive.

ERROR_INFO =
  | BUG of INTERNAL_ERROR | USAGE_ERROR
  | DATA_ERROR of (META_ERROR(y/n), BODY_ERROR(y/n), MISSING_INCLUDES(y/n))

"""
import logging as log
import sys

DATA_ERROR_EXIT = 2**7
META_ERROR_EXIT, BODY_ERROR_EXIT, MISSING_INCLUDES_EXIT = (
    2**i | DATA_ERROR_EXIT for i in range(1, 4))
INTERNAL_ERROR_EXIT, USAGE_ERROR_EXIT = range(1, 3)

# mutated from outside
final_exit_code=0 # pylint: disable=C0322,C0103

def exit(): # pylint: disable=W0622
    if final_exit_code:
        if final_exit_code & DATA_ERROR_EXIT:
            code = final_exit_code & ~DATA_ERROR_EXIT
            errs = [err
                    for err in ['META_ERROR', 'BODY_ERROR', 'MISSING_INCLUDES']
                    if code & globals()[err + '_EXIT']]
            log.error('About to exit; the following data errors occured:%s',
                      errs)
    sys.exit(final_exit_code)
