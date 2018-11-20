# -*- coding: utf-8 -*-
from datetime import date, datetime

from dateutil.tz.tz import tzoffset
import numpy as np
import pytest
import pytz

from pandas._libs import iNaT, tslib
from pandas.compat.numpy import np_array_datetime64_compat

import pandas.util.testing as tm


class TestParseISO8601(object):
    @pytest.mark.parametrize('date_str, exp', [
        ('2011-01-02', datetime(2011, 1, 2)),
        ('2011-1-2', datetime(2011, 1, 2)),
        ('2011-01', datetime(2011, 1, 1)),
        ('2011-1', datetime(2011, 1, 1)),
        ('2011 01 02', datetime(2011, 1, 2)),
        ('2011.01.02', datetime(2011, 1, 2)),
        ('2011/01/02', datetime(2011, 1, 2)),
        ('2011\\01\\02', datetime(2011, 1, 2)),
        ('2013-01-01 05:30:00', datetime(2013, 1, 1, 5, 30)),
        ('2013-1-1 5:30:00', datetime(2013, 1, 1, 5, 30))])
    def test_parsers_iso8601(self, date_str, exp):
        # GH#12060
        # test only the iso parser - flexibility to different
        # separators and leadings 0s
        # Timestamp construction falls back to dateutil
        actual = tslib._test_parse_iso8601(date_str)
        assert actual == exp

    @pytest.mark.parametrize(
        'date_str',
        ['2011-01/02', '2011^11^11',
         '201401', '201111', '200101',
         # mixed separated and unseparated
         '2005-0101', '200501-01',
         '20010101 12:3456',
         '20010101 1234:56',
         # HHMMSS must have two digits in
         # each component if unseparated
         '20010101 1', '20010101 123',
         '20010101 12345', '20010101 12345Z',
         # wrong separator for HHMMSS
         '2001-01-01 12-34-56'])
    def test_parsers_iso8601_invalid(self, date_str):
        # separators must all match - YYYYMM not valid
        with pytest.raises(ValueError):
            tslib._test_parse_iso8601(date_str)


class TestArrayToDatetime(object):
    def test_parsing_valid_dates(self):
        arr = np.array(['01-01-2013', '01-02-2013'], dtype=object)
        result, _ = tslib.array_to_datetime(arr)
        expected = ['2013-01-01T00:00:00.000000000-0000',
                    '2013-01-02T00:00:00.000000000-0000']
        tm.assert_numpy_array_equal(
            result,
            np_array_datetime64_compat(expected, dtype='M8[ns]'))

        arr = np.array(['Mon Sep 16 2013', 'Tue Sep 17 2013'], dtype=object)
        result, _ = tslib.array_to_datetime(arr)
        expected = ['2013-09-16T00:00:00.000000000-0000',
                    '2013-09-17T00:00:00.000000000-0000']
        tm.assert_numpy_array_equal(
            result,
            np_array_datetime64_compat(expected, dtype='M8[ns]'))

    @pytest.mark.parametrize('dt_string, expected_tz', [
        ['01-01-2013 08:00:00+08:00', pytz.FixedOffset(480)],
        ['2013-01-01T08:00:00.000000000+0800', pytz.FixedOffset(480)],
        ['2012-12-31T16:00:00.000000000-0800', pytz.FixedOffset(-480)],
        ['12-31-2012 23:00:00-01:00', pytz.FixedOffset(-60)]])
    def test_parsing_timezone_offsets(self, dt_string, expected_tz):
        # All of these datetime strings with offsets are equivalent
        # to the same datetime after the timezone offset is added
        arr = np.array(['01-01-2013 00:00:00'], dtype=object)
        expected, _ = tslib.array_to_datetime(arr)

        arr = np.array([dt_string], dtype=object)
        result, result_tz = tslib.array_to_datetime(arr)
        tm.assert_numpy_array_equal(result, expected)
        assert result_tz is expected_tz

    def test_parsing_non_iso_timezone_offset(self):
        dt_string = '01-01-2013T00:00:00.000000000+0000'
        arr = np.array([dt_string], dtype=object)
        result, result_tz = tslib.array_to_datetime(arr)
        expected = np.array([np.datetime64('2013-01-01 00:00:00.000000000')])
        tm.assert_numpy_array_equal(result, expected)
        assert result_tz is pytz.FixedOffset(0)

    def test_parsing_different_timezone_offsets(self):
        # GH 17697
        data = ["2015-11-18 15:30:00+05:30", "2015-11-18 15:30:00+06:30"]
        data = np.array(data, dtype=object)
        result, result_tz = tslib.array_to_datetime(data)
        expected = np.array([datetime(2015, 11, 18, 15, 30,
                                      tzinfo=tzoffset(None, 19800)),
                             datetime(2015, 11, 18, 15, 30,
                                      tzinfo=tzoffset(None, 23400))],
                            dtype=object)
        tm.assert_numpy_array_equal(result, expected)
        assert result_tz is None

    def test_number_looking_strings_not_into_datetime(self):
        # GH#4601
        # These strings don't look like datetimes so they shouldn't be
        # attempted to be converted
        arr = np.array(['-352.737091', '183.575577'], dtype=object)
        result, _ = tslib.array_to_datetime(arr, errors='ignore')
        tm.assert_numpy_array_equal(result, arr)

        arr = np.array(['1', '2', '3', '4', '5'], dtype=object)
        result, _ = tslib.array_to_datetime(arr, errors='ignore')
        tm.assert_numpy_array_equal(result, arr)

    @pytest.mark.parametrize('invalid_date', [
        date(1000, 1, 1),
        datetime(1000, 1, 1),
        '1000-01-01',
        'Jan 1, 1000',
        np.datetime64('1000-01-01')])
    def test_coerce_outside_ns_bounds(self, invalid_date):
        arr = np.array([invalid_date], dtype='object')
        with pytest.raises(ValueError):
            tslib.array_to_datetime(arr, errors='raise')

        result, _ = tslib.array_to_datetime(arr, errors='coerce')
        expected = np.array([iNaT], dtype='M8[ns]')
        tm.assert_numpy_array_equal(result, expected)

    def test_coerce_outside_ns_bounds_one_valid(self):
        arr = np.array(['1/1/1000', '1/1/2000'], dtype=object)
        result, _ = tslib.array_to_datetime(arr, errors='coerce')
        expected = [iNaT,
                    '2000-01-01T00:00:00.000000000-0000']
        tm.assert_numpy_array_equal(
            result,
            np_array_datetime64_compat(expected, dtype='M8[ns]'))

    def test_coerce_of_invalid_datetimes(self):
        arr = np.array(['01-01-2013', 'not_a_date', '1'], dtype=object)

        # Without coercing, the presence of any invalid dates prevents
        # any values from being converted
        result, _ = tslib.array_to_datetime(arr, errors='ignore')
        tm.assert_numpy_array_equal(result, arr)

        # With coercing, the invalid dates becomes iNaT
        result, _ = tslib.array_to_datetime(arr, errors='coerce')
        expected = ['2013-01-01T00:00:00.000000000-0000',
                    iNaT,
                    iNaT]

        tm.assert_numpy_array_equal(
            result,
            np_array_datetime64_compat(expected, dtype='M8[ns]'))

    def test_to_datetime_barely_out_of_bounds(self):
        # GH#19529
        # GH#19382 close enough to bounds that dropping nanos would result
        # in an in-bounds datetime
        arr = np.array(['2262-04-11 23:47:16.854775808'], dtype=object)
        with pytest.raises(tslib.OutOfBoundsDatetime):
            tslib.array_to_datetime(arr)
