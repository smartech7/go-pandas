# -*- coding: utf-8 -*-

from datetime import datetime, timedelta, date, time

import numpy as np
import pandas as pd
import pandas.lib as lib
import pandas.util.testing as tm
from pandas import Index

from pandas.compat import long, u, PY2


class TestInference(tm.TestCase):

    def test_infer_dtype_bytes(self):
        compare = 'string' if PY2 else 'bytes'

        # string array of bytes
        arr = np.array(list('abc'), dtype='S1')
        self.assertEqual(pd.lib.infer_dtype(arr), compare)

        # object array of bytes
        arr = arr.astype(object)
        self.assertEqual(pd.lib.infer_dtype(arr), compare)

    def test_isinf_scalar(self):
        # GH 11352
        self.assertTrue(lib.isposinf_scalar(float('inf')))
        self.assertTrue(lib.isposinf_scalar(np.inf))
        self.assertFalse(lib.isposinf_scalar(-np.inf))
        self.assertFalse(lib.isposinf_scalar(1))
        self.assertFalse(lib.isposinf_scalar('a'))

        self.assertTrue(lib.isneginf_scalar(float('-inf')))
        self.assertTrue(lib.isneginf_scalar(-np.inf))
        self.assertFalse(lib.isneginf_scalar(np.inf))
        self.assertFalse(lib.isneginf_scalar(1))
        self.assertFalse(lib.isneginf_scalar('a'))

    def test_maybe_convert_numeric_infinities(self):
        # see gh-13274
        infinities = ['inf', 'inF', 'iNf', 'Inf',
                      'iNF', 'InF', 'INf', 'INF']
        na_values = set(['', 'NULL', 'nan'])

        pos = np.array(['inf'], dtype=np.float64)
        neg = np.array(['-inf'], dtype=np.float64)

        msg = "Unable to parse string"

        for infinity in infinities:
            for maybe_int in (True, False):
                out = lib.maybe_convert_numeric(
                    np.array([infinity], dtype=object),
                    na_values, maybe_int)
                tm.assert_numpy_array_equal(out, pos)

                out = lib.maybe_convert_numeric(
                    np.array(['-' + infinity], dtype=object),
                    na_values, maybe_int)
                tm.assert_numpy_array_equal(out, neg)

                out = lib.maybe_convert_numeric(
                    np.array([u(infinity)], dtype=object),
                    na_values, maybe_int)
                tm.assert_numpy_array_equal(out, pos)

                out = lib.maybe_convert_numeric(
                    np.array(['+' + infinity], dtype=object),
                    na_values, maybe_int)
                tm.assert_numpy_array_equal(out, pos)

                # too many characters
                with tm.assertRaisesRegexp(ValueError, msg):
                    lib.maybe_convert_numeric(
                        np.array(['foo_' + infinity], dtype=object),
                        na_values, maybe_int)

    def test_maybe_convert_numeric_post_floatify_nan(self):
        # see gh-13314
        data = np.array(['1.200', '-999.000', '4.500'], dtype=object)
        expected = np.array([1.2, np.nan, 4.5], dtype=np.float64)
        nan_values = set([-999, -999.0])

        for coerce_type in (True, False):
            out = lib.maybe_convert_numeric(data, nan_values, coerce_type)
            tm.assert_numpy_array_equal(out, expected)

    def test_convert_infs(self):
        arr = np.array(['inf', 'inf', 'inf'], dtype='O')
        result = lib.maybe_convert_numeric(arr, set(), False)
        self.assertTrue(result.dtype == np.float64)

        arr = np.array(['-inf', '-inf', '-inf'], dtype='O')
        result = lib.maybe_convert_numeric(arr, set(), False)
        self.assertTrue(result.dtype == np.float64)

    def test_scientific_no_exponent(self):
        # See PR 12215
        arr = np.array(['42E', '2E', '99e', '6e'], dtype='O')
        result = lib.maybe_convert_numeric(arr, set(), False, True)
        self.assertTrue(np.all(np.isnan(result)))

    def test_convert_non_hashable(self):
        # GH13324
        # make sure that we are handing non-hashables
        arr = np.array([[10.0, 2], 1.0, 'apple'])
        result = lib.maybe_convert_numeric(arr, set(), False, True)
        tm.assert_numpy_array_equal(result, np.array([np.nan, 1.0, np.nan]))


class TestTypeInference(tm.TestCase):
    _multiprocess_can_split_ = True

    def test_length_zero(self):
        result = lib.infer_dtype(np.array([], dtype='i4'))
        self.assertEqual(result, 'integer')

        result = lib.infer_dtype([])
        self.assertEqual(result, 'empty')

    def test_integers(self):
        arr = np.array([1, 2, 3, np.int64(4), np.int32(5)], dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'integer')

        arr = np.array([1, 2, 3, np.int64(4), np.int32(5), 'foo'], dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'mixed-integer')

        arr = np.array([1, 2, 3, 4, 5], dtype='i4')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'integer')

    def test_bools(self):
        arr = np.array([True, False, True, True, True], dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'boolean')

        arr = np.array([np.bool_(True), np.bool_(False)], dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'boolean')

        arr = np.array([True, False, True, 'foo'], dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'mixed')

        arr = np.array([True, False, True], dtype=bool)
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'boolean')

    def test_floats(self):
        arr = np.array([1., 2., 3., np.float64(4), np.float32(5)], dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'floating')

        arr = np.array([1, 2, 3, np.float64(4), np.float32(5), 'foo'],
                       dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'mixed-integer')

        arr = np.array([1, 2, 3, 4, 5], dtype='f4')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'floating')

        arr = np.array([1, 2, 3, 4, 5], dtype='f8')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'floating')

    def test_string(self):
        pass

    def test_unicode(self):
        pass

    def test_datetime(self):

        dates = [datetime(2012, 1, x) for x in range(1, 20)]
        index = Index(dates)
        self.assertEqual(index.inferred_type, 'datetime64')

    def test_infer_dtype_datetime(self):

        arr = np.array([pd.Timestamp('2011-01-01'),
                        pd.Timestamp('2011-01-02')])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        arr = np.array([np.datetime64('2011-01-01'),
                        np.datetime64('2011-01-01')], dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime64')

        arr = np.array([datetime(2011, 1, 1), datetime(2012, 2, 1)])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        # starts with nan
        for n in [pd.NaT, np.nan]:
            arr = np.array([n, pd.Timestamp('2011-01-02')])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

            arr = np.array([n, np.datetime64('2011-01-02')])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime64')

            arr = np.array([n, datetime(2011, 1, 1)])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

            arr = np.array([n, pd.Timestamp('2011-01-02'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

            arr = np.array([n, np.datetime64('2011-01-02'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime64')

            arr = np.array([n, datetime(2011, 1, 1), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        # different type of nat
        arr = np.array([np.timedelta64('nat'),
                        np.datetime64('2011-01-02')], dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        arr = np.array([np.datetime64('2011-01-02'),
                        np.timedelta64('nat')], dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        # mixed datetime
        arr = np.array([datetime(2011, 1, 1),
                        pd.Timestamp('2011-01-02')])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        # should be datetime?
        arr = np.array([np.datetime64('2011-01-01'),
                        pd.Timestamp('2011-01-02')])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        arr = np.array([pd.Timestamp('2011-01-02'),
                        np.datetime64('2011-01-01')])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        arr = np.array([np.nan, pd.Timestamp('2011-01-02'), 1])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed-integer')

        arr = np.array([np.nan, pd.Timestamp('2011-01-02'), 1.1])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        arr = np.array([np.nan, '2011-01-01', pd.Timestamp('2011-01-02')])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

    def test_infer_dtype_timedelta(self):

        arr = np.array([pd.Timedelta('1 days'),
                        pd.Timedelta('2 days')])
        self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

        arr = np.array([np.timedelta64(1, 'D'),
                        np.timedelta64(2, 'D')], dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

        arr = np.array([timedelta(1), timedelta(2)])
        self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

        # starts with nan
        for n in [pd.NaT, np.nan]:
            arr = np.array([n, pd.Timedelta('1 days')])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

            arr = np.array([n, np.timedelta64(1, 'D')])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

            arr = np.array([n, timedelta(1)])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

            arr = np.array([n, pd.Timedelta('1 days'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

            arr = np.array([n, np.timedelta64(1, 'D'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

            arr = np.array([n, timedelta(1), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

        # different type of nat
        arr = np.array([np.datetime64('nat'), np.timedelta64(1, 'D')],
                       dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        arr = np.array([np.timedelta64(1, 'D'), np.datetime64('nat')],
                       dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

    def test_infer_dtype_all_nan_nat_like(self):
        arr = np.array([np.nan, np.nan])
        self.assertEqual(pd.lib.infer_dtype(arr), 'floating')

        # nan and None mix are result in mixed
        arr = np.array([np.nan, np.nan, None])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        arr = np.array([None, np.nan, np.nan])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        # pd.NaT
        arr = np.array([pd.NaT])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        arr = np.array([pd.NaT, np.nan])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        arr = np.array([np.nan, pd.NaT])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        arr = np.array([np.nan, pd.NaT, np.nan])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        arr = np.array([None, pd.NaT, None])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime')

        # np.datetime64(nat)
        arr = np.array([np.datetime64('nat')])
        self.assertEqual(pd.lib.infer_dtype(arr), 'datetime64')

        for n in [np.nan, pd.NaT, None]:
            arr = np.array([n, np.datetime64('nat'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime64')

            arr = np.array([pd.NaT, n, np.datetime64('nat'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'datetime64')

        arr = np.array([np.timedelta64('nat')], dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

        for n in [np.nan, pd.NaT, None]:
            arr = np.array([n, np.timedelta64('nat'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

            arr = np.array([pd.NaT, n, np.timedelta64('nat'), n])
            self.assertEqual(pd.lib.infer_dtype(arr), 'timedelta')

        # datetime / timedelta mixed
        arr = np.array([pd.NaT, np.datetime64('nat'),
                        np.timedelta64('nat'), np.nan])
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

        arr = np.array([np.timedelta64('nat'), np.datetime64('nat')],
                       dtype=object)
        self.assertEqual(pd.lib.infer_dtype(arr), 'mixed')

    def test_is_datetimelike_array_all_nan_nat_like(self):
        arr = np.array([np.nan, pd.NaT, np.datetime64('nat')])
        self.assertTrue(pd.lib.is_datetime_array(arr))
        self.assertTrue(pd.lib.is_datetime64_array(arr))
        self.assertFalse(pd.lib.is_timedelta_array(arr))
        self.assertFalse(pd.lib.is_timedelta64_array(arr))
        self.assertFalse(pd.lib.is_timedelta_or_timedelta64_array(arr))

        arr = np.array([np.nan, pd.NaT, np.timedelta64('nat')])
        self.assertFalse(pd.lib.is_datetime_array(arr))
        self.assertFalse(pd.lib.is_datetime64_array(arr))
        self.assertTrue(pd.lib.is_timedelta_array(arr))
        self.assertTrue(pd.lib.is_timedelta64_array(arr))
        self.assertTrue(pd.lib.is_timedelta_or_timedelta64_array(arr))

        arr = np.array([np.nan, pd.NaT, np.datetime64('nat'),
                        np.timedelta64('nat')])
        self.assertFalse(pd.lib.is_datetime_array(arr))
        self.assertFalse(pd.lib.is_datetime64_array(arr))
        self.assertFalse(pd.lib.is_timedelta_array(arr))
        self.assertFalse(pd.lib.is_timedelta64_array(arr))
        self.assertFalse(pd.lib.is_timedelta_or_timedelta64_array(arr))

        arr = np.array([np.nan, pd.NaT])
        self.assertTrue(pd.lib.is_datetime_array(arr))
        self.assertTrue(pd.lib.is_datetime64_array(arr))
        self.assertTrue(pd.lib.is_timedelta_array(arr))
        self.assertTrue(pd.lib.is_timedelta64_array(arr))
        self.assertTrue(pd.lib.is_timedelta_or_timedelta64_array(arr))

        arr = np.array([np.nan, np.nan], dtype=object)
        self.assertFalse(pd.lib.is_datetime_array(arr))
        self.assertFalse(pd.lib.is_datetime64_array(arr))
        self.assertFalse(pd.lib.is_timedelta_array(arr))
        self.assertFalse(pd.lib.is_timedelta64_array(arr))
        self.assertFalse(pd.lib.is_timedelta_or_timedelta64_array(arr))

    def test_date(self):

        dates = [date(2012, 1, x) for x in range(1, 20)]
        index = Index(dates)
        self.assertEqual(index.inferred_type, 'date')

    def test_to_object_array_tuples(self):
        r = (5, 6)
        values = [r]
        result = lib.to_object_array_tuples(values)

        try:
            # make sure record array works
            from collections import namedtuple
            record = namedtuple('record', 'x y')
            r = record(5, 6)
            values = [r]
            result = lib.to_object_array_tuples(values)  # noqa
        except ImportError:
            pass

    def test_to_object_array_width(self):
        # see gh-13320
        rows = [[1, 2, 3], [4, 5, 6]]

        expected = np.array(rows, dtype=object)
        out = lib.to_object_array(rows)
        tm.assert_numpy_array_equal(out, expected)

        expected = np.array(rows, dtype=object)
        out = lib.to_object_array(rows, min_width=1)
        tm.assert_numpy_array_equal(out, expected)

        expected = np.array([[1, 2, 3, None, None],
                             [4, 5, 6, None, None]], dtype=object)
        out = lib.to_object_array(rows, min_width=5)
        tm.assert_numpy_array_equal(out, expected)

    def test_object(self):

        # GH 7431
        # cannot infer more than this as only a single element
        arr = np.array([None], dtype='O')
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'mixed')

    def test_categorical(self):

        # GH 8974
        from pandas import Categorical, Series
        arr = Categorical(list('abc'))
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'categorical')

        result = lib.infer_dtype(Series(arr))
        self.assertEqual(result, 'categorical')

        arr = Categorical(list('abc'), categories=['cegfab'], ordered=True)
        result = lib.infer_dtype(arr)
        self.assertEqual(result, 'categorical')

        result = lib.infer_dtype(Series(arr))
        self.assertEqual(result, 'categorical')

    def test_is_period(self):
        self.assertTrue(lib.is_period(pd.Period('2011-01', freq='M')))
        self.assertFalse(lib.is_period(pd.PeriodIndex(['2011-01'], freq='M')))
        self.assertFalse(lib.is_period(pd.Timestamp('2011-01')))
        self.assertFalse(lib.is_period(1))
        self.assertFalse(lib.is_period(np.nan))


class TestConvert(tm.TestCase):

    def test_convert_objects(self):
        arr = np.array(['a', 'b', np.nan, np.nan, 'd', 'e', 'f'], dtype='O')
        result = lib.maybe_convert_objects(arr)
        self.assertTrue(result.dtype == np.object_)

    def test_convert_objects_ints(self):
        # test that we can detect many kinds of integers
        dtypes = ['i1', 'i2', 'i4', 'i8', 'u1', 'u2', 'u4', 'u8']

        for dtype_str in dtypes:
            arr = np.array(list(np.arange(20, dtype=dtype_str)), dtype='O')
            self.assertTrue(arr[0].dtype == np.dtype(dtype_str))
            result = lib.maybe_convert_objects(arr)
            self.assertTrue(issubclass(result.dtype.type, np.integer))

    def test_convert_objects_complex_number(self):
        for dtype in np.sctypes['complex']:
            arr = np.array(list(1j * np.arange(20, dtype=dtype)), dtype='O')
            self.assertTrue(arr[0].dtype == np.dtype(dtype))
            result = lib.maybe_convert_objects(arr)
            self.assertTrue(issubclass(result.dtype.type, np.complexfloating))


class Testisscalar(tm.TestCase):

    def test_isscalar_builtin_scalars(self):
        self.assertTrue(lib.isscalar(None))
        self.assertTrue(lib.isscalar(True))
        self.assertTrue(lib.isscalar(False))
        self.assertTrue(lib.isscalar(0.))
        self.assertTrue(lib.isscalar(np.nan))
        self.assertTrue(lib.isscalar('foobar'))
        self.assertTrue(lib.isscalar(b'foobar'))
        self.assertTrue(lib.isscalar(u('efoobar')))
        self.assertTrue(lib.isscalar(datetime(2014, 1, 1)))
        self.assertTrue(lib.isscalar(date(2014, 1, 1)))
        self.assertTrue(lib.isscalar(time(12, 0)))
        self.assertTrue(lib.isscalar(timedelta(hours=1)))
        self.assertTrue(lib.isscalar(pd.NaT))

    def test_isscalar_builtin_nonscalars(self):
        self.assertFalse(lib.isscalar({}))
        self.assertFalse(lib.isscalar([]))
        self.assertFalse(lib.isscalar([1]))
        self.assertFalse(lib.isscalar(()))
        self.assertFalse(lib.isscalar((1, )))
        self.assertFalse(lib.isscalar(slice(None)))
        self.assertFalse(lib.isscalar(Ellipsis))

    def test_isscalar_numpy_array_scalars(self):
        self.assertTrue(lib.isscalar(np.int64(1)))
        self.assertTrue(lib.isscalar(np.float64(1.)))
        self.assertTrue(lib.isscalar(np.int32(1)))
        self.assertTrue(lib.isscalar(np.object_('foobar')))
        self.assertTrue(lib.isscalar(np.str_('foobar')))
        self.assertTrue(lib.isscalar(np.unicode_(u('foobar'))))
        self.assertTrue(lib.isscalar(np.bytes_(b'foobar')))
        self.assertTrue(lib.isscalar(np.datetime64('2014-01-01')))
        self.assertTrue(lib.isscalar(np.timedelta64(1, 'h')))

    def test_isscalar_numpy_zerodim_arrays(self):
        for zerodim in [np.array(1), np.array('foobar'),
                        np.array(np.datetime64('2014-01-01')),
                        np.array(np.timedelta64(1, 'h')),
                        np.array(np.datetime64('NaT'))]:
            self.assertFalse(lib.isscalar(zerodim))
            self.assertTrue(lib.isscalar(lib.item_from_zerodim(zerodim)))

    def test_isscalar_numpy_arrays(self):
        self.assertFalse(lib.isscalar(np.array([])))
        self.assertFalse(lib.isscalar(np.array([[]])))
        self.assertFalse(lib.isscalar(np.matrix('1; 2')))

    def test_isscalar_pandas_scalars(self):
        self.assertTrue(lib.isscalar(pd.Timestamp('2014-01-01')))
        self.assertTrue(lib.isscalar(pd.Timedelta(hours=1)))
        self.assertTrue(lib.isscalar(pd.Period('2014-01-01')))

    def test_lisscalar_pandas_containers(self):
        self.assertFalse(lib.isscalar(pd.Series()))
        self.assertFalse(lib.isscalar(pd.Series([1])))
        self.assertFalse(lib.isscalar(pd.DataFrame()))
        self.assertFalse(lib.isscalar(pd.DataFrame([[1]])))
        self.assertFalse(lib.isscalar(pd.Panel()))
        self.assertFalse(lib.isscalar(pd.Panel([[[1]]])))
        self.assertFalse(lib.isscalar(pd.Index([])))
        self.assertFalse(lib.isscalar(pd.Index([1])))


class TestParseSQL(tm.TestCase):

    def test_convert_sql_column_floats(self):
        arr = np.array([1.5, None, 3, 4.2], dtype=object)
        result = lib.convert_sql_column(arr)
        expected = np.array([1.5, np.nan, 3, 4.2], dtype='f8')
        self.assert_numpy_array_equal(result, expected)

    def test_convert_sql_column_strings(self):
        arr = np.array(['1.5', None, '3', '4.2'], dtype=object)
        result = lib.convert_sql_column(arr)
        expected = np.array(['1.5', np.nan, '3', '4.2'], dtype=object)
        self.assert_numpy_array_equal(result, expected)

    def test_convert_sql_column_unicode(self):
        arr = np.array([u('1.5'), None, u('3'), u('4.2')],
                       dtype=object)
        result = lib.convert_sql_column(arr)
        expected = np.array([u('1.5'), np.nan, u('3'), u('4.2')],
                            dtype=object)
        self.assert_numpy_array_equal(result, expected)

    def test_convert_sql_column_ints(self):
        arr = np.array([1, 2, 3, 4], dtype='O')
        arr2 = np.array([1, 2, 3, 4], dtype='i4').astype('O')
        result = lib.convert_sql_column(arr)
        result2 = lib.convert_sql_column(arr2)
        expected = np.array([1, 2, 3, 4], dtype='i8')
        self.assert_numpy_array_equal(result, expected)
        self.assert_numpy_array_equal(result2, expected)

        arr = np.array([1, 2, 3, None, 4], dtype='O')
        result = lib.convert_sql_column(arr)
        expected = np.array([1, 2, 3, np.nan, 4], dtype='f8')
        self.assert_numpy_array_equal(result, expected)

    def test_convert_sql_column_longs(self):
        arr = np.array([long(1), long(2), long(3), long(4)], dtype='O')
        result = lib.convert_sql_column(arr)
        expected = np.array([1, 2, 3, 4], dtype='i8')
        self.assert_numpy_array_equal(result, expected)

        arr = np.array([long(1), long(2), long(3), None, long(4)], dtype='O')
        result = lib.convert_sql_column(arr)
        expected = np.array([1, 2, 3, np.nan, 4], dtype='f8')
        self.assert_numpy_array_equal(result, expected)

    def test_convert_sql_column_bools(self):
        arr = np.array([True, False, True, False], dtype='O')
        result = lib.convert_sql_column(arr)
        expected = np.array([True, False, True, False], dtype=bool)
        self.assert_numpy_array_equal(result, expected)

        arr = np.array([True, False, None, False], dtype='O')
        result = lib.convert_sql_column(arr)
        expected = np.array([True, False, np.nan, False], dtype=object)
        self.assert_numpy_array_equal(result, expected)

    def test_convert_sql_column_decimals(self):
        from decimal import Decimal
        arr = np.array([Decimal('1.5'), None, Decimal('3'), Decimal('4.2')])
        result = lib.convert_sql_column(arr)
        expected = np.array([1.5, np.nan, 3, 4.2], dtype='f8')
        self.assert_numpy_array_equal(result, expected)

    def test_convert_downcast_int64(self):
        from pandas.parser import na_values

        arr = np.array([1, 2, 7, 8, 10], dtype=np.int64)
        expected = np.array([1, 2, 7, 8, 10], dtype=np.int8)

        # default argument
        result = lib.downcast_int64(arr, na_values)
        self.assert_numpy_array_equal(result, expected)

        result = lib.downcast_int64(arr, na_values, use_unsigned=False)
        self.assert_numpy_array_equal(result, expected)

        expected = np.array([1, 2, 7, 8, 10], dtype=np.uint8)
        result = lib.downcast_int64(arr, na_values, use_unsigned=True)
        self.assert_numpy_array_equal(result, expected)

        # still cast to int8 despite use_unsigned=True
        # because of the negative number as an element
        arr = np.array([1, 2, -7, 8, 10], dtype=np.int64)
        expected = np.array([1, 2, -7, 8, 10], dtype=np.int8)
        result = lib.downcast_int64(arr, na_values, use_unsigned=True)
        self.assert_numpy_array_equal(result, expected)

        arr = np.array([1, 2, 7, 8, 300], dtype=np.int64)
        expected = np.array([1, 2, 7, 8, 300], dtype=np.int16)
        result = lib.downcast_int64(arr, na_values)
        self.assert_numpy_array_equal(result, expected)

        int8_na = na_values[np.int8]
        int64_na = na_values[np.int64]
        arr = np.array([int64_na, 2, 3, 10, 15], dtype=np.int64)
        expected = np.array([int8_na, 2, 3, 10, 15], dtype=np.int8)
        result = lib.downcast_int64(arr, na_values)
        self.assert_numpy_array_equal(result, expected)


if __name__ == '__main__':
    import nose

    nose.runmodule(argv=[__file__, '-vvs', '-x', '--pdb', '--pdb-failure'],
                   exit=False)
