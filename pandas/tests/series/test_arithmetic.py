# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import operator

import numpy as np
import pytest

from pandas import Series, Timestamp, Period
from pandas._libs.tslibs.period import IncompatibleFrequency

import pandas as pd
import pandas.util.testing as tm


# ------------------------------------------------------------------
# Comparisons

class TestSeriesComparison(object):
    def test_compare_invalid(self):
        # GH#8058
        # ops testing
        a = pd.Series(np.random.randn(5), name=0)
        b = pd.Series(np.random.randn(5))
        b.name = pd.Timestamp('2000-01-01')
        tm.assert_series_equal(a / b, 1 / (b / a))

    @pytest.mark.parametrize('opname', ['eq', 'ne', 'gt', 'lt', 'ge', 'le'])
    def test_ser_flex_cmp_return_dtypes(self, opname):
        # GH#15115
        ser = Series([1, 3, 2], index=range(3))
        const = 2

        result = getattr(ser, opname)(const).get_dtype_counts()
        tm.assert_series_equal(result, Series([1], ['bool']))

    @pytest.mark.parametrize('opname', ['eq', 'ne', 'gt', 'lt', 'ge', 'le'])
    def test_ser_flex_cmp_return_dtypes_empty(self, opname):
        # GH#15115 empty Series case
        ser = Series([1, 3, 2], index=range(3))
        empty = ser.iloc[:0]
        const = 2

        result = getattr(empty, opname)(const).get_dtype_counts()
        tm.assert_series_equal(result, Series([1], ['bool']))

    @pytest.mark.parametrize('op', [operator.eq, operator.ne,
                                    operator.le, operator.lt,
                                    operator.ge, operator.gt])
    @pytest.mark.parametrize('names', [(None, None, None),
                                       ('foo', 'bar', None),
                                       ('baz', 'baz', 'baz')])
    def test_ser_cmp_result_names(self, names, op):
        # datetime64 dtype
        dti = pd.date_range('1949-06-07 03:00:00',
                            freq='H', periods=5, name=names[0])
        ser = Series(dti).rename(names[1])
        result = op(ser, dti)
        assert result.name == names[2]

        # datetime64tz dtype
        dti = dti.tz_localize('US/Central')
        ser = Series(dti).rename(names[1])
        result = op(ser, dti)
        assert result.name == names[2]

        # timedelta64 dtype
        tdi = dti - dti.shift(1)
        ser = Series(tdi).rename(names[1])
        result = op(ser, tdi)
        assert result.name == names[2]

        # categorical
        if op in [operator.eq, operator.ne]:
            # categorical dtype comparisons raise for inequalities
            cidx = tdi.astype('category')
            ser = Series(cidx).rename(names[1])
            result = op(ser, cidx)
            assert result.name == names[2]


class TestTimestampSeriesComparison(object):
    def test_dt64ser_cmp_period_scalar(self):
        ser = Series(pd.period_range('2000-01-01', periods=10, freq='D'))
        val = Period('2000-01-04', freq='D')
        result = ser > val
        expected = Series([x > val for x in ser])
        tm.assert_series_equal(result, expected)

        val = ser[5]
        result = ser > val
        expected = Series([x > val for x in ser])
        tm.assert_series_equal(result, expected)

    def test_timestamp_compare_series(self):
        # make sure we can compare Timestamps on the right AND left hand side
        # GH#4982
        ser = pd.Series(pd.date_range('20010101', periods=10), name='dates')
        s_nat = ser.copy(deep=True)

        ser[0] = pd.Timestamp('nat')
        ser[3] = pd.Timestamp('nat')

        ops = {'lt': 'gt', 'le': 'ge', 'eq': 'eq', 'ne': 'ne'}

        for left, right in ops.items():
            left_f = getattr(operator, left)
            right_f = getattr(operator, right)

            # no nats
            expected = left_f(ser, pd.Timestamp('20010109'))
            result = right_f(pd.Timestamp('20010109'), ser)
            tm.assert_series_equal(result, expected)

            # nats
            expected = left_f(ser, pd.Timestamp('nat'))
            result = right_f(pd.Timestamp('nat'), ser)
            tm.assert_series_equal(result, expected)

            # compare to timestamp with series containing nats
            expected = left_f(s_nat, pd.Timestamp('20010109'))
            result = right_f(pd.Timestamp('20010109'), s_nat)
            tm.assert_series_equal(result, expected)

            # compare to nat with series containing nats
            expected = left_f(s_nat, pd.Timestamp('nat'))
            result = right_f(pd.Timestamp('nat'), s_nat)
            tm.assert_series_equal(result, expected)

    def test_timestamp_equality(self):
        # GH#11034
        ser = pd.Series([pd.Timestamp('2000-01-29 01:59:00'), 'NaT'])
        result = ser != ser
        tm.assert_series_equal(result, pd.Series([False, True]))
        result = ser != ser[0]
        tm.assert_series_equal(result, pd.Series([False, True]))
        result = ser != ser[1]
        tm.assert_series_equal(result, pd.Series([True, True]))

        result = ser == ser
        tm.assert_series_equal(result, pd.Series([True, False]))
        result = ser == ser[0]
        tm.assert_series_equal(result, pd.Series([True, False]))
        result = ser == ser[1]
        tm.assert_series_equal(result, pd.Series([False, False]))


class TestTimedeltaSeriesComparisons(object):
    def test_compare_timedelta_series(self):
        # regresssion test for GH5963
        s = pd.Series([timedelta(days=1), timedelta(days=2)])
        actual = s > timedelta(days=1)
        expected = pd.Series([False, True])
        tm.assert_series_equal(actual, expected)


class TestPeriodSeriesComparisons(object):
    @pytest.mark.parametrize('freq', ['M', '2M', '3M'])
    def test_cmp_series_period_scalar(self, freq):
        # GH 13200
        base = Series([Period(x, freq=freq) for x in
                       ['2011-01', '2011-02', '2011-03', '2011-04']])
        p = Period('2011-02', freq=freq)

        exp = Series([False, True, False, False])
        tm.assert_series_equal(base == p, exp)
        tm.assert_series_equal(p == base, exp)

        exp = Series([True, False, True, True])
        tm.assert_series_equal(base != p, exp)
        tm.assert_series_equal(p != base, exp)

        exp = Series([False, False, True, True])
        tm.assert_series_equal(base > p, exp)
        tm.assert_series_equal(p < base, exp)

        exp = Series([True, False, False, False])
        tm.assert_series_equal(base < p, exp)
        tm.assert_series_equal(p > base, exp)

        exp = Series([False, True, True, True])
        tm.assert_series_equal(base >= p, exp)
        tm.assert_series_equal(p <= base, exp)

        exp = Series([True, True, False, False])
        tm.assert_series_equal(base <= p, exp)
        tm.assert_series_equal(p >= base, exp)

        # different base freq
        msg = "Input has different freq=A-DEC from Period"
        with tm.assert_raises_regex(IncompatibleFrequency, msg):
            base <= Period('2011', freq='A')

        with tm.assert_raises_regex(IncompatibleFrequency, msg):
            Period('2011', freq='A') >= base

    @pytest.mark.parametrize('freq', ['M', '2M', '3M'])
    def test_cmp_series_period_series(self, freq):
        # GH#13200
        base = Series([Period(x, freq=freq) for x in
                       ['2011-01', '2011-02', '2011-03', '2011-04']])

        ser = Series([Period(x, freq=freq) for x in
                      ['2011-02', '2011-01', '2011-03', '2011-05']])

        exp = Series([False, False, True, False])
        tm.assert_series_equal(base == ser, exp)

        exp = Series([True, True, False, True])
        tm.assert_series_equal(base != ser, exp)

        exp = Series([False, True, False, False])
        tm.assert_series_equal(base > ser, exp)

        exp = Series([True, False, False, True])
        tm.assert_series_equal(base < ser, exp)

        exp = Series([False, True, True, False])
        tm.assert_series_equal(base >= ser, exp)

        exp = Series([True, False, True, True])
        tm.assert_series_equal(base <= ser, exp)

        ser2 = Series([Period(x, freq='A') for x in
                       ['2011', '2011', '2011', '2011']])

        # different base freq
        msg = "Input has different freq=A-DEC from Period"
        with tm.assert_raises_regex(IncompatibleFrequency, msg):
            base <= ser2

    def test_cmp_series_period_series_mixed_freq(self):
        # GH#13200
        base = Series([Period('2011', freq='A'),
                       Period('2011-02', freq='M'),
                       Period('2013', freq='A'),
                       Period('2011-04', freq='M')])

        ser = Series([Period('2012', freq='A'),
                      Period('2011-01', freq='M'),
                      Period('2013', freq='A'),
                      Period('2011-05', freq='M')])

        exp = Series([False, False, True, False])
        tm.assert_series_equal(base == ser, exp)

        exp = Series([True, True, False, True])
        tm.assert_series_equal(base != ser, exp)

        exp = Series([False, True, False, False])
        tm.assert_series_equal(base > ser, exp)

        exp = Series([True, False, False, True])
        tm.assert_series_equal(base < ser, exp)

        exp = Series([False, True, True, False])
        tm.assert_series_equal(base >= ser, exp)

        exp = Series([True, False, True, True])
        tm.assert_series_equal(base <= ser, exp)


# ------------------------------------------------------------------
# Arithmetic

class TestSeriesArithmetic(object):
    # Standard, numeric, or otherwise not-Timestamp/Timedelta/Period dtypes
    @pytest.mark.parametrize('data', [
        [1, 2, 3],
        [1.1, 2.2, 3.3],
        [Timestamp('2011-01-01'), Timestamp('2011-01-02'), pd.NaT],
        ['x', 'y', 1]])
    @pytest.mark.parametrize('dtype', [None, object])
    def test_series_radd_str_invalid(self, dtype, data):
        ser = Series(data, dtype=dtype)
        with pytest.raises(TypeError):
            'foo_' + ser

    # TODO: parametrize, better name
    def test_object_ser_add_invalid(self):
        # invalid ops
        obj_ser = tm.makeObjectSeries()
        obj_ser.name = 'objects'
        with pytest.raises(Exception):
            obj_ser + 1
        with pytest.raises(Exception):
            obj_ser + np.array(1, dtype=np.int64)
        with pytest.raises(Exception):
            obj_ser - 1
        with pytest.raises(Exception):
            obj_ser - np.array(1, dtype=np.int64)

    @pytest.mark.parametrize('dtype', [None, object])
    def test_series_with_dtype_radd_nan(self, dtype):
        ser = pd.Series([1, 2, 3], dtype=dtype)
        expected = pd.Series([np.nan, np.nan, np.nan], dtype=dtype)

        result = np.nan + ser
        tm.assert_series_equal(result, expected)

        result = ser + np.nan
        tm.assert_series_equal(result, expected)

    @pytest.mark.parametrize('dtype', [None, object])
    def test_series_with_dtype_radd_int(self, dtype):
        ser = pd.Series([1, 2, 3], dtype=dtype)
        expected = pd.Series([2, 3, 4], dtype=dtype)

        result = 1 + ser
        tm.assert_series_equal(result, expected)

        result = ser + 1
        tm.assert_series_equal(result, expected)

    def test_series_radd_str(self):
        ser = pd.Series(['x', np.nan, 'x'])
        tm.assert_series_equal('a' + ser, pd.Series(['ax', np.nan, 'ax']))
        tm.assert_series_equal(ser + 'a', pd.Series(['xa', np.nan, 'xa']))


class TestPeriodSeriesArithmetic(object):
    def test_ops_series_timedelta(self):
        # GH 13043
        ser = pd.Series([pd.Period('2015-01-01', freq='D'),
                         pd.Period('2015-01-02', freq='D')], name='xxx')
        assert ser.dtype == object

        expected = pd.Series([pd.Period('2015-01-02', freq='D'),
                              pd.Period('2015-01-03', freq='D')], name='xxx')

        result = ser + pd.Timedelta('1 days')
        tm.assert_series_equal(result, expected)

        result = pd.Timedelta('1 days') + ser
        tm.assert_series_equal(result, expected)

        result = ser + pd.tseries.offsets.Day()
        tm.assert_series_equal(result, expected)

        result = pd.tseries.offsets.Day() + ser
        tm.assert_series_equal(result, expected)

    def test_ops_series_period(self):
        # GH 13043
        ser = pd.Series([pd.Period('2015-01-01', freq='D'),
                         pd.Period('2015-01-02', freq='D')], name='xxx')
        assert ser.dtype == object

        per = pd.Period('2015-01-10', freq='D')
        # dtype will be object because of original dtype
        expected = pd.Series([9, 8], name='xxx', dtype=object)
        tm.assert_series_equal(per - ser, expected)
        tm.assert_series_equal(ser - per, -1 * expected)

        s2 = pd.Series([pd.Period('2015-01-05', freq='D'),
                        pd.Period('2015-01-04', freq='D')], name='xxx')
        assert s2.dtype == object

        expected = pd.Series([4, 2], name='xxx', dtype=object)
        tm.assert_series_equal(s2 - ser, expected)
        tm.assert_series_equal(ser - s2, -1 * expected)


class TestTimestampSeriesArithmetic(object):
    def test_timestamp_sub_series(self):
        ser = pd.Series(pd.date_range('2014-03-17', periods=2, freq='D',
                                      tz='US/Eastern'))
        ts = ser[0]

        delta_series = pd.Series([np.timedelta64(0, 'D'),
                                  np.timedelta64(1, 'D')])
        tm.assert_series_equal(ser - ts, delta_series)
        tm.assert_series_equal(ts - ser, -delta_series)

    def test_dt64ser_sub_datetime_dtype(self):
        ts = Timestamp(datetime(1993, 1, 7, 13, 30, 00))
        dt = datetime(1993, 6, 22, 13, 30)
        ser = Series([ts])
        result = pd.to_timedelta(np.abs(ser - dt))
        assert result.dtype == 'timedelta64[ns]'
