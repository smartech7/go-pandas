from datetime import datetime, time, timedelta, date
import sys
import os

import nose

import numpy as np
from numpy.testing import assert_almost_equal as np_assert_almost_equal
from pandas import Timestamp
from pandas.compat import u
import pandas.util.testing as tm
from pandas.tseries.offsets import Second, Milli, Micro

try:
    import pandas.tseries.converter as converter
except ImportError:
    raise nose.SkipTest("no pandas.tseries.converter, skipping")


def test_timtetonum_accepts_unicode():
    assert(converter.time2num("00:01") == converter.time2num(u("00:01")))


class TestDateTimeConverter(tm.TestCase):

    def setUp(self):
        self.dtc = converter.DatetimeConverter()
        self.tc = converter.TimeFormatter(None)

    def test_convert_accepts_unicode(self):
        r1 = self.dtc.convert("12:22", None, None)
        r2 = self.dtc.convert(u("12:22"), None, None)
        assert(r1 == r2), "DatetimeConverter.convert should accept unicode"

    def test_conversion(self):
        rs = self.dtc.convert(['2012-1-1'], None, None)[0]
        xp = datetime(2012, 1, 1).toordinal()
        self.assertEqual(rs, xp)

        rs = self.dtc.convert('2012-1-1', None, None)
        self.assertEqual(rs, xp)

        rs = self.dtc.convert(date(2012, 1, 1), None, None)
        self.assertEqual(rs, xp)

        rs = self.dtc.convert(datetime(2012, 1, 1).toordinal(), None, None)
        self.assertEqual(rs, xp)

        rs = self.dtc.convert('2012-1-1', None, None)
        self.assertEqual(rs, xp)

        rs = self.dtc.convert(Timestamp('2012-1-1'), None, None)
        self.assertEqual(rs, xp)

    def test_conversion_float(self):
        decimals = 9

        rs = self.dtc.convert(Timestamp('2012-1-1 01:02:03', tz='UTC'), None, None)
        xp = converter.dates.date2num(Timestamp('2012-1-1 01:02:03', tz='UTC'))
        np_assert_almost_equal(rs, xp, decimals)

        rs = self.dtc.convert(Timestamp('2012-1-1 09:02:03', tz='Asia/Hong_Kong'), None, None)
        np_assert_almost_equal(rs, xp, decimals)

        rs = self.dtc.convert(datetime(2012, 1, 1, 1, 2, 3), None, None)
        np_assert_almost_equal(rs, xp, decimals)

    def test_time_formatter(self):
        self.tc(90000)

    def test_dateindex_conversion(self):
        decimals = 9

        for freq in ('B', 'L', 'S'):
            dateindex = tm.makeDateIndex(k = 10, freq = freq)
            rs = self.dtc.convert(dateindex, None, None)
            xp = converter.dates.date2num(dateindex)
            np_assert_almost_equal(rs, xp, decimals)

    def test_resolution(self):
        def _assert_less(ts1, ts2):
            val1 = self.dtc.convert(ts1, None, None)
            val2 = self.dtc.convert(ts2, None, None)
            if not val1 < val2:
                raise AssertionError('{0} is not less than {1}.'.format(val1, val2))

        # Matplotlib's time representation using floats cannot distinguish intervals smaller
        # than ~10 microsecond in the common range of years.
        ts = Timestamp('2012-1-1')
        _assert_less(ts, ts + Second())
        _assert_less(ts, ts + Milli())
        _assert_less(ts, ts + Micro(50))


if __name__ == '__main__':
    import nose
    nose.runmodule(argv=[__file__, '-vvs', '-x', '--pdb', '--pdb-failure'],
                   exit=False)
