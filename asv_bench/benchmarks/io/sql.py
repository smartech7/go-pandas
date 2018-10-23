import sqlite3

import numpy as np
import pandas.util.testing as tm
from pandas import DataFrame, date_range, read_sql_query, read_sql_table
from sqlalchemy import create_engine


class SQL(object):

    params = ['sqlalchemy', 'sqlite']
    param_names = ['connection']

    def setup(self, connection):
        N = 10000
        con = {'sqlalchemy': create_engine('sqlite:///:memory:'),
               'sqlite': sqlite3.connect(':memory:')}
        self.table_name = 'test_type'
        self.query_all = 'SELECT * FROM {}'.format(self.table_name)
        self.con = con[connection]
        self.df = DataFrame({'float': np.random.randn(N),
                             'float_with_nan': np.random.randn(N),
                             'string': ['foo'] * N,
                             'bool': [True] * N,
                             'int': np.random.randint(0, N, size=N),
                             'datetime': date_range('2000-01-01',
                                                    periods=N,
                                                    freq='s')},
                            index=tm.makeStringIndex(N))
        self.df.loc[1000:3000, 'float_with_nan'] = np.nan
        self.df['datetime_string'] = self.df['datetime'].astype(str)
        self.df.to_sql(self.table_name, self.con, if_exists='replace')

    def time_to_sql_dataframe(self, connection):
        self.df.to_sql('test1', self.con, if_exists='replace')

    def time_read_sql_query(self, connection):
        read_sql_query(self.query_all, self.con)


class WriteSQLDtypes(object):

    params = (['sqlalchemy', 'sqlite'],
              ['float', 'float_with_nan', 'string', 'bool', 'int', 'datetime'])
    param_names = ['connection', 'dtype']

    def setup(self, connection, dtype):
        N = 10000
        con = {'sqlalchemy': create_engine('sqlite:///:memory:'),
               'sqlite': sqlite3.connect(':memory:')}
        self.table_name = 'test_type'
        self.query_col = 'SELECT {} FROM {}'.format(dtype, self.table_name)
        self.con = con[connection]
        self.df = DataFrame({'float': np.random.randn(N),
                             'float_with_nan': np.random.randn(N),
                             'string': ['foo'] * N,
                             'bool': [True] * N,
                             'int': np.random.randint(0, N, size=N),
                             'datetime': date_range('2000-01-01',
                                                    periods=N,
                                                    freq='s')},
                            index=tm.makeStringIndex(N))
        self.df.loc[1000:3000, 'float_with_nan'] = np.nan
        self.df['datetime_string'] = self.df['datetime'].astype(str)
        self.df.to_sql(self.table_name, self.con, if_exists='replace')

    def time_to_sql_dataframe_column(self, connection, dtype):
        self.df[[dtype]].to_sql('test1', self.con, if_exists='replace')

    def time_read_sql_query_select_column(self, connection, dtype):
        read_sql_query(self.query_col, self.con)


class ReadSQLTable(object):

    def setup(self):
        N = 10000
        self.table_name = 'test'
        self.con = create_engine('sqlite:///:memory:')
        self.df = DataFrame({'float': np.random.randn(N),
                             'float_with_nan': np.random.randn(N),
                             'string': ['foo'] * N,
                             'bool': [True] * N,
                             'int': np.random.randint(0, N, size=N),
                             'datetime': date_range('2000-01-01',
                                                    periods=N,
                                                    freq='s')},
                            index=tm.makeStringIndex(N))
        self.df.loc[1000:3000, 'float_with_nan'] = np.nan
        self.df['datetime_string'] = self.df['datetime'].astype(str)
        self.df.to_sql(self.table_name, self.con, if_exists='replace')

    def time_read_sql_table_all(self):
        read_sql_table(self.table_name, self.con)

    def time_read_sql_table_parse_dates(self):
        read_sql_table(self.table_name, self.con, columns=['datetime_string'],
                       parse_dates=['datetime_string'])


class ReadSQLTableDtypes(object):

    params = ['float', 'float_with_nan', 'string', 'bool', 'int', 'datetime']
    param_names = ['dtype']

    def setup(self, dtype):
        N = 10000
        self.table_name = 'test'
        self.con = create_engine('sqlite:///:memory:')
        self.df = DataFrame({'float': np.random.randn(N),
                             'float_with_nan': np.random.randn(N),
                             'string': ['foo'] * N,
                             'bool': [True] * N,
                             'int': np.random.randint(0, N, size=N),
                             'datetime': date_range('2000-01-01',
                                                    periods=N,
                                                    freq='s')},
                            index=tm.makeStringIndex(N))
        self.df.loc[1000:3000, 'float_with_nan'] = np.nan
        self.df['datetime_string'] = self.df['datetime'].astype(str)
        self.df.to_sql(self.table_name, self.con, if_exists='replace')

    def time_read_sql_table_column(self, dtype):
        read_sql_table(self.table_name, self.con, columns=[dtype])


from ..pandas_vb_common import setup  # noqa: F401
