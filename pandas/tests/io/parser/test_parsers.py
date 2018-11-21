# -*- coding: utf-8 -*-

import os

import pytest

from pandas._libs.tslib import Timestamp
from pandas.compat import StringIO
from pandas.errors import AbstractMethodError

from pandas import DataFrame, read_csv, read_table
import pandas.util.testing as tm

from .common import ParserTests
from .python_parser_only import PythonParserTests
from .quoting import QuotingTests
from .usecols import UsecolsTests


class BaseParser(ParserTests, UsecolsTests,
                 QuotingTests):

    def read_csv(self, *args, **kwargs):
        raise NotImplementedError

    def read_table(self, *args, **kwargs):
        raise NotImplementedError

    def float_precision_choices(self):
        raise AbstractMethodError(self)

    @pytest.fixture(autouse=True)
    def setup_method(self, datapath):
        self.dirpath = datapath('io', 'parser', 'data')
        self.csv1 = os.path.join(self.dirpath, 'test1.csv')
        self.csv2 = os.path.join(self.dirpath, 'test2.csv')
        self.xls1 = os.path.join(self.dirpath, 'test.xls')
        self.csv_shiftjs = os.path.join(self.dirpath, 'sauron.SHIFT_JIS.csv')


class TestCParserHighMemory(BaseParser):
    engine = 'c'
    low_memory = False
    float_precision_choices = [None, 'high', 'round_trip']

    def read_csv(self, *args, **kwds):
        kwds = kwds.copy()
        kwds['engine'] = self.engine
        kwds['low_memory'] = self.low_memory
        return read_csv(*args, **kwds)

    def read_table(self, *args, **kwds):
        kwds = kwds.copy()
        kwds['engine'] = self.engine
        kwds['low_memory'] = self.low_memory
        with tm.assert_produces_warning(FutureWarning):
            df = read_table(*args, **kwds)
        return df


class TestCParserLowMemory(BaseParser):
    engine = 'c'
    low_memory = True
    float_precision_choices = [None, 'high', 'round_trip']

    def read_csv(self, *args, **kwds):
        kwds = kwds.copy()
        kwds['engine'] = self.engine
        kwds['low_memory'] = self.low_memory
        return read_csv(*args, **kwds)

    def read_table(self, *args, **kwds):
        kwds = kwds.copy()
        kwds['engine'] = self.engine
        kwds['low_memory'] = True
        with tm.assert_produces_warning(FutureWarning):
            df = read_table(*args, **kwds)
        return df


class TestPythonParser(BaseParser, PythonParserTests):
    engine = 'python'
    float_precision_choices = [None]

    def read_csv(self, *args, **kwds):
        kwds = kwds.copy()
        kwds['engine'] = self.engine
        return read_csv(*args, **kwds)

    def read_table(self, *args, **kwds):
        kwds = kwds.copy()
        kwds['engine'] = self.engine
        with tm.assert_produces_warning(FutureWarning):
            df = read_table(*args, **kwds)
        return df


class TestUnsortedUsecols(object):
    def test_override__set_noconvert_columns(self):
        # GH 17351 - usecols needs to be sorted in _setnoconvert_columns
        # based on the test_usecols_with_parse_dates test from usecols.py
        from pandas.io.parsers import CParserWrapper, TextFileReader

        s = """a,b,c,d,e
        0,1,20140101,0900,4
        0,1,20140102,1000,4"""

        parse_dates = [[1, 2]]
        cols = {
            'a': [0, 0],
            'c_d': [
                Timestamp('2014-01-01 09:00:00'),
                Timestamp('2014-01-02 10:00:00')
            ]
        }
        expected = DataFrame(cols, columns=['c_d', 'a'])

        class MyTextFileReader(TextFileReader):
            def __init__(self):
                self._currow = 0
                self.squeeze = False

        class MyCParserWrapper(CParserWrapper):
            def _set_noconvert_columns(self):
                if self.usecols_dtype == 'integer':
                    # self.usecols is a set, which is documented as unordered
                    # but in practice, a CPython set of integers is sorted.
                    # In other implementations this assumption does not hold.
                    # The following code simulates a different order, which
                    # before GH 17351 would cause the wrong columns to be
                    # converted via the parse_dates parameter
                    self.usecols = list(self.usecols)
                    self.usecols.reverse()
                return CParserWrapper._set_noconvert_columns(self)

        parser = MyTextFileReader()
        parser.options = {'usecols': [0, 2, 3],
                          'parse_dates': parse_dates,
                          'delimiter': ','}
        parser._engine = MyCParserWrapper(StringIO(s), **parser.options)
        df = parser.read()

        tm.assert_frame_equal(df, expected)
