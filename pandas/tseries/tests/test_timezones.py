# pylint: disable-msg=E1101,W0612
from __future__ import with_statement # for Python 2.5
from datetime import datetime, time, timedelta
import sys
import os
import unittest

import nose

import numpy as np

from pandas import (Index, Series, TimeSeries, DataFrame, isnull,
                    date_range, Timestamp)

from pandas import DatetimeIndex, Int64Index, to_datetime

from pandas.core.daterange import DateRange
import pandas.core.datetools as datetools
import pandas.tseries.offsets as offsets
from pandas.tseries.index import bdate_range, date_range
import pandas.tseries.tools as tools

from pandas.util.testing import assert_series_equal, assert_almost_equal
import pandas.util.testing as tm

import pandas._tseries as lib
import cPickle as pickle
import pandas.core.datetools as dt
from numpy.random import rand
from pandas.util.testing import assert_frame_equal
import pandas.util.py3compat as py3compat
from pandas.core.datetools import BDay
import pandas.core.common as com

NaT = lib.NaT


def _skip_if_no_pytz():
    try:
        import pytz
    except ImportError:
        raise nose.SkipTest

try:
    import pytz
except ImportError:
    pass


class TestTimeZoneSupport(unittest.TestCase):

    def setUp(self):
        _skip_if_no_pytz()

    def test_utc_to_local_no_modify(self):
        rng = date_range('3/11/2012', '3/12/2012', freq='H', tz='utc')
        rng_eastern = rng.tz_convert('US/Eastern')

        # Values are unmodified
        self.assert_(np.array_equal(rng.asi8, rng_eastern.asi8))

        self.assert_(rng_eastern.tz == pytz.timezone('US/Eastern'))

    def test_localize_utc_conversion(self):
        # Localizing to time zone should:
        #  1) check for DST ambiguities
        #  2) convert to UTC

        rng = date_range('3/10/2012', '3/11/2012', freq='30T')

        converted = rng.tz_localize('US/Eastern')
        expected_naive = rng + offsets.Hour(5)
        self.assert_(np.array_equal(converted.asi8, expected_naive.asi8))

        # DST ambiguity, this should fail
        rng = date_range('3/11/2012', '3/12/2012', freq='30T')
        self.assertRaises(Exception, rng.tz_localize, 'US/Eastern')

    def test_tz_localize_dti(self):
        from pandas.tseries.offsets import Hour

        dti = DatetimeIndex(start='1/1/2005', end='1/1/2005 0:00:30.256',
                            freq='L')
        dti2 = dti.tz_localize('US/Eastern')

        dti_utc = DatetimeIndex(start='1/1/2005 05:00',
                                end='1/1/2005 5:00:30.256', freq='L',
                                tz='utc')

        self.assert_(np.array_equal(dti2.values, dti_utc.values))

        dti3 = dti2.tz_convert('US/Pacific')
        self.assert_(np.array_equal(dti3.values, dti_utc.values))

        dti = DatetimeIndex(start='11/6/2011 1:59',
                            end='11/6/2011 2:00', freq='L')
        self.assertRaises(pytz.AmbiguousTimeError, dti.tz_localize,
                          'US/Eastern')

        dti = DatetimeIndex(start='3/13/2011 1:59', end='3/13/2011 2:00',
                            freq='L')
        self.assertRaises(pytz.AmbiguousTimeError, dti.tz_localize,
                          'US/Eastern')

    def test_utc_box_timestamp_and_localize(self):
        rng = date_range('3/11/2012', '3/12/2012', freq='H', tz='utc')
        rng_eastern = rng.tz_convert('US/Eastern')

        tz = pytz.timezone('US/Eastern')
        expected = tz.normalize(rng[-1])

        stamp = rng_eastern[-1]
        self.assertEquals(stamp, expected)
        self.assertEquals(stamp.tzinfo, expected.tzinfo)

    def test_timestamp_tz_convert(self):
        pass

    def test_pass_dates_convert_to_utc(self):
        pass

    def test_field_access_localize(self):
        pass

    def test_with_tz(self):
        tz = pytz.timezone('US/Central')

        # just want it to work
        start = datetime(2011, 3, 12, tzinfo=pytz.utc)
        dr = bdate_range(start, periods=50, freq=datetools.Hour())
        self.assert_(dr.tz is pytz.utc)

        # DateRange with naive datetimes
        dr = bdate_range('1/1/2005', '1/1/2009', tz=pytz.utc)
        dr = bdate_range('1/1/2005', '1/1/2009', tz=tz)

        # normalized
        central = dr.tz_convert(tz)
        self.assert_(central.tz is tz)
        self.assert_(central[0].tz is tz)

        # datetimes with tzinfo set
        dr = bdate_range(datetime(2005, 1, 1, tzinfo=pytz.utc),
                         '1/1/2009', tz=pytz.utc)

        self.assertRaises(Exception, bdate_range,
                          datetime(2005, 1, 1, tzinfo=pytz.utc),
                          '1/1/2009', tz=tz)

    def test_tz_localize(self):
        dr = bdate_range('1/1/2009', '1/1/2010')
        dr_utc = bdate_range('1/1/2009', '1/1/2010', tz=pytz.utc)
        localized = dr.tz_localize(pytz.utc)
        self.assert_(np.array_equal(dr_utc, localized))

    def test_with_tz_ambiguous_times(self):
        tz = pytz.timezone('US/Eastern')

        rng = bdate_range(datetime(2009, 1, 1), datetime(2010, 1, 1))

        # regular no problem
        self.assert_(rng.tz_validate())

        # March 13, 2011, spring forward, skip from 2 AM to 3 AM
        dr = date_range(datetime(2011, 3, 13, 1, 30), periods=3,
                        freq=datetools.Hour())
        self.assertRaises(pytz.AmbiguousTimeError, dr.tz_localize, tz)

        # after dst transition, it works
        dr = date_range(datetime(2011, 3, 13, 3, 30), periods=3,
                        freq=datetools.Hour(), tz=tz)

        # November 6, 2011, fall back, repeat 2 AM hour
        dr = date_range(datetime(2011, 11, 6, 1, 30), periods=3,
                        freq=datetools.Hour())
        self.assertRaises(pytz.AmbiguousTimeError, dr.tz_localize, tz)

        # UTC is OK
        dr = date_range(datetime(2011, 3, 13), periods=48,
                        freq=datetools.Minute(30), tz=pytz.utc)

    # test utility methods
    def test_infer_tz(self):
        eastern = pytz.timezone('US/Eastern')
        utc = pytz.utc

        _start = datetime(2001, 1, 1)
        _end = datetime(2009, 1, 1)

        start = eastern.localize(_start)
        end = eastern.localize(_end)
        assert(tools._infer_tzinfo(start, end) is eastern)
        assert(tools._infer_tzinfo(start, None) is eastern)
        assert(tools._infer_tzinfo(None, end) is eastern)

        start = utc.localize(_start)
        end = utc.localize(_end)
        assert(tools._infer_tzinfo(start, end) is utc)

        end = eastern.localize(_end)
        self.assertRaises(Exception, tools._infer_tzinfo, start, end)
        self.assertRaises(Exception, tools._infer_tzinfo, end, start)

    def test_asobject_tz_box(self):
        tz = pytz.timezone('US/Eastern')
        index = DatetimeIndex(start='1/1/2005', periods=10, tz=tz,
                              freq='B')

        result = index.asobject
        self.assert_(result[0].tz is tz)

    def test_tz_string(self):
        result = date_range('1/1/2000', periods=10, tz='US/Eastern')
        expected = date_range('1/1/2000', periods=10,
                              tz=pytz.timezone('US/Eastern'))

        self.assert_(result.equals(expected))

    def test_take_dont_lose_meta(self):
        _skip_if_no_pytz()
        rng = date_range('1/1/2000', periods=20, tz='US/Eastern')

        result = rng.take(range(5))
        self.assert_(result.tz == rng.tz)
        self.assert_(result.freq == rng.freq)


class TestTimeZones(unittest.TestCase):

    def setUp(self):
        _skip_if_no_pytz()

    def test_index_equals_with_tz(self):
        left = date_range('1/1/2011', periods=100, freq='H', tz='utc')
        right = date_range('1/1/2011', periods=100, freq='H',
                           tz='US/Eastern')

        self.assert_(not left.equals(right))

    def test_tz_convert_naive(self):
        rng = date_range('1/1/2011', periods=100, freq='H')

        conv = rng.tz_convert('US/Pacific')
        exp = rng.tz_localize('US/Pacific')
        self.assert_(conv.equals(exp))

    def test_tz_convert(self):
        rng = date_range('1/1/2011', periods=100, freq='H')
        ts = Series(1, index=rng)

        result = ts.tz_convert('utc')
        self.assert_(result.index.tz.zone == 'UTC')

    def test_join_utc_convert(self):
        rng = date_range('1/1/2011', periods=100, freq='H', tz='utc')

        left = rng.tz_convert('US/Eastern')
        right = rng.tz_convert('Europe/Berlin')

        for how in ['inner', 'outer', 'left', 'right']:
            result = left.join(left[:-5], how=how)
            self.assert_(isinstance(result, DatetimeIndex))
            self.assert_(result.tz == left.tz)

            result = left.join(right[:-5], how=how)
            self.assert_(isinstance(result, DatetimeIndex))
            self.assert_(result.tz.zone == 'UTC')

    def test_arith_utc_convert(self):
        rng = date_range('1/1/2011', periods=100, freq='H', tz='utc')

        perm = np.random.permutation(100)[:90]
        ts1 = Series(np.random.randn(90),
                     index=rng.take(perm).tz_convert('US/Eastern'))

        perm = np.random.permutation(100)[:90]
        ts2 = Series(np.random.randn(90),
                     index=rng.take(perm).tz_convert('Europe/Berlin'))

        result = ts1 + ts2

        uts1 = ts1.tz_convert('utc')
        uts2 = ts2.tz_convert('utc')
        expected = uts1 + uts2

        self.assert_(result.index.tz == pytz.UTC)
        assert_series_equal(result, expected)

    def test_intersection(self):
        rng = date_range('1/1/2011', periods=100, freq='H', tz='utc')

        left = rng[10:90][::-1]
        right = rng[20:80][::-1]

        self.assert_(left.tz == rng.tz)
        result = left.intersection(right)
        self.assert_(result.tz == left.tz)


if __name__ == '__main__':
    nose.runmodule(argv=[__file__,'-vvs','-x','--pdb', '--pdb-failure'],
                   exit=False)
