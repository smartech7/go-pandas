# pylint: disable-msg=E1101,W0612

from datetime import datetime, timedelta, date
import os
import operator
import unittest

import nose

from numpy import nan as NA
import numpy as np

from pandas import (Index, Series, TimeSeries, DataFrame, isnull, notnull,
                    bdate_range, date_range)
import pandas.core.common as com

from pandas.util.testing import assert_series_equal, assert_almost_equal
import pandas.util.testing as tm

import pandas.core.strings as strings

class TestStringMethods(unittest.TestCase):

    def test_cat(self):
        one = ['a', 'a', 'b', 'b', 'c', NA]
        two = ['a', NA, 'b', 'd', 'foo', NA]

        # single array
        result = strings.str_cat(one)
        self.assert_(isnull(result))

        result = strings.str_cat(one, na_rep='NA')
        exp = 'aabbcNA'
        self.assertEquals(result, exp)

        result = strings.str_cat(one, na_rep='-')
        exp = 'aabbc-'
        self.assertEquals(result, exp)

        result = strings.str_cat(one, sep='_', na_rep='NA')
        exp = 'a_a_b_b_c_NA'
        self.assertEquals(result, exp)

        # Multiple arrays
        result = strings.str_cat(one, [two], na_rep='NA')
        exp = ['aa', 'aNA', 'bb', 'bd', 'cfoo', 'NANA']
        self.assert_(np.array_equal(result, exp))

        result = strings.str_cat(one, two)
        exp = ['aa', NA, 'bb', 'bd', 'cfoo', NA]
        tm.assert_almost_equal(result, exp)

    def test_count(self):
        values = ['foo', 'foofoo', NA, 'foooofooofommmfoo']

        result = strings.str_count(values, 'f[o]+')
        exp = [1, 2, NA, 4]
        tm.assert_almost_equal(result, exp)

        result = Series(values).str.count('f[o]+')
        self.assert_(isinstance(result, Series))
        tm.assert_almost_equal(result, exp)

        #mixed
        mixed = ['a', NA, 'b', True, datetime.today(), 'foo', None, 1, 2.]
        rs = strings.str_count(mixed, 'a')
        xp = [1, NA, 0, NA, NA, 0, NA, NA, NA]
        tm.assert_almost_equal(rs, xp)

        rs = Series(mixed).str.count('a')
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_contains(self):
        values = ['foo', NA, 'fooommm__foo', 'mmm_']
        pat = 'mmm[_]+'

        result = strings.str_contains(values, pat)
        expected = [False, np.nan, True, True]
        tm.assert_almost_equal(result, expected)

        values = ['foo', 'xyz', 'fooommm__foo', 'mmm_']
        result = strings.str_contains(values, pat)
        expected = [False, False, True, True]
        self.assert_(result.dtype == np.bool_)
        tm.assert_almost_equal(result, expected)

        #mixed
        mixed = ['a', NA, 'b', True, datetime.today(), 'foo', None, 1, 2.]
        rs = strings.str_contains(mixed, 'o')
        xp = [False, NA, False, NA, NA, True, NA, NA, NA]
        tm.assert_almost_equal(rs, xp)

        rs = Series(mixed).str.contains('o')
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_startswith(self):
        values = Series(['om', NA, 'foo_nom', 'nom', 'bar_foo', NA, 'foo'])

        result = values.str.startswith('foo')
        exp = Series([False, NA, True, False, False, NA, True])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = ['a', NA, 'b', True, datetime.today(), 'foo', None, 1, 2.]
        rs = strings.str_startswith(mixed, 'f')
        xp = [False, NA, False, NA, NA, True, NA, NA, NA]
        tm.assert_almost_equal(rs, xp)

        rs = Series(mixed).str.startswith('f')
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_endswith(self):
        values = Series(['om', NA, 'foo_nom', 'nom', 'bar_foo', NA, 'foo'])

        result = values.str.endswith('foo')
        exp = Series([False, NA, False, False, True, NA, True])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = ['a', NA, 'b', True, datetime.today(), 'foo', None, 1, 2.]
        rs = strings.str_endswith(mixed, 'f')
        xp = [False, NA, False, NA, NA, False, NA, NA, NA]
        tm.assert_almost_equal(rs, xp)

        rs = Series(mixed).str.endswith('f')
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_lower_upper(self):
        values = Series(['om', NA, 'nom', 'nom'])

        result = values.str.upper()
        exp = Series(['OM', NA, 'NOM', 'NOM'])
        tm.assert_series_equal(result, exp)

        result = result.str.lower()
        tm.assert_series_equal(result, values)

        #mixed
        mixed = Series(['a', NA, 'b', True, datetime.today(), 'foo', None,
                        1, 2.])
        mixed = mixed.str.upper()
        rs = Series(mixed).str.lower()
        xp = ['a', NA, 'b', NA, NA, 'foo', NA, NA, NA]
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_replace(self):
        values = Series(['fooBAD__barBAD', NA])

        result = values.str.replace('BAD[_]*', '')
        exp = Series(['foobar', NA])
        tm.assert_series_equal(result, exp)

        result = values.str.replace('BAD[_]*', '', n=1)
        exp = Series(['foobarBAD', NA])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = Series(['aBAD', NA, 'bBAD', True, datetime.today(), 'fooBAD',
                        None, 1, 2.])

        rs = Series(mixed).str.replace('BAD[_]*', '')
        xp = ['a', NA, 'b', NA, NA, 'foo', NA, NA, NA]
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_repeat(self):
        values = Series(['a', 'b', NA, 'c', NA, 'd'])

        result = values.str.repeat(3)
        exp = Series(['aaa', 'bbb', NA, 'ccc', NA, 'ddd'])
        tm.assert_series_equal(result, exp)

        result = values.str.repeat([1, 2, 3, 4, 5, 6])
        exp = Series(['a', 'bb', NA, 'cccc', NA, 'dddddd'])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = Series(['a', NA, 'b', True, datetime.today(), 'foo',
                        None, 1, 2.])

        rs = Series(mixed).str.repeat(3)
        xp = ['aaa', NA, 'bbb', NA, NA, 'foofoofoo', NA, NA, NA]
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_match(self):
        values = Series(['fooBAD__barBAD', NA, 'foo'])

        result = values.str.match('.*(BAD[_]+).*(BAD)')
        exp = Series([('BAD__', 'BAD'), NA, []])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = Series(['aBAD_BAD', NA, 'BAD_b_BAD', True, datetime.today(),
                        'foo', None, 1, 2.])

        rs = Series(mixed).str.match('.*(BAD[_]+).*(BAD)')
        xp = [('BAD_', 'BAD'), NA, ('BAD_', 'BAD'), NA, NA, [], NA, NA, NA]
        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_join(self):
        values = Series(['a_b_c', 'c_d_e', np.nan, 'f_g_h'])
        result = values.str.split('_').str.join('_')
        tm.assert_series_equal(values, result)

        #mixed
        mixed = Series(['a_b', NA, 'asdf_cas_asdf', True, datetime.today(),
                        'foo', None, 1, 2.])

        rs = Series(mixed).str.split('_').str.join('_')
        xp = Series(['a_b', NA, 'asdf_cas_asdf', NA, NA, 'foo', NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_len(self):
        values = Series(['foo', 'fooo', 'fooooo', np.nan, 'fooooooo'])

        result = values.str.len()
        exp = values.map(lambda x: len(x) if com.notnull(x) else NA)
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = Series(['a_b', NA, 'asdf_cas_asdf', True, datetime.today(),
                        'foo', None, 1, 2.])

        rs = Series(mixed).str.len()
        xp = Series([3, NA, 13, NA, NA, 3, NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_findall(self):
        values = Series(['fooBAD__barBAD', NA, 'foo', 'BAD'])

        result = values.str.findall('BAD[_]*')
        exp = Series([['BAD__', 'BAD'], NA, [], ['BAD']])
        tm.assert_almost_equal(result, exp)

        #mixed
        mixed = Series(['fooBAD__barBAD', NA, 'foo', True, datetime.today(),
                        'BAD', None, 1, 2.])

        rs = Series(mixed).str.findall('BAD[_]*')
        xp = Series([['BAD__', 'BAD'], NA, [], NA, NA, ['BAD'], NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_pad(self):
        values = Series(['a', 'b', NA, 'c', NA, 'eeeeee'])

        result = values.str.pad(5, side='left')
        exp = Series(['    a', '    b', NA, '    c', NA, 'eeeeee'])
        tm.assert_almost_equal(result, exp)

        result = values.str.pad(5, side='right')
        exp = Series(['a    ', 'b    ', NA, 'c    ', NA, 'eeeeee'])
        tm.assert_almost_equal(result, exp)

        result = values.str.pad(5, side='both')
        exp = Series(['  a  ', '  b  ', NA, '  c  ', NA, 'eeeeee'])
        tm.assert_almost_equal(result, exp)

        #mixed
        mixed = Series(['a', NA, 'b', True, datetime.today(),
                        'ee', None, 1, 2.])

        rs = Series(mixed).str.pad(5, side='left')
        xp = Series(['    a', NA, '    b', NA, NA, '   ee', NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

        mixed = Series(['a', NA, 'b', True, datetime.today(),
                        'ee', None, 1, 2.])

        rs = Series(mixed).str.pad(5, side='right')
        xp = Series(['a    ', NA, 'b    ', NA, NA, 'ee   ', NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

        mixed = Series(['a', NA, 'b', True, datetime.today(),
                        'ee', None, 1, 2.])

        rs = Series(mixed).str.pad(5, side='both')
        xp = Series(['  a  ', NA, '  b  ', NA, NA, '  ee ', NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_center(self):
        values = Series(['a', 'b', NA, 'c', NA, 'eeeeee'])

        result = values.str.center(5)
        exp = Series(['  a  ', '  b  ', NA, '  c  ', NA, 'eeeeee'])
        tm.assert_almost_equal(result, exp)

        #mixed
        mixed = Series(['a', NA, 'b', True, datetime.today(),
                        'c', 'eee', None, 1, 2.])

        rs = Series(mixed).str.center(5)
        xp = Series(['  a  ', NA, '  b  ', NA, NA, '  c  ', ' eee ', NA, NA,
                     NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_split(self):
        values = Series(['a_b_c', 'c_d_e', NA, 'f_g_h'])

        result = values.str.split('_')
        exp = Series([['a', 'b', 'c'], ['c', 'd', 'e'], NA, ['f', 'g', 'h']])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = Series(['a_b_c', NA, 'd_e_f', True, datetime.today(),
                        None, 1, 2.])

        rs = Series(mixed).str.split('_')
        xp = Series([['a', 'b', 'c'], NA, ['d', 'e', 'f'], NA, NA,
                     NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_slice(self):
        values = Series(['aafootwo','aabartwo', NA, 'aabazqux'])

        result = values.str.slice(2, 5)
        exp = Series(['foo', 'bar', NA, 'baz'])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = Series(['aafootwo', NA, 'aabartwo', True, datetime.today(),
                        None, 1, 2.])

        rs = Series(mixed).str.slice(2, 5)
        xp = Series(['foo', NA, 'bar', NA, NA,
                     NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_slice_replace(self):
        pass

    def test_strip_lstrip_rstrip(self):
        values = Series(['  aa   ', ' bb \n', NA, 'cc  '])

        result = values.str.strip()
        exp = Series(['aa', 'bb', NA, 'cc'])
        tm.assert_series_equal(result, exp)

        result = values.str.lstrip()
        exp = Series(['aa   ', 'bb \n', NA, 'cc  '])
        tm.assert_series_equal(result, exp)

        result = values.str.rstrip()
        exp = Series(['  aa', ' bb', NA, 'cc'])
        tm.assert_series_equal(result, exp)

        #mixed
        mixed = Series(['  aa  ', NA, ' bb \t\n', True, datetime.today(),
                        None, 1, 2.])

        rs = Series(mixed).str.strip()
        xp = Series(['aa', NA, 'bb', NA, NA,
                     NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

        rs = Series(mixed).str.lstrip()
        xp = Series(['aa  ', NA, 'bb \t\n', NA, NA,
                     NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

        rs = Series(mixed).str.rstrip()
        xp = Series(['  aa', NA, ' bb', NA, NA,
                     NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

    def test_wrap(self):
        pass

    def test_get(self):
        values = Series(['a_b_c', 'c_d_e', np.nan, 'f_g_h'])

        result = values.str.split('_').str.get(1)
        expected = Series(['b', 'd', np.nan, 'g'])
        tm.assert_series_equal(result, expected)

        #mixed
        mixed = Series(['a_b_c', NA, 'c_d_e', True, datetime.today(),
                        None, 1, 2.])

        rs = Series(mixed).str.split('_').str.get(1)
        xp = Series(['b', NA, 'd', NA, NA,
                     NA, NA, NA])

        self.assert_(isinstance(rs, Series))
        tm.assert_almost_equal(rs, xp)

if __name__ == '__main__':
    nose.runmodule(argv=[__file__,'-vvs','-x','--pdb', '--pdb-failure'],
                   exit=False)
