import pytest

import operator

import pandas as pd
from .base import BaseExtensionTests


class BaseOpsUtil(BaseExtensionTests):
    def get_op_from_name(self, op_name):
        short_opname = op_name.strip('_')
        try:
            op = getattr(operator, short_opname)
        except AttributeError:
            # Assume it is the reverse operator
            rop = getattr(operator, short_opname[1:])
            op = lambda x, y: rop(y, x)

        return op

    def check_opname(self, s, op_name, other, exc=NotImplementedError):
        op = self.get_op_from_name(op_name)

        self._check_op(s, op, other, exc)

    def _check_op(self, s, op, other, exc=NotImplementedError):
        if exc is None:
            result = op(s, other)
            expected = s.combine(other, op)
            self.assert_series_equal(result, expected)
        else:
            with pytest.raises(exc):
                op(s, other)


class BaseArithmeticOpsTests(BaseOpsUtil):
    """Various Series and DataFrame arithmetic ops methods."""

    def test_arith_scalar(self, data, all_arithmetic_operators):
        # scalar
        op_name = all_arithmetic_operators
        s = pd.Series(data)
        self.check_opname(s, op_name, s.iloc[0], exc=TypeError)

    def test_arith_array(self, data, all_arithmetic_operators):
        # ndarray & other series
        op_name = all_arithmetic_operators
        s = pd.Series(data)
        self.check_opname(s, op_name, [s.iloc[0]] * len(s), exc=TypeError)

    def test_divmod(self, data):
        s = pd.Series(data)
        self._check_op(s, divmod, 1, exc=TypeError)
        self._check_op(1, divmod, s, exc=TypeError)

    def test_error(self, data, all_arithmetic_operators):
        # invalid ops
        op_name = all_arithmetic_operators
        with pytest.raises(AttributeError):
            getattr(data, op_name)


class BaseComparisonOpsTests(BaseOpsUtil):
    """Various Series and DataFrame comparison ops methods."""

    def _compare_other(self, s, data, op_name, other):
        op = self.get_op_from_name(op_name)
        if op_name == '__eq__':
            assert getattr(data, op_name)(other) is NotImplemented
            assert not op(s, other).all()
        elif op_name == '__ne__':
            assert getattr(data, op_name)(other) is NotImplemented
            assert op(s, other).all()

        else:

            # array
            assert getattr(data, op_name)(other) is NotImplemented

            # series
            s = pd.Series(data)
            with pytest.raises(TypeError):
                op(s, other)

    def test_compare_scalar(self, data, all_compare_operators):
        op_name = all_compare_operators
        s = pd.Series(data)
        self._compare_other(s, data, op_name, 0)

    def test_compare_array(self, data, all_compare_operators):
        op_name = all_compare_operators
        s = pd.Series(data)
        other = [0] * len(data)
        self._compare_other(s, data, op_name, other)
