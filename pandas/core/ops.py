"""
Arithmetic operations for PandasObjects

This is not a public API.
"""
# necessary to enforce truediv in Python 2.X
from __future__ import division
import operator

import numpy as np
import pandas as pd

from pandas._libs import (lib, index as libindex,
                          algos as libalgos)

from pandas import compat
from pandas.util._decorators import Appender

from pandas.compat import bind_method
import pandas.core.missing as missing
import pandas.core.common as com

from pandas.errors import NullFrequencyError
from pandas.core.dtypes.missing import notna, isna
from pandas.core.dtypes.common import (
    needs_i8_conversion,
    is_datetimelike_v_numeric,
    is_integer_dtype, is_categorical_dtype,
    is_object_dtype, is_timedelta64_dtype,
    is_datetime64_dtype, is_datetime64tz_dtype,
    is_bool_dtype,
    is_list_like,
    is_scalar,
    _ensure_object)
from pandas.core.dtypes.cast import (
    maybe_upcast_putmask, find_common_type,
    construct_1d_object_array_from_listlike)
from pandas.core.dtypes.generic import (
    ABCSeries,
    ABCDataFrame,
    ABCIndex,
    ABCSparseSeries, ABCSparseArray)


# -----------------------------------------------------------------------------
# Reversed Operations not available in the stdlib operator module.
# Defining these instead of using lambdas allows us to reference them by name.

def radd(left, right):
    return right + left


def rsub(left, right):
    return right - left


def rmul(left, right):
    return right * left


def rdiv(left, right):
    return right / left


def rtruediv(left, right):
    return right / left


def rfloordiv(left, right):
    return right // left


def rmod(left, right):
    return right % left


def rdivmod(left, right):
    return divmod(right, left)


def rpow(left, right):
    return right ** left


def rand_(left, right):
    return operator.and_(right, left)


def ror_(left, right):
    return operator.or_(right, left)


def rxor(left, right):
    return operator.xor(right, left)


# -----------------------------------------------------------------------------

def make_invalid_op(name):
    """
    Return a binary method that always raises a TypeError.

    Parameters
    ----------
    name : str

    Returns
    -------
    invalid_op : function
    """
    def invalid_op(self, other=None):
        raise TypeError("cannot perform {name} with this index type: "
                        "{typ}".format(name=name, typ=type(self).__name__))

    invalid_op.__name__ = name
    return invalid_op


def _gen_eval_kwargs(name):
    """
    Find the keyword arguments to pass to numexpr for the given operation.

    Parameters
    ----------
    name : str

    Returns
    -------
    eval_kwargs : dict

    Examples
    --------
    >>> _gen_eval_kwargs("__add__")
    {}

    >>> _gen_eval_kwargs("rtruediv")
    {"reversed": True, "truediv": True}
    """
    kwargs = {}

    # Series and Panel appear to only pass __add__, __radd__, ...
    # but DataFrame gets both these dunder names _and_ non-dunder names
    # add, radd, ...
    name = name.replace('__', '')

    if name.startswith('r'):
        if name not in ['radd', 'rand', 'ror', 'rxor']:
            # Exclude commutative operations
            kwargs['reversed'] = True

    if name in ['truediv', 'rtruediv']:
        kwargs['truediv'] = True

    if name in ['ne']:
        kwargs['masker'] = True

    return kwargs


def _gen_fill_zeros(name):
    """
    Find the appropriate fill value to use when filling in undefined values
    in the results of the given operation caused by operating on
    (generally dividing by) zero.

    Parameters
    ----------
    name : str

    Returns
    -------
    fill_value : {None, np.nan, np.inf}
    """
    name = name.strip('__')
    if 'div' in name:
        # truediv, floordiv, div, and reversed variants
        fill_value = np.inf
    elif 'mod' in name:
        # mod, rmod
        fill_value = np.nan
    else:
        fill_value = None
    return fill_value


def _get_frame_op_default_axis(name):
    """
    Only DataFrame cares about default_axis, specifically:
    special methods have default_axis=None and flex methods
    have default_axis='columns'.

    Parameters
    ----------
    name : str

    Returns
    -------
    default_axis: str or None
    """
    if name.replace('__r', '__') in ['__and__', '__or__', '__xor__']:
        # bool methods
        return 'columns'
    elif name.startswith('__'):
        # __add__, __mul__, ...
        return None
    else:
        # add, mul, ...
        return 'columns'


def _get_opstr(op, cls):
    """
    Find the operation string, if any, to pass to numexpr for this
    operation.

    Parameters
    ----------
    op : binary operator
    cls : class

    Returns
    -------
    op_str : string or None
    """
    # numexpr is available for non-sparse classes
    subtyp = getattr(cls, '_subtyp', '')
    use_numexpr = 'sparse' not in subtyp

    if not use_numexpr:
        # if we're not using numexpr, then don't pass a str_rep
        return None

    return {operator.add: '+',
            radd: '+',
            operator.mul: '*',
            rmul: '*',
            operator.sub: '-',
            rsub: '-',
            operator.truediv: '/',
            rtruediv: '/',
            operator.floordiv: '//',
            rfloordiv: '//',
            operator.mod: None,  # TODO: Why None for mod but '%' for rmod?
            rmod: '%',
            operator.pow: '**',
            rpow: '**',
            operator.eq: '==',
            operator.ne: '!=',
            operator.le: '<=',
            operator.lt: '<',
            operator.ge: '>=',
            operator.gt: '>',
            operator.and_: '&',
            rand_: '&',
            operator.or_: '|',
            ror_: '|',
            operator.xor: '^',
            rxor: '^',
            divmod: None,
            rdivmod: None}[op]


def _get_op_name(op, special):
    """
    Find the name to attach to this method according to conventions
    for special and non-special methods.

    Parameters
    ----------
    op : binary operator
    special : bool

    Returns
    -------
    op_name : str
    """
    opname = op.__name__.strip('_')
    if special:
        opname = '__{opname}__'.format(opname=opname)
    return opname


# -----------------------------------------------------------------------------
# Docstring Generation and Templates

_op_descriptions = {
    'add': {'op': '+',
            'desc': 'Addition',
            'reverse': 'radd'},
    'sub': {'op': '-',
            'desc': 'Subtraction',
            'reverse': 'rsub'},
    'mul': {'op': '*',
            'desc': 'Multiplication',
            'reverse': 'rmul'},
    'mod': {'op': '%',
            'desc': 'Modulo',
            'reverse': 'rmod'},
    'pow': {'op': '**',
            'desc': 'Exponential power',
            'reverse': 'rpow'},
    'truediv': {'op': '/',
                'desc': 'Floating division',
                'reverse': 'rtruediv'},
    'floordiv': {'op': '//',
                 'desc': 'Integer division',
                 'reverse': 'rfloordiv'},
    'divmod': {'op': 'divmod',
               'desc': 'Integer division and modulo',
               'reverse': None},

    'eq': {'op': '==',
                 'desc': 'Equal to',
                 'reverse': None},
    'ne': {'op': '!=',
                 'desc': 'Not equal to',
                 'reverse': None},
    'lt': {'op': '<',
                 'desc': 'Less than',
                 'reverse': None},
    'le': {'op': '<=',
                 'desc': 'Less than or equal to',
                 'reverse': None},
    'gt': {'op': '>',
                 'desc': 'Greater than',
                 'reverse': None},
    'ge': {'op': '>=',
                 'desc': 'Greater than or equal to',
                 'reverse': None}}

_op_names = list(_op_descriptions.keys())
for key in _op_names:
    _op_descriptions[key]['reversed'] = False
    reverse_op = _op_descriptions[key]['reverse']
    if reverse_op is not None:
        _op_descriptions[reverse_op] = _op_descriptions[key].copy()
        _op_descriptions[reverse_op]['reversed'] = True
        _op_descriptions[reverse_op]['reverse'] = key

_flex_doc_SERIES = """
{desc} of series and other, element-wise (binary operator `{op_name}`).

Equivalent to ``{equiv}``, but with support to substitute a fill_value for
missing data in one of the inputs.

Parameters
----------
other : Series or scalar value
fill_value : None or float value, default None (NaN)
    Fill missing (NaN) values with this value. If both Series are
    missing, the result will be missing
level : int or name
    Broadcast across a level, matching Index values on the
    passed MultiIndex level

Returns
-------
result : Series

See also
--------
Series.{reverse}
"""

_arith_doc_FRAME = """
Binary operator %s with support to substitute a fill_value for missing data in
one of the inputs

Parameters
----------
other : Series, DataFrame, or constant
axis : {0, 1, 'index', 'columns'}
    For Series input, axis to match Series index on
fill_value : None or float value, default None
    Fill missing (NaN) values with this value. If both DataFrame locations are
    missing, the result will be missing
level : int or name
    Broadcast across a level, matching Index values on the
    passed MultiIndex level

Notes
-----
Mismatched indices will be unioned together

Returns
-------
result : DataFrame
"""

_flex_doc_FRAME = """
{desc} of dataframe and other, element-wise (binary operator `{op_name}`).

Equivalent to ``{equiv}``, but with support to substitute a fill_value for
missing data in one of the inputs.

Parameters
----------
other : Series, DataFrame, or constant
axis : {{0, 1, 'index', 'columns'}}
    For Series input, axis to match Series index on
fill_value : None or float value, default None
    Fill missing (NaN) values with this value. If both DataFrame
    locations are missing, the result will be missing
level : int or name
    Broadcast across a level, matching Index values on the
    passed MultiIndex level

Notes
-----
Mismatched indices will be unioned together

Returns
-------
result : DataFrame

See also
--------
DataFrame.{reverse}
"""

_flex_doc_PANEL = """
{desc} of series and other, element-wise (binary operator `{op_name}`).
Equivalent to ``{equiv}``.

Parameters
----------
other : DataFrame or Panel
axis : {{items, major_axis, minor_axis}}
    Axis to broadcast over

Returns
-------
Panel

See also
--------
Panel.{reverse}
"""


_agg_doc_PANEL = """
Wrapper method for {op_name}

Parameters
----------
other : DataFrame or Panel
axis : {{items, major_axis, minor_axis}}
    Axis to broadcast over

Returns
-------
Panel
"""


def _make_flex_doc(op_name, typ):
    """
    Make the appropriate substitutions for the given operation and class-typ
    into either _flex_doc_SERIES or _flex_doc_FRAME to return the docstring
    to attach to a generated method.

    Parameters
    ----------
    op_name : str {'__add__', '__sub__', ... '__eq__', '__ne__', ...}
    typ : str {series, 'dataframe']}

    Returns
    -------
    doc : str
    """
    op_name = op_name.replace('__', '')
    op_desc = _op_descriptions[op_name]

    if op_desc['reversed']:
        equiv = 'other ' + op_desc['op'] + ' ' + typ
    else:
        equiv = typ + ' ' + op_desc['op'] + ' other'

    if typ == 'series':
        base_doc = _flex_doc_SERIES
    elif typ == 'dataframe':
        base_doc = _flex_doc_FRAME
    elif typ == 'panel':
        base_doc = _flex_doc_PANEL
    else:
        raise AssertionError('Invalid typ argument.')

    doc = base_doc.format(desc=op_desc['desc'], op_name=op_name,
                          equiv=equiv, reverse=op_desc['reverse'])
    return doc


# -----------------------------------------------------------------------------
# Masking NA values and fallbacks for operations numpy does not support

def fill_binop(left, right, fill_value):
    """
    If a non-None fill_value is given, replace null entries in left and right
    with this value, but only in positions where _one_ of left/right is null,
    not both.

    Parameters
    ----------
    left : array-like
    right : array-like
    fill_value : object

    Returns
    -------
    left : array-like
    right : array-like

    Notes
    -----
    Makes copies if fill_value is not None
    """
    # TODO: can we make a no-copy implementation?
    if fill_value is not None:
        left_mask = isna(left)
        right_mask = isna(right)
        left = left.copy()
        right = right.copy()

        # one but not both
        mask = left_mask ^ right_mask
        left[left_mask & mask] = fill_value
        right[right_mask & mask] = fill_value
    return left, right


def mask_cmp_op(x, y, op, allowed_types):
    """
    Apply the function `op` to only non-null points in x and y.

    Parameters
    ----------
    x : array-like
    y : array-like
    op : binary operation
    allowed_types : class or tuple of classes

    Returns
    -------
    result : ndarray[bool]
    """
    # TODO: Can we make the allowed_types arg unnecessary?
    xrav = x.ravel()
    result = np.empty(x.size, dtype=bool)
    if isinstance(y, allowed_types):
        yrav = y.ravel()
        mask = notna(xrav) & notna(yrav)
        result[mask] = op(np.array(list(xrav[mask])),
                          np.array(list(yrav[mask])))
    else:
        mask = notna(xrav)
        result[mask] = op(np.array(list(xrav[mask])), y)

    if op == operator.ne:  # pragma: no cover
        np.putmask(result, ~mask, True)
    else:
        np.putmask(result, ~mask, False)
    result = result.reshape(x.shape)
    return result


# -----------------------------------------------------------------------------
# Functions that add arithmetic methods to objects, given arithmetic factory
# methods


def _create_methods(cls, arith_method, comp_method, bool_method,
                    special=False):
    # creates actual methods based upon arithmetic, comp and bool method
    # constructors.

    have_divmod = issubclass(cls, ABCSeries)
    # divmod is available for Series and SparseSeries

    # yapf: disable
    new_methods = dict(
        add=arith_method(cls, operator.add, special),
        radd=arith_method(cls, radd, special),
        sub=arith_method(cls, operator.sub, special),
        mul=arith_method(cls, operator.mul, special),
        truediv=arith_method(cls, operator.truediv, special),
        floordiv=arith_method(cls, operator.floordiv, special),
        # Causes a floating point exception in the tests when numexpr enabled,
        # so for now no speedup
        mod=arith_method(cls, operator.mod, special),
        pow=arith_method(cls, operator.pow, special),
        # not entirely sure why this is necessary, but previously was included
        # so it's here to maintain compatibility
        rmul=arith_method(cls, rmul, special),
        rsub=arith_method(cls, rsub, special),
        rtruediv=arith_method(cls, rtruediv, special),
        rfloordiv=arith_method(cls, rfloordiv, special),
        rpow=arith_method(cls, rpow, special),
        rmod=arith_method(cls, rmod, special))
    # yapf: enable
    new_methods['div'] = new_methods['truediv']
    new_methods['rdiv'] = new_methods['rtruediv']

    # Comp methods never had a default axis set
    if comp_method:
        new_methods.update(dict(
            eq=comp_method(cls, operator.eq, special),
            ne=comp_method(cls, operator.ne, special),
            lt=comp_method(cls, operator.lt, special),
            gt=comp_method(cls, operator.gt, special),
            le=comp_method(cls, operator.le, special),
            ge=comp_method(cls, operator.ge, special)))
    if bool_method:
        new_methods.update(
            dict(and_=bool_method(cls, operator.and_, special),
                 or_=bool_method(cls, operator.or_, special),
                 # For some reason ``^`` wasn't used in original.
                 xor=bool_method(cls, operator.xor, special),
                 rand_=bool_method(cls, rand_, special),
                 ror_=bool_method(cls, ror_, special),
                 rxor=bool_method(cls, rxor, special)))
    if have_divmod:
        # divmod doesn't have an op that is supported by numexpr
        new_methods['divmod'] = arith_method(cls, divmod, special)

    if special:
        dunderize = lambda x: '__{name}__'.format(name=x.strip('_'))
    else:
        dunderize = lambda x: x
    new_methods = {dunderize(k): v for k, v in new_methods.items()}
    return new_methods


def add_methods(cls, new_methods):
    for name, method in new_methods.items():
        # For most methods, if we find that the class already has a method
        # of the same name, it is OK to over-write it.  The exception is
        # inplace methods (__iadd__, __isub__, ...) for SparseArray, which
        # retain the np.ndarray versions.
        force = not (issubclass(cls, ABCSparseArray) and
                     name.startswith('__i'))
        if force or name not in cls.__dict__:
            bind_method(cls, name, method)


# ----------------------------------------------------------------------
# Arithmetic
def add_special_arithmetic_methods(cls, arith_method=None,
                                   comp_method=None, bool_method=None):
    """
    Adds the full suite of special arithmetic methods (``__add__``,
    ``__sub__``, etc.) to the class.

    Parameters
    ----------
    arith_method : function (optional)
        factory for special arithmetic methods:
        f(cls, op, special)
    comp_method : function (optional)
        factory for rich comparison - signature: f(cls, op, special)
    bool_method : function (optional)
        factory for boolean methods - signature: f(cls, op, special)
    """
    new_methods = _create_methods(cls, arith_method, comp_method, bool_method,
                                  special=True)
    # inplace operators (I feel like these should get passed an `inplace=True`
    # or just be removed

    def _wrap_inplace_method(method):
        """
        return an inplace wrapper for this method
        """

        def f(self, other):
            result = method(self, other)

            # this makes sure that we are aligned like the input
            # we are updating inplace so we want to ignore is_copy
            self._update_inplace(result.reindex_like(self, copy=False)._data,
                                 verify_is_copy=False)

            return self

        return f

    new_methods.update(
        dict(__iadd__=_wrap_inplace_method(new_methods["__add__"]),
             __isub__=_wrap_inplace_method(new_methods["__sub__"]),
             __imul__=_wrap_inplace_method(new_methods["__mul__"]),
             __itruediv__=_wrap_inplace_method(new_methods["__truediv__"]),
             __ifloordiv__=_wrap_inplace_method(new_methods["__floordiv__"]),
             __imod__=_wrap_inplace_method(new_methods["__mod__"]),
             __ipow__=_wrap_inplace_method(new_methods["__pow__"])))
    if not compat.PY3:
        new_methods["__idiv__"] = _wrap_inplace_method(new_methods["__div__"])
    if bool_method:
        new_methods.update(
            dict(__iand__=_wrap_inplace_method(new_methods["__and__"]),
                 __ior__=_wrap_inplace_method(new_methods["__or__"]),
                 __ixor__=_wrap_inplace_method(new_methods["__xor__"])))

    add_methods(cls, new_methods=new_methods)


def add_flex_arithmetic_methods(cls, flex_arith_method, flex_comp_method=None):
    """
    Adds the full suite of flex arithmetic methods (``pow``, ``mul``, ``add``)
    to the class.

    Parameters
    ----------
    flex_arith_method : function
        factory for flex arithmetic methods:
        f(cls, op, special)
    flex_comp_method : function, optional,
        factory for rich comparison - signature: f(cls, op, special)
    """
    new_methods = _create_methods(cls, flex_arith_method,
                                  flex_comp_method, bool_method=None,
                                  special=False)
    new_methods.update(dict(multiply=new_methods['mul'],
                            subtract=new_methods['sub'],
                            divide=new_methods['div']))
    # opt out of bool flex methods for now
    assert not any(kname in new_methods for kname in ('ror_', 'rxor', 'rand_'))

    add_methods(cls, new_methods=new_methods)


# -----------------------------------------------------------------------------
# Series

def _align_method_SERIES(left, right, align_asobject=False):
    """ align lhs and rhs Series """

    # ToDo: Different from _align_method_FRAME, list, tuple and ndarray
    # are not coerced here
    # because Series has inconsistencies described in #13637

    if isinstance(right, ABCSeries):
        # avoid repeated alignment
        if not left.index.equals(right.index):

            if align_asobject:
                # to keep original value's dtype for bool ops
                left = left.astype(object)
                right = right.astype(object)

            left, right = left.align(right, copy=False)

    return left, right


def _construct_result(left, result, index, name, dtype):
    """
    If the raw op result has a non-None name (e.g. it is an Index object) and
    the name argument is None, then passing name to the constructor will
    not be enough; we still need to override the name attribute.
    """
    out = left._constructor(result, index=index, dtype=dtype)

    out.name = name
    return out


def _construct_divmod_result(left, result, index, name, dtype):
    """divmod returns a tuple of like indexed series instead of a single series.
    """
    constructor = left._constructor
    return (
        constructor(result[0], index=index, name=name, dtype=dtype),
        constructor(result[1], index=index, name=name, dtype=dtype),
    )


def _arith_method_SERIES(cls, op, special):
    """
    Wrapper function for Series arithmetic operations, to avoid
    code duplication.
    """
    str_rep = _get_opstr(op, cls)
    name = _get_op_name(op, special)
    eval_kwargs = _gen_eval_kwargs(name)
    fill_zeros = _gen_fill_zeros(name)
    construct_result = (_construct_divmod_result
                        if op is divmod else _construct_result)

    def na_op(x, y):
        import pandas.core.computation.expressions as expressions

        try:
            result = expressions.evaluate(op, str_rep, x, y, **eval_kwargs)
        except TypeError:
            if isinstance(y, (np.ndarray, ABCSeries, pd.Index)):
                dtype = find_common_type([x.dtype, y.dtype])
                result = np.empty(x.size, dtype=dtype)
                mask = notna(x) & notna(y)
                result[mask] = op(x[mask], com._values_from_object(y[mask]))
            else:
                assert isinstance(x, np.ndarray)
                result = np.empty(len(x), dtype=x.dtype)
                mask = notna(x)
                result[mask] = op(x[mask], y)

            result, changed = maybe_upcast_putmask(result, ~mask, np.nan)

        result = missing.fill_zeros(result, x, y, name, fill_zeros)
        return result

    def safe_na_op(lvalues, rvalues):
        try:
            with np.errstate(all='ignore'):
                return na_op(lvalues, rvalues)
        except Exception:
            if is_object_dtype(lvalues):
                return libalgos.arrmap_object(lvalues,
                                              lambda x: op(x, rvalues))
            raise

    def wrapper(left, right, name=name, na_op=na_op):

        if isinstance(right, ABCDataFrame):
            return NotImplemented

        left, right = _align_method_SERIES(left, right)
        res_name = _get_series_op_result_name(left, right)

        if is_datetime64_dtype(left) or is_datetime64tz_dtype(left):
            result = dispatch_to_index_op(op, left, right, pd.DatetimeIndex)
            return construct_result(left, result,
                                    index=left.index, name=res_name,
                                    dtype=result.dtype)

        elif is_timedelta64_dtype(left):
            result = dispatch_to_index_op(op, left, right, pd.TimedeltaIndex)
            return construct_result(left, result,
                                    index=left.index, name=res_name,
                                    dtype=result.dtype)

        elif is_categorical_dtype(left):
            raise TypeError("{typ} cannot perform the operation "
                            "{op}".format(typ=type(left).__name__, op=str_rep))

        lvalues = left.values
        rvalues = right
        if isinstance(rvalues, ABCSeries):
            rvalues = rvalues.values

        result = safe_na_op(lvalues, rvalues)
        return construct_result(left, result,
                                index=left.index, name=res_name, dtype=None)

    return wrapper


def dispatch_to_index_op(op, left, right, index_class):
    """
    Wrap Series left in the given index_class to delegate the operation op
    to the index implementation.  DatetimeIndex and TimedeltaIndex perform
    type checking, timezone handling, overflow checks, etc.

    Parameters
    ----------
    op : binary operator (operator.add, operator.sub, ...)
    left : Series
    right : object
    index_class : DatetimeIndex or TimedeltaIndex

    Returns
    -------
    result : object, usually DatetimeIndex, TimedeltaIndex, or Series
    """
    left_idx = index_class(left)

    # avoid accidentally allowing integer add/sub.  For datetime64[tz] dtypes,
    # left_idx may inherit a freq from a cached DatetimeIndex.
    # See discussion in GH#19147.
    if getattr(left_idx, 'freq', None) is not None:
        left_idx = left_idx._shallow_copy(freq=None)
    try:
        result = op(left_idx, right)
    except NullFrequencyError:
        # DatetimeIndex and TimedeltaIndex with freq == None raise ValueError
        # on add/sub of integers (or int-like).  We re-raise as a TypeError.
        raise TypeError('incompatible type for a datetime/timedelta '
                        'operation [{name}]'.format(name=op.__name__))
    return result


def _get_series_op_result_name(left, right):
    # `left` is always a pd.Series
    if isinstance(right, (ABCSeries, pd.Index)):
        name = com._maybe_match_name(left, right)
    else:
        name = left.name
    return name


def _comp_method_OBJECT_ARRAY(op, x, y):
    if isinstance(y, list):
        y = construct_1d_object_array_from_listlike(y)
    if isinstance(y, (np.ndarray, ABCSeries, ABCIndex)):
        if not is_object_dtype(y.dtype):
            y = y.astype(np.object_)

        if isinstance(y, (ABCSeries, ABCIndex)):
            y = y.values

        result = lib.vec_compare(x, y, op)
    else:
        result = lib.scalar_compare(x, y, op)
    return result


def _comp_method_SERIES(cls, op, special):
    """
    Wrapper function for Series arithmetic operations, to avoid
    code duplication.
    """
    name = _get_op_name(op, special)
    masker = _gen_eval_kwargs(name).get('masker', False)

    def na_op(x, y):

        # dispatch to the categorical if we have a categorical
        # in either operand
        if is_categorical_dtype(y) and not is_scalar(y):
            # The `not is_scalar(y)` check excludes the string "category"
            return op(y, x)

        elif is_object_dtype(x.dtype):
            result = _comp_method_OBJECT_ARRAY(op, x, y)

        elif is_datetimelike_v_numeric(x, y):
            raise TypeError("invalid type comparison")

        else:

            # we want to compare like types
            # we only want to convert to integer like if
            # we are not NotImplemented, otherwise
            # we would allow datetime64 (but viewed as i8) against
            # integer comparisons

            # we have a datetime/timedelta and may need to convert
            mask = None
            if (needs_i8_conversion(x) or
                    (not is_scalar(y) and needs_i8_conversion(y))):

                if is_scalar(y):
                    mask = isna(x)
                    y = libindex.convert_scalar(x, com._values_from_object(y))
                else:
                    mask = isna(x) | isna(y)
                    y = y.view('i8')
                x = x.view('i8')

            try:
                with np.errstate(all='ignore'):
                    result = getattr(x, name)(y)
                if result is NotImplemented:
                    raise TypeError("invalid type comparison")
            except AttributeError:
                result = op(x, y)

            if mask is not None and mask.any():
                result[mask] = masker

        return result

    def wrapper(self, other, axis=None):
        # Validate the axis parameter
        if axis is not None:
            self._get_axis_number(axis)

        res_name = _get_series_op_result_name(self, other)

        if isinstance(other, ABCDataFrame):  # pragma: no cover
            # Defer to DataFrame implementation; fail early
            return NotImplemented

        elif isinstance(other, ABCSeries) and not self._indexed_same(other):
            raise ValueError("Can only compare identically-labeled "
                             "Series objects")

        elif is_categorical_dtype(self):
            # Dispatch to Categorical implementation; pd.CategoricalIndex
            # behavior is non-canonical GH#19513
            res_values = dispatch_to_index_op(op, self, other, pd.Categorical)
            return self._constructor(res_values, index=self.index,
                                     name=res_name)

        elif is_timedelta64_dtype(self):
            res_values = dispatch_to_index_op(op, self, other,
                                              pd.TimedeltaIndex)
            return self._constructor(res_values, index=self.index,
                                     name=res_name)

        elif isinstance(other, ABCSeries):
            # By this point we have checked that self._indexed_same(other)
            res_values = na_op(self.values, other.values)
            # rename is needed in case res_name is None and res_values.name
            # is not.
            return self._constructor(res_values, index=self.index,
                                     name=res_name).rename(res_name)

        elif isinstance(other, (np.ndarray, pd.Index)):
            # do not check length of zerodim array
            # as it will broadcast
            if (not is_scalar(lib.item_from_zerodim(other)) and
                    len(self) != len(other)):
                raise ValueError('Lengths must match to compare')

            res_values = na_op(self.values, np.asarray(other))
            result = self._constructor(res_values, index=self.index)
            # rename is needed in case res_name is None and self.name
            # is not.
            return result.__finalize__(self).rename(res_name)

        elif isinstance(other, pd.Categorical):
            # ordering of checks matters; by this point we know
            # that not is_categorical_dtype(self)
            res_values = op(self.values, other)
            return self._constructor(res_values, index=self.index,
                                     name=res_name)

        elif is_scalar(other) and isna(other):
            # numpy does not like comparisons vs None
            if op is operator.ne:
                res_values = np.ones(len(self), dtype=bool)
            else:
                res_values = np.zeros(len(self), dtype=bool)
            return self._constructor(res_values, index=self.index,
                                     name=self.name, dtype='bool')

        else:
            values = self.get_values()
            if isinstance(other, list):
                other = np.asarray(other)

            with np.errstate(all='ignore'):
                res = na_op(values, other)
            if is_scalar(res):
                raise TypeError('Could not compare {typ} type with Series'
                                .format(typ=type(other)))

            # always return a full value series here
            res_values = com._values_from_object(res)
            return pd.Series(res_values, index=self.index,
                             name=res_name, dtype='bool')

    return wrapper


def _bool_method_SERIES(cls, op, special):
    """
    Wrapper function for Series arithmetic operations, to avoid
    code duplication.
    """

    def na_op(x, y):
        try:
            result = op(x, y)
        except TypeError:
            if isinstance(y, list):
                y = construct_1d_object_array_from_listlike(y)

            if isinstance(y, (np.ndarray, ABCSeries)):
                if (is_bool_dtype(x.dtype) and is_bool_dtype(y.dtype)):
                    result = op(x, y)  # when would this be hit?
                else:
                    x = _ensure_object(x)
                    y = _ensure_object(y)
                    result = lib.vec_binop(x, y, op)
            else:
                # let null fall thru
                if not isna(y):
                    y = bool(y)
                try:
                    result = lib.scalar_binop(x, y, op)
                except:
                    raise TypeError("cannot compare a dtyped [{dtype}] array "
                                    "with a scalar of type [{typ}]"
                                    .format(dtype=x.dtype,
                                            typ=type(y).__name__))

        return result

    fill_int = lambda x: x.fillna(0)
    fill_bool = lambda x: x.fillna(False).astype(bool)

    def wrapper(self, other):
        is_self_int_dtype = is_integer_dtype(self.dtype)

        self, other = _align_method_SERIES(self, other, align_asobject=True)

        if isinstance(other, ABCDataFrame):
            # Defer to DataFrame implementation; fail early
            return NotImplemented

        elif isinstance(other, ABCSeries):
            name = com._maybe_match_name(self, other)
            is_other_int_dtype = is_integer_dtype(other.dtype)
            other = fill_int(other) if is_other_int_dtype else fill_bool(other)

            filler = (fill_int if is_self_int_dtype and is_other_int_dtype
                      else fill_bool)

            res_values = na_op(self.values, other.values)
            unfilled = self._constructor(res_values,
                                         index=self.index, name=name)
            return filler(unfilled)

        else:
            # scalars, list, tuple, np.array
            filler = (fill_int if is_self_int_dtype and
                      is_integer_dtype(np.asarray(other)) else fill_bool)

            res_values = na_op(self.values, other)
            unfilled = self._constructor(res_values, index=self.index)
            return filler(unfilled).__finalize__(self)

    return wrapper


def _flex_method_SERIES(cls, op, special):
    name = _get_op_name(op, special)
    doc = _make_flex_doc(name, 'series')

    @Appender(doc)
    def flex_wrapper(self, other, level=None, fill_value=None, axis=0):
        # validate axis
        if axis is not None:
            self._get_axis_number(axis)
        if isinstance(other, ABCSeries):
            return self._binop(other, op, level=level, fill_value=fill_value)
        elif isinstance(other, (np.ndarray, list, tuple)):
            if len(other) != len(self):
                raise ValueError('Lengths must be equal')
            other = self._constructor(other, self.index)
            return self._binop(other, op, level=level, fill_value=fill_value)
        else:
            if fill_value is not None:
                self = self.fillna(fill_value)

            return self._constructor(op(self, other),
                                     self.index).__finalize__(self)

    flex_wrapper.__name__ = name
    return flex_wrapper


series_flex_funcs = dict(flex_arith_method=_flex_method_SERIES,
                         flex_comp_method=_flex_method_SERIES)

series_special_funcs = dict(arith_method=_arith_method_SERIES,
                            comp_method=_comp_method_SERIES,
                            bool_method=_bool_method_SERIES)


# -----------------------------------------------------------------------------
# DataFrame

def _combine_series_frame(self, other, func, fill_value=None, axis=None,
                          level=None, try_cast=True):
    """
    Apply binary operator `func` to self, other using alignment and fill
    conventions determined by the fill_value, axis, level, and try_cast kwargs.

    Parameters
    ----------
    self : DataFrame
    other : Series
    func : binary operator
    fill_value : object, default None
    axis : {0, 1, 'columns', 'index', None}, default None
    level : int or None, default None
    try_cast : bool, default True

    Returns
    -------
    result : DataFrame
    """
    if fill_value is not None:
        raise NotImplementedError("fill_value {fill} not supported."
                                  .format(fill=fill_value))

    if axis is not None:
        axis = self._get_axis_number(axis)
        if axis == 0:
            return self._combine_match_index(other, func, level=level)
        else:
            return self._combine_match_columns(other, func, level=level,
                                               try_cast=try_cast)
    else:
        if not len(other):
            return self * np.nan

        if not len(self):
            # Ambiguous case, use _series so works with DataFrame
            return self._constructor(data=self._series, index=self.index,
                                     columns=self.columns)

        # default axis is columns
        return self._combine_match_columns(other, func, level=level,
                                           try_cast=try_cast)


def _align_method_FRAME(left, right, axis):
    """ convert rhs to meet lhs dims if input is list, tuple or np.ndarray """

    def to_series(right):
        msg = ('Unable to coerce to Series, length must be {req_len}: '
               'given {given_len}')
        if axis is not None and left._get_axis_name(axis) == 'index':
            if len(left.index) != len(right):
                raise ValueError(msg.format(req_len=len(left.index),
                                            given_len=len(right)))
            right = left._constructor_sliced(right, index=left.index)
        else:
            if len(left.columns) != len(right):
                raise ValueError(msg.format(req_len=len(left.columns),
                                            given_len=len(right)))
            right = left._constructor_sliced(right, index=left.columns)
        return right

    if isinstance(right, np.ndarray):

        if right.ndim == 1:
            right = to_series(right)

        elif right.ndim == 2:
            if left.shape != right.shape:
                raise ValueError("Unable to coerce to DataFrame, shape "
                                 "must be {req_shape}: given {given_shape}"
                                 .format(req_shape=left.shape,
                                         given_shape=right.shape))

            right = left._constructor(right, index=left.index,
                                      columns=left.columns)
        elif right.ndim > 2:
            raise ValueError('Unable to coerce to Series/DataFrame, dim '
                             'must be <= 2: {dim}'.format(dim=right.shape))

    elif (is_list_like(right) and
          not isinstance(right, (ABCSeries, ABCDataFrame))):
        # GH17901
        right = to_series(right)

    return right


def _arith_method_FRAME(cls, op, special):
    str_rep = _get_opstr(op, cls)
    name = _get_op_name(op, special)
    eval_kwargs = _gen_eval_kwargs(name)
    fill_zeros = _gen_fill_zeros(name)
    default_axis = _get_frame_op_default_axis(name)

    def na_op(x, y):
        import pandas.core.computation.expressions as expressions

        try:
            result = expressions.evaluate(op, str_rep, x, y, **eval_kwargs)
        except TypeError:
            xrav = x.ravel()
            if isinstance(y, (np.ndarray, ABCSeries)):
                dtype = np.find_common_type([x.dtype, y.dtype], [])
                result = np.empty(x.size, dtype=dtype)
                yrav = y.ravel()
                mask = notna(xrav) & notna(yrav)
                xrav = xrav[mask]

                if yrav.shape != mask.shape:
                    # FIXME: GH#5284, GH#5035, GH#19448
                    # Without specifically raising here we get mismatched
                    # errors in Py3 (TypeError) vs Py2 (ValueError)
                    raise ValueError('Cannot broadcast operands together.')

                yrav = yrav[mask]
                if xrav.size:
                    with np.errstate(all='ignore'):
                        result[mask] = op(xrav, yrav)

            elif isinstance(x, np.ndarray):
                # mask is only meaningful for x
                result = np.empty(x.size, dtype=x.dtype)
                mask = notna(xrav)
                xrav = xrav[mask]
                if xrav.size:
                    with np.errstate(all='ignore'):
                        result[mask] = op(xrav, y)
            else:
                raise TypeError("cannot perform operation {op} between "
                                "objects of type {x} and {y}"
                                .format(op=name, x=type(x), y=type(y)))

            result, changed = maybe_upcast_putmask(result, ~mask, np.nan)
            result = result.reshape(x.shape)

        result = missing.fill_zeros(result, x, y, name, fill_zeros)

        return result

    if name in _op_descriptions:
        # i.e. include "add" but not "__add__"
        doc = _make_flex_doc(name, 'dataframe')
    else:
        doc = _arith_doc_FRAME % name

    @Appender(doc)
    def f(self, other, axis=default_axis, level=None, fill_value=None):

        other = _align_method_FRAME(self, other, axis)

        if isinstance(other, ABCDataFrame):  # Another DataFrame
            return self._combine_frame(other, na_op, fill_value, level)
        elif isinstance(other, ABCSeries):
            return _combine_series_frame(self, other, na_op,
                                         fill_value=fill_value, axis=axis,
                                         level=level, try_cast=True)
        else:
            if fill_value is not None:
                self = self.fillna(fill_value)

            return self._combine_const(other, na_op, try_cast=True)

    f.__name__ = name

    return f


def _flex_comp_method_FRAME(cls, op, special):
    str_rep = _get_opstr(op, cls)
    name = _get_op_name(op, special)
    default_axis = _get_frame_op_default_axis(name)

    def na_op(x, y):
        try:
            with np.errstate(invalid='ignore'):
                result = op(x, y)
        except TypeError:
            result = mask_cmp_op(x, y, op, (np.ndarray, ABCSeries))
        return result

    @Appender('Wrapper for flexible comparison methods {name}'
              .format(name=name))
    def f(self, other, axis=default_axis, level=None):

        other = _align_method_FRAME(self, other, axis)

        if isinstance(other, ABCDataFrame):
            # Another DataFrame
            if not self._indexed_same(other):
                self, other = self.align(other, 'outer',
                                         level=level, copy=False)
            return self._compare_frame(other, na_op, str_rep)

        elif isinstance(other, ABCSeries):
            return _combine_series_frame(self, other, na_op,
                                         fill_value=None, axis=axis,
                                         level=level, try_cast=False)
        else:
            return self._combine_const(other, na_op, try_cast=False)

    f.__name__ = name

    return f


def _comp_method_FRAME(cls, func, special):
    str_rep = _get_opstr(func, cls)
    name = _get_op_name(func, special)

    @Appender('Wrapper for comparison method {name}'.format(name=name))
    def f(self, other):
        if isinstance(other, ABCDataFrame):
            # Another DataFrame
            if not self._indexed_same(other):
                raise ValueError('Can only compare identically-labeled '
                                 'DataFrame objects')
            return self._compare_frame(other, func, str_rep)

        elif isinstance(other, ABCSeries):
            return _combine_series_frame(self, other, func,
                                         fill_value=None, axis=None,
                                         level=None, try_cast=False)
        else:

            # straight boolean comparisons we want to allow all columns
            # (regardless of dtype to pass thru) See #4537 for discussion.
            res = self._combine_const(other, func,
                                      errors='ignore',
                                      try_cast=False)
            return res.fillna(True).astype(bool)

    f.__name__ = name

    return f


frame_flex_funcs = dict(flex_arith_method=_arith_method_FRAME,
                        flex_comp_method=_flex_comp_method_FRAME)

frame_special_funcs = dict(arith_method=_arith_method_FRAME,
                           comp_method=_comp_method_FRAME,
                           bool_method=_arith_method_FRAME)


# -----------------------------------------------------------------------------
# Panel

def _arith_method_PANEL(cls, op, special):
    # work only for scalars
    name = _get_op_name(op, special)

    def f(self, other):
        if not is_scalar(other):
            raise ValueError('Simple arithmetic with {name} can only be '
                             'done with scalar values'
                             .format(name=self._constructor.__name__))

        return self._combine(other, op)

    f.__name__ = name
    return f


def _comp_method_PANEL(cls, op, special):
    str_rep = _get_opstr(op, cls)
    name = _get_op_name(op, special)

    def na_op(x, y):
        import pandas.core.computation.expressions as expressions

        try:
            result = expressions.evaluate(op, str_rep, x, y)
        except TypeError:
            result = mask_cmp_op(x, y, op, np.ndarray)
        return result

    @Appender('Wrapper for comparison method {name}'.format(name=name))
    def f(self, other, axis=None):
        # Validate the axis parameter
        if axis is not None:
            axis = self._get_axis_number(axis)

        if isinstance(other, self._constructor):
            return self._compare_constructor(other, na_op, try_cast=False)
        elif isinstance(other, (self._constructor_sliced, ABCDataFrame,
                                ABCSeries)):
            raise Exception("input needs alignment for this object [{object}]"
                            .format(object=self._constructor))
        else:
            return self._combine_const(other, na_op, try_cast=False)

    f.__name__ = name

    return f


def _flex_method_PANEL(cls, op, special):
    str_rep = _get_opstr(op, cls)
    name = _get_op_name(op, special)
    eval_kwargs = _gen_eval_kwargs(name)
    fill_zeros = _gen_fill_zeros(name)

    def na_op(x, y):
        import pandas.core.computation.expressions as expressions

        try:
            result = expressions.evaluate(op, str_rep, x, y,
                                          errors='raise',
                                          **eval_kwargs)
        except TypeError:
            result = op(x, y)

        # handles discrepancy between numpy and numexpr on division/mod
        # by 0 though, given that these are generally (always?)
        # non-scalars, I'm not sure whether it's worth it at the moment
        result = missing.fill_zeros(result, x, y, name, fill_zeros)
        return result

    if name in _op_descriptions:
        doc = _make_flex_doc(name, 'panel')
    else:
        # doc strings substitors
        doc = _agg_doc_PANEL.format(op_name=name)

    @Appender(doc)
    def f(self, other, axis=0):
        return self._combine(other, na_op, axis=axis)

    f.__name__ = name
    return f


panel_special_funcs = dict(arith_method=_arith_method_PANEL,
                           comp_method=_comp_method_PANEL,
                           bool_method=_arith_method_PANEL)

panel_flex_funcs = dict(flex_arith_method=_flex_method_PANEL,
                        flex_comp_method=_comp_method_PANEL)

# -----------------------------------------------------------------------------
# Sparse


def _arith_method_SPARSE_SERIES(cls, op, special):
    """
    Wrapper function for Series arithmetic operations, to avoid
    code duplication.
    """
    name = _get_op_name(op, special)

    def wrapper(self, other):
        if isinstance(other, ABCDataFrame):
            return NotImplemented
        elif isinstance(other, ABCSeries):
            if not isinstance(other, ABCSparseSeries):
                other = other.to_sparse(fill_value=self.fill_value)
            return _sparse_series_op(self, other, op, name)
        elif is_scalar(other):
            with np.errstate(all='ignore'):
                new_values = op(self.values, other)
            return self._constructor(new_values,
                                     index=self.index,
                                     name=self.name)
        else:  # pragma: no cover
            raise TypeError('operation with {other} not supported'
                            .format(other=type(other)))

    wrapper.__name__ = name
    return wrapper


def _sparse_series_op(left, right, op, name):
    left, right = left.align(right, join='outer', copy=False)
    new_index = left.index
    new_name = com._maybe_match_name(left, right)

    from pandas.core.sparse.array import _sparse_array_op
    result = _sparse_array_op(left.values, right.values, op, name,
                              series=True)
    return left._constructor(result, index=new_index, name=new_name)


def _arith_method_SPARSE_ARRAY(cls, op, special):
    """
    Wrapper function for Series arithmetic operations, to avoid
    code duplication.
    """
    name = _get_op_name(op, special)

    def wrapper(self, other):
        from pandas.core.sparse.array import (
            SparseArray, _sparse_array_op, _wrap_result, _get_fill)
        if isinstance(other, np.ndarray):
            if len(self) != len(other):
                raise AssertionError("length mismatch: {self} vs. {other}"
                                     .format(self=len(self), other=len(other)))
            if not isinstance(other, SparseArray):
                dtype = getattr(other, 'dtype', None)
                other = SparseArray(other, fill_value=self.fill_value,
                                    dtype=dtype)
            return _sparse_array_op(self, other, op, name, series=False)
        elif is_scalar(other):
            with np.errstate(all='ignore'):
                fill = op(_get_fill(self), np.asarray(other))
                result = op(self.sp_values, other)

            return _wrap_result(name, result, self.sp_index, fill)
        else:  # pragma: no cover
            raise TypeError('operation with {other} not supported'
                            .format(other=type(other)))

    wrapper.__name__ = name
    return wrapper


sparse_array_special_funcs = dict(arith_method=_arith_method_SPARSE_ARRAY,
                                  comp_method=_arith_method_SPARSE_ARRAY,
                                  bool_method=_arith_method_SPARSE_ARRAY)

sparse_series_special_funcs = dict(arith_method=_arith_method_SPARSE_SERIES,
                                   comp_method=_arith_method_SPARSE_SERIES,
                                   bool_method=_bool_method_SERIES)
# TODO: I don't think the functions defined by bool_method are tested
