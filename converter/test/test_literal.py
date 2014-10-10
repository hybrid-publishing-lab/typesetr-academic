#-*- file-encoding: utf-8 -*-
import datetime

from converter.literal import * # pylint: disable=W0614,W0401

def test_time_rex():
    assert TIME_REX.match('13:00Z').groups() == ('13', '00', None, 'Z', None)
    assert TIME_REX.match('13:00Z').groupdict()
    # Out[26]: {'hours': '13', 'mins': '00', 'sec': None, 'tz': 'Z'}
    assert TIME_REX.match('13:00').groups() == ('13', '00', None, None, None)

def test_date():
    assert Date('2003').to_string() == '2003'
    assert Date('2003-12-1').to_string() == '2003-12-01'
    assert Date('today').to_string() == 'today'
    assert Date('today').to_value() == datetime.date.today().isoformat()
