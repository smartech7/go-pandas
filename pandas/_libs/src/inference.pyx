import sys
from decimal import Decimal
cimport util
cimport cython
from tslib import NaT, get_timezone
from datetime import datetime, timedelta
iNaT = util.get_nat()

cdef bint PY2 = sys.version_info[0] == 2

from util cimport (UINT8_MAX, UINT16_MAX, UINT32_MAX, UINT64_MAX,
                   INT8_MIN, INT8_MAX, INT16_MIN, INT16_MAX,
                   INT32_MAX, INT32_MIN, INT64_MAX, INT64_MIN)

# core.common import for fast inference checks

cpdef bint is_float(object obj):
    return util.is_float_object(obj)


cpdef bint is_integer(object obj):
    return util.is_integer_object(obj)


cpdef bint is_bool(object obj):
    return util.is_bool_object(obj)


cpdef bint is_complex(object obj):
    return util.is_complex_object(obj)


cpdef bint is_decimal(object obj):
    return isinstance(obj, Decimal)


cpdef bint is_interval(object obj):
    return isinstance(obj, Interval)


cpdef bint is_period(object val):
    """ Return a boolean if this is a Period object """
    return util.is_period_object(val)


_TYPE_MAP = {
    'categorical': 'categorical',
    'category': 'categorical',
    'int8': 'integer',
    'int16': 'integer',
    'int32': 'integer',
    'int64': 'integer',
    'i': 'integer',
    'uint8': 'integer',
    'uint16': 'integer',
    'uint32': 'integer',
    'uint64': 'integer',
    'u': 'integer',
    'float32': 'floating',
    'float64': 'floating',
    'f': 'floating',
    'complex128': 'complex',
    'c': 'complex',
    'string': 'string' if PY2 else 'bytes',
    'S': 'string' if PY2 else 'bytes',
    'unicode': 'unicode' if PY2 else 'string',
    'U': 'unicode' if PY2 else 'string',
    'bool': 'boolean',
    'b': 'boolean',
    'datetime64[ns]': 'datetime64',
    'M': 'datetime64',
    'timedelta64[ns]': 'timedelta64',
    'm': 'timedelta64',
}

# types only exist on certain platform
try:
    np.float128
    _TYPE_MAP['float128'] = 'floating'
except AttributeError:
    pass
try:
    np.complex256
    _TYPE_MAP['complex256'] = 'complex'
except AttributeError:
    pass
try:
    np.float16
    _TYPE_MAP['float16'] = 'floating'
except AttributeError:
    pass


cdef class Seen(object):
    """
    Class for keeping track of the types of elements
    encountered when trying to perform type conversions.
    """

    cdef:
        bint int_             # seen_int
        bint bool_            # seen_bool
        bint null_            # seen_null
        bint uint_            # seen_uint (unsigned integer)
        bint sint_            # seen_sint (signed integer)
        bint float_           # seen_float
        bint object_          # seen_object
        bint complex_         # seen_complex
        bint datetime_        # seen_datetime
        bint coerce_numeric   # coerce data to numeric
        bint timedelta_       # seen_timedelta
        bint datetimetz_      # seen_datetimetz

    def __cinit__(self, bint coerce_numeric=0):
        """
        Initialize a Seen instance.

        Parameters
        ----------
        coerce_numeric : bint, default 0
            Whether or not to force conversion to a numeric data type if
            initial methods to convert to numeric fail.
        """
        self.int_ = 0
        self.bool_ = 0
        self.null_ = 0
        self.uint_ = 0
        self.sint_ = 0
        self.float_ = 0
        self.object_ = 0
        self.complex_ = 0
        self.datetime_ = 0
        self.timedelta_ = 0
        self.datetimetz_ = 0
        self.coerce_numeric = coerce_numeric

    cdef inline bint check_uint64_conflict(self) except -1:
        """
        Check whether we can safely convert a uint64 array to a numeric dtype.

        There are two cases when conversion to numeric dtype with a uint64
        array is not safe (and will therefore not be performed)

        1) A NaN element is encountered.

           uint64 cannot be safely cast to float64 due to truncation issues
           at the extreme ends of the range.

        2) A negative number is encountered.

           There is no numerical dtype that can hold both negative numbers
           and numbers greater than INT64_MAX. Hence, at least one number
           will be improperly cast if we convert to a numeric dtype.

        Returns
        -------
        return_values : bool
            Whether or not we should return the original input array to avoid
            data truncation.

        Raises
        ------
        ValueError : uint64 elements were detected, and at least one of the
                     two conflict cases was also detected. However, we are
                     trying to force conversion to a numeric dtype.
        """
        if self.uint_ and (self.null_ or self.sint_):
            if not self.coerce_numeric:
                return True

            if self.null_:
                msg = ("uint64 array detected, and such an "
                       "array cannot contain NaN.")
            else:  # self.sint_ = 1
                msg = ("uint64 and negative values detected. "
                       "Cannot safely return a numeric array "
                       "without truncating data.")

            raise ValueError(msg)
        return False

    cdef inline saw_null(self):
        """
        Set flags indicating that a null value was encountered.
        """
        self.null_ = 1
        self.float_ = 1

    cdef saw_int(self, object val):
        """
        Set flags indicating that an integer value was encountered.

        Parameters
        ----------
        val : Python int
            Value with which to set the flags.
        """
        self.int_ = 1
        self.sint_ = self.sint_ or (val < 0)
        self.uint_ = self.uint_ or (val > oINT64_MAX)

    @property
    def numeric_(self):
        return self.complex_ or self.float_ or self.int_

    @property
    def is_bool(self):
        return not (self.datetime_ or self.numeric_ or self.timedelta_)

    @property
    def is_float_or_complex(self):
        return not (self.bool_ or self.datetime_ or self.timedelta_)


cdef _try_infer_map(v):
    """ if its in our map, just return the dtype """
    cdef:
        object attr, val
    for attr in ['name', 'kind', 'base']:
        val = getattr(v.dtype, attr)
        if val in _TYPE_MAP:
            return _TYPE_MAP[val]
    return None


def infer_dtype(object value, bint skipna=False):
    """
    Effeciently infer the type of a passed val, or list-like
    array of values. Return a string describing the type.

    Parameters
    ----------
    value : scalar, list, ndarray, or pandas type
    skipna : bool, default False
        Ignore NaN values when inferring the type. The default of ``False``
        will be deprecated in a later version of pandas.

        .. versionadded:: 0.21.0

    Returns
    -------
    string describing the common type of the input data.
    Results can include:

    - string
    - unicode
    - bytes
    - floating
    - integer
    - mixed-integer
    - mixed-integer-float
    - decimal
    - complex
    - categorical
    - boolean
    - datetime64
    - datetime
    - date
    - timedelta64
    - timedelta
    - time
    - period
    - mixed

    Raises
    ------
    TypeError if ndarray-like but cannot infer the dtype

    Notes
    -----
    - 'mixed' is the catchall for anything that is not otherwise
      specialized
    - 'mixed-integer-float' are floats and integers
    - 'mixed-integer' are integers mixed with non-integers

    Examples
    --------
    >>> infer_dtype(['foo', 'bar'])
    'string'

    >>> infer_dtype(['a', np.nan, 'b'], skipna=True)
    'string'

    >>> infer_dtype(['a', np.nan, 'b'], skipna=False)
    'mixed'

    >>> infer_dtype([b'foo', b'bar'])
    'bytes'

    >>> infer_dtype([1, 2, 3])
    'integer'

    >>> infer_dtype([1, 2, 3.5])
    'mixed-integer-float'

    >>> infer_dtype([1.0, 2.0, 3.5])
    'floating'

    >>> infer_dtype(['a', 1])
    'mixed-integer'

    >>> infer_dtype([Decimal(1), Decimal(2.0)])
    'decimal'

    >>> infer_dtype([True, False])
    'boolean'

    >>> infer_dtype([True, False, np.nan])
    'mixed'

    >>> infer_dtype([pd.Timestamp('20130101')])
    'datetime'

    >>> infer_dtype([datetime.date(2013, 1, 1)])
    'date'

    >>> infer_dtype([np.datetime64('2013-01-01')])
    'datetime64'

    >>> infer_dtype([datetime.timedelta(0, 1, 1)])
    'timedelta'

    >>> infer_dtype(pd.Series(list('aabc')).astype('category'))
    'categorical'
    """
    cdef:
        Py_ssize_t i, n
        object val
        ndarray values
        bint seen_pdnat = False
        bint seen_val = False

    if isinstance(value, np.ndarray):
        values = value
    elif hasattr(value, 'dtype'):

        # this will handle ndarray-like
        # e.g. categoricals
        try:
            values = getattr(value, '_values', getattr(
                value, 'values', value))
        except:
            value = _try_infer_map(value)
            if value is not None:
                return value

            # its ndarray like but we can't handle
            raise ValueError("cannot infer type for {0}".format(type(value)))

    else:
        if not isinstance(value, list):
            value = list(value)
        values = list_to_object_array(value)

    values = getattr(values, 'values', values)
    val = _try_infer_map(values)
    if val is not None:
        return val

    if values.dtype != np.object_:
        values = values.astype('O')

    n = len(values)
    if n == 0:
        return 'empty'

    # make contiguous
    values = values.ravel()

    # try to use a valid value
    for i in range(n):
        val = util.get_value_1d(values, i)

        # do not use is_nul_datetimelike to keep
        # np.datetime64('nat') and np.timedelta64('nat')
        if util._checknull(val):
            pass
        elif val is NaT:
            seen_pdnat = True
        else:
            seen_val = True
            break

    # if all values are nan/NaT
    if seen_val is False and seen_pdnat is True:
        return 'datetime'
        # float/object nan is handled in latter logic

    if util.is_datetime64_object(val):
        if is_datetime64_array(values):
            return 'datetime64'
        elif is_timedelta_or_timedelta64_array(values):
            return 'timedelta'

    elif is_timedelta(val):
        if is_timedelta_or_timedelta64_array(values):
            return 'timedelta'

    elif util.is_integer_object(val):
        # a timedelta will show true here as well
        if is_timedelta(val):
            if is_timedelta_or_timedelta64_array(values):
                return 'timedelta'

        if is_integer_array(values):
            return 'integer'
        elif is_integer_float_array(values):
            return 'mixed-integer-float'
        elif is_timedelta_or_timedelta64_array(values):
            return 'timedelta'
        return 'mixed-integer'

    elif is_datetime(val):
        if is_datetime_array(values):
            return 'datetime'

    elif is_date(val):
        if is_date_array(values, skipna=skipna):
            return 'date'

    elif is_time(val):
        if is_time_array(values, skipna=skipna):
            return 'time'

    elif is_decimal(val):
        return 'decimal'

    elif util.is_float_object(val):
        if is_float_array(values):
            return 'floating'
        elif is_integer_float_array(values):
            return 'mixed-integer-float'

    elif util.is_bool_object(val):
        if is_bool_array(values, skipna=skipna):
            return 'boolean'

    elif PyString_Check(val):
        if is_string_array(values, skipna=skipna):
            return 'string'

    elif PyUnicode_Check(val):
        if is_unicode_array(values, skipna=skipna):
            return 'unicode'

    elif PyBytes_Check(val):
        if is_bytes_array(values, skipna=skipna):
            return 'bytes'

    elif is_period(val):
        if is_period_array(values):
            return 'period'

    elif is_interval(val):
        if is_interval_array(values):
            return 'interval'

    for i in range(n):
        val = util.get_value_1d(values, i)
        if (util.is_integer_object(val) and
            not util.is_timedelta64_object(val) and
            not util.is_datetime64_object(val)):
            return 'mixed-integer'

    return 'mixed'


cpdef object infer_datetimelike_array(object arr):
    """
    infer if we have a datetime or timedelta array
    - date: we have *only* date and maybe strings, nulls
    - datetime: we have *only* datetimes and maybe strings, nulls
    - timedelta: we have *only* timedeltas and maybe strings, nulls
    - nat: we do not have *any* date, datetimes or timedeltas, but do have
      at least a NaT
    - mixed: other objects (strings or actual objects)

    Parameters
    ----------
    arr : object array

    Returns
    -------
    string: {datetime, timedelta, date, nat, mixed}

    """

    cdef:
        Py_ssize_t i, n = len(arr)
        bint seen_timedelta = 0, seen_date = 0, seen_datetime = 0
        bint seen_nat = 0
        list objs = []
        object v

    for i in range(n):
        v = arr[i]
        if util.is_string_object(v):
            objs.append(v)

            if len(objs) == 3:
                break

        elif util._checknull(v):
            # nan or None
            pass
        elif v is NaT:
            seen_nat = 1
        elif is_datetime(v) or util.is_datetime64_object(v):
            # datetime, or np.datetime64
            seen_datetime = 1
        elif is_date(v):
            seen_date = 1
        elif is_timedelta(v) or util.is_timedelta64_object(v):
            # timedelta, or timedelta64
            seen_timedelta = 1
        else:
            return 'mixed'

    if seen_date and not (seen_datetime or seen_timedelta):
        return 'date'
    elif seen_datetime and not seen_timedelta:
        return 'datetime'
    elif seen_timedelta and not seen_datetime:
        return 'timedelta'
    elif seen_nat:
        return 'nat'

    # short-circuit by trying to
    # actually convert these strings
    # this is for performance as we don't need to try
    # convert *every* string array
    if len(objs):
        try:
            tslib.array_to_datetime(objs, errors='raise')
            return 'datetime'
        except:
            pass

        # we are *not* going to infer from strings
        # for timedelta as too much ambiguity

    return 'mixed'


cdef inline bint is_null_datetimelike(v):
    # determine if we have a null for a timedelta/datetime (or integer
    # versions)
    if util._checknull(v):
        return True
    elif v is NaT:
        return True
    elif util.is_timedelta64_object(v):
        return v.view('int64') == iNaT
    elif util.is_datetime64_object(v):
        return v.view('int64') == iNaT
    elif util.is_integer_object(v):
        return v == iNaT
    return False


cdef inline bint is_null_datetime64(v):
    # determine if we have a null for a datetime (or integer versions),
    # excluding np.timedelta64('nat')
    if util._checknull(v):
        return True
    elif v is NaT:
        return True
    elif util.is_datetime64_object(v):
        return v.view('int64') == iNaT
    return False


cdef inline bint is_null_timedelta64(v):
    # determine if we have a null for a timedelta (or integer versions),
    # excluding np.datetime64('nat')
    if util._checknull(v):
        return True
    elif v is NaT:
        return True
    elif util.is_timedelta64_object(v):
        return v.view('int64') == iNaT
    return False


cdef inline bint is_null_period(v):
    # determine if we have a null for a Period (or integer versions),
    # excluding np.datetime64('nat') and np.timedelta64('nat')
    if util._checknull(v):
        return True
    elif v is NaT:
        return True
    return False


cdef inline bint is_datetime(object o):
    return PyDateTime_Check(o)

cdef inline bint is_date(object o):
    return PyDate_Check(o)

cdef inline bint is_time(object o):
    return PyTime_Check(o)

cdef inline bint is_timedelta(object o):
    return PyDelta_Check(o) or util.is_timedelta64_object(o)


cdef class Validator:

    cdef:
        Py_ssize_t n
        np.dtype dtype
        bint skipna

    def __cinit__(
        self,
        Py_ssize_t n,
        np.dtype dtype=np.dtype(np.object_),
        bint skipna=False
    ):
        self.n = n
        self.dtype = dtype
        self.skipna = skipna

    cdef bint validate(self, object[:] values) except -1:
        if not self.n:
            return False

        if self.is_array_typed():
            return True
        elif self.dtype.type_num == NPY_OBJECT:
            if self.skipna:
                return self._validate_skipna(values)
            else:
                return self._validate(values)
        else:
            return False

    @cython.wraparound(False)
    @cython.boundscheck(False)
    cdef bint _validate(self, object[:] values) except -1:
        cdef:
            Py_ssize_t i
            Py_ssize_t n = self.n

        for i in range(n):
            if not self.is_valid(values[i]):
                return False

        return self.finalize_validate()

    @cython.wraparound(False)
    @cython.boundscheck(False)
    cdef bint _validate_skipna(self, object[:] values) except -1:
        cdef:
            Py_ssize_t i
            Py_ssize_t n = self.n

        for i in range(n):
            if not self.is_valid_skipna(values[i]):
                return False

        return self.finalize_validate_skipna()

    cdef bint is_valid(self, object value) except -1:
        return self.is_value_typed(value)

    cdef bint is_valid_skipna(self, object value) except -1:
        return self.is_valid(value) or self.is_valid_null(value)

    cdef bint is_value_typed(self, object value) except -1:
        raise NotImplementedError(
            '{} child class must define is_value_typed'.format(
                type(self).__name__
            )
        )

    cdef bint is_valid_null(self, object value) except -1:
        return util._checknull(value)

    cdef bint is_array_typed(self) except -1:
        return False

    cdef inline bint finalize_validate(self):
        return True

    cdef bint finalize_validate_skipna(self):
        # TODO(phillipc): Remove the existing validate methods and replace them
        # with the skipna versions upon full deprecation of skipna=False
        return True


cdef class BoolValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return util.is_bool_object(value)

    cdef inline bint is_array_typed(self) except -1:
        return issubclass(self.dtype.type, np.bool_)


cpdef bint is_bool_array(ndarray values, bint skipna=False):
    cdef:
        BoolValidator validator = BoolValidator(
            len(values),
            values.dtype,
            skipna=skipna
        )
    return validator.validate(values)


cdef class IntegerValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return util.is_integer_object(value)

    cdef inline bint is_array_typed(self) except -1:
        return issubclass(self.dtype.type, np.integer)


cpdef bint is_integer_array(ndarray values):
    cdef:
        IntegerValidator validator = IntegerValidator(
            len(values),
            values.dtype,
        )
    return validator.validate(values)


cdef class IntegerFloatValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return util.is_integer_object(value) or util.is_float_object(value)

    cdef inline bint is_array_typed(self) except -1:
        return issubclass(self.dtype.type, np.integer)


cpdef bint is_integer_float_array(ndarray values):
    cdef:
        IntegerFloatValidator validator = IntegerFloatValidator(
            len(values),
            values.dtype,
        )
    return validator.validate(values)


cdef class FloatValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return util.is_float_object(value)

    cdef inline bint is_array_typed(self) except -1:
        return issubclass(self.dtype.type, np.floating)


cpdef bint is_float_array(ndarray values):
    cdef FloatValidator validator = FloatValidator(len(values), values.dtype)
    return validator.validate(values)


cdef class StringValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return PyString_Check(value)

    cdef inline bint is_array_typed(self) except -1:
        return issubclass(self.dtype.type, np.str_)


cpdef bint is_string_array(ndarray values, bint skipna=False):
    cdef:
        StringValidator validator = StringValidator(
            len(values),
            values.dtype,
            skipna=skipna,
        )
    return validator.validate(values)


cdef class UnicodeValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return PyUnicode_Check(value)

    cdef inline bint is_array_typed(self) except -1:
        return issubclass(self.dtype.type, np.unicode_)


cpdef bint is_unicode_array(ndarray values, bint skipna=False):
    cdef:
        UnicodeValidator validator = UnicodeValidator(
            len(values),
            values.dtype,
            skipna=skipna,
        )
    return validator.validate(values)


cdef class BytesValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return PyBytes_Check(value)

    cdef inline bint is_array_typed(self) except -1:
        return issubclass(self.dtype.type, np.bytes_)


cpdef bint is_bytes_array(ndarray values, bint skipna=False):
    cdef:
        BytesValidator validator = BytesValidator(
            len(values),
            values.dtype,
            skipna=skipna
        )
    return validator.validate(values)


cdef class TemporalValidator(Validator):

    cdef Py_ssize_t generic_null_count

    def __cinit__(
        self,
        Py_ssize_t n,
        np.dtype dtype=np.dtype(np.object_),
        bint skipna=False
    ):
        self.n = n
        self.dtype = dtype
        self.skipna = skipna
        self.generic_null_count = 0

    cdef inline bint is_valid(self, object value) except -1:
        return self.is_value_typed(value) or self.is_valid_null(value)

    cdef bint is_valid_null(self, object value) except -1:
        raise NotImplementedError(
            '{} child class must define is_valid_null'.format(
                type(self).__name__
            )
        )

    cdef inline bint is_valid_skipna(self, object value) except -1:
        cdef:
            bint is_typed_null = self.is_valid_null(value)
            bint is_generic_null = util._checknull(value)
        self.generic_null_count += is_typed_null and is_generic_null
        return self.is_value_typed(value) or is_typed_null or is_generic_null

    cdef inline bint finalize_validate_skipna(self):
        return self.generic_null_count != self.n


cdef class DatetimeValidator(TemporalValidator):

    cdef bint is_value_typed(self, object value) except -1:
        return is_datetime(value)

    cdef inline bint is_valid_null(self, object value) except -1:
        return is_null_datetime64(value)


cpdef bint is_datetime_array(ndarray[object] values):
    cdef:
        DatetimeValidator validator = DatetimeValidator(
            len(values),
            skipna=True,
        )
    return validator.validate(values)


cdef class Datetime64Validator(DatetimeValidator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return util.is_datetime64_object(value)


cpdef bint is_datetime64_array(ndarray values):
    cdef:
        Datetime64Validator validator = Datetime64Validator(
            len(values),
            skipna=True,
        )
    return validator.validate(values)


cpdef bint is_datetime_with_singletz_array(ndarray[object] values):
    """
    Check values have the same tzinfo attribute.
    Doesn't check values are datetime-like types.
    """

    cdef Py_ssize_t i, j, n = len(values)
    cdef object base_val, base_tz, val, tz

    if n == 0:
        return False

    for i in range(n):
        base_val = values[i]
        if base_val is not NaT:
            base_tz = get_timezone(getattr(base_val, 'tzinfo', None))

            for j in range(i, n):
                val = values[j]
                if val is not NaT:
                    tz = getattr(val, 'tzinfo', None)
                    if base_tz != tz and base_tz != get_timezone(tz):
                        return False
            break

    return True


cdef class TimedeltaValidator(TemporalValidator):

    cdef bint is_value_typed(self, object value) except -1:
        return PyDelta_Check(value)

    cdef inline bint is_valid_null(self, object value) except -1:
        return is_null_timedelta64(value)


cpdef bint is_timedelta_array(ndarray values):
    cdef:
        TimedeltaValidator validator = TimedeltaValidator(
            len(values),
            skipna=True,
        )
    return validator.validate(values)


cdef class Timedelta64Validator(TimedeltaValidator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return util.is_timedelta64_object(value)


cpdef bint is_timedelta64_array(ndarray values):
    cdef:
        Timedelta64Validator validator = Timedelta64Validator(
            len(values),
            skipna=True,
        )
    return validator.validate(values)


cdef class AnyTimedeltaValidator(TimedeltaValidator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return is_timedelta(value)


cpdef bint is_timedelta_or_timedelta64_array(ndarray values):
    """ infer with timedeltas and/or nat/none """
    cdef:
        AnyTimedeltaValidator validator = AnyTimedeltaValidator(
            len(values),
            skipna=True,
        )
    return validator.validate(values)


cdef class DateValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return is_date(value)


cpdef bint is_date_array(ndarray[object] values, bint skipna=False):
    cdef DateValidator validator = DateValidator(len(values), skipna=skipna)
    return validator.validate(values)


cdef class TimeValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return is_time(value)


cpdef bint is_time_array(ndarray[object] values, bint skipna=False):
    cdef TimeValidator validator = TimeValidator(len(values), skipna=skipna)
    return validator.validate(values)


cdef class PeriodValidator(TemporalValidator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return is_period(value)

    cdef inline bint is_valid_null(self, object value) except -1:
        return is_null_period(value)


cpdef bint is_period_array(ndarray[object] values):
    cdef PeriodValidator validator = PeriodValidator(len(values), skipna=True)
    return validator.validate(values)


cdef class IntervalValidator(Validator):

    cdef inline bint is_value_typed(self, object value) except -1:
        return is_interval(value)


cpdef bint is_interval_array(ndarray[object] values):
    cdef:
        IntervalValidator validator = IntervalValidator(
            len(values),
            skipna=True,
        )
    return validator.validate(values)


cdef extern from "parse_helper.h":
    inline int floatify(object, double *result, int *maybe_int) except -1

# constants that will be compared to potentially arbitrarily large
# python int
cdef object oINT64_MAX = <int64_t> INT64_MAX
cdef object oINT64_MIN = <int64_t> INT64_MIN
cdef object oUINT64_MAX = <uint64_t> UINT64_MAX


@cython.boundscheck(False)
@cython.wraparound(False)
def maybe_convert_numeric(ndarray[object] values, set na_values,
                          bint convert_empty=True, bint coerce_numeric=False):
    """
    Convert object array to a numeric array if possible.

    Parameters
    ----------
    values : ndarray
        Array of object elements to convert.
    na_values : set
        Set of values that should be interpreted as NaN.
    convert_empty : bool, default True
        If an empty array-like object is encountered, whether to interpret
        that element as NaN or not. If set to False, a ValueError will be
        raised if such an element is encountered and 'coerce_numeric' is False.
    coerce_numeric : bool, default False
        If initial attempts to convert to numeric have failed, whether to
        force conversion to numeric via alternative methods or by setting the
        element to NaN. Otherwise, an Exception will be raised when such an
        element is encountered.

        This boolean also has an impact on how conversion behaves when a
        numeric array has no suitable numerical dtype to return (i.e. uint64,
        int32, uint8). If set to False, the original object array will be
        returned. Otherwise, a ValueError will be raised.

    Returns
    -------
    numeric_array : array of converted object values to numerical ones
    """

    if len(values) == 0:
        return np.array([], dtype='i8')

    # fastpath for ints - try to convert all based on first value
    cdef object val = values[0]

    if util.is_integer_object(val):
        try:
            maybe_ints = values.astype('i8')
            if (maybe_ints == values).all():
                return maybe_ints
        except (ValueError, OverflowError, TypeError):
            pass

    # otherwise, iterate and do full infererence
    cdef:
        int status, maybe_int
        Py_ssize_t i, n = values.size
        Seen seen = Seen(coerce_numeric);
        ndarray[float64_t] floats = np.empty(n, dtype='f8')
        ndarray[complex128_t] complexes = np.empty(n, dtype='c16')
        ndarray[int64_t] ints = np.empty(n, dtype='i8')
        ndarray[uint64_t] uints = np.empty(n, dtype='u8')
        ndarray[uint8_t] bools = np.empty(n, dtype='u1')
        float64_t fval

    for i in range(n):
        val = values[i]

        if val.__hash__ is not None and val in na_values:
            seen.saw_null()
            floats[i] = complexes[i] = nan
        elif util.is_float_object(val):
            fval = val
            if fval != fval:
                seen.null_ = True

            floats[i] = complexes[i] = fval
            seen.float_ = True
        elif util.is_integer_object(val):
            floats[i] = complexes[i] = val

            val = int(val)
            seen.saw_int(val)

            if val >= 0:
                uints[i] = val

            if val <= oINT64_MAX:
                ints[i] = val
        elif util.is_bool_object(val):
            floats[i] = uints[i] = ints[i] = bools[i] = val
            seen.bool_ = True
        elif val is None:
            seen.saw_null()
            floats[i] = complexes[i] = nan
        elif hasattr(val, '__len__') and len(val) == 0:
            if convert_empty or seen.coerce_numeric:
                seen.saw_null()
                floats[i] = complexes[i] = nan
            else:
                raise ValueError('Empty string encountered')
        elif util.is_complex_object(val):
            complexes[i] = val
            seen.complex_ = True
        elif is_decimal(val):
            floats[i] = complexes[i] = val
            seen.float_ = True
        else:
            try:
                status = floatify(val, &fval, &maybe_int)

                if fval in na_values:
                    seen.saw_null()
                    floats[i] = complexes[i] = nan
                else:
                    if fval != fval:
                        seen.null_ = True

                    floats[i] = fval

                if maybe_int:
                    as_int = int(val)

                    if as_int in na_values:
                        seen.saw_null()
                    else:
                        seen.saw_int(as_int)

                    if not (seen.float_ or as_int in na_values):
                        if as_int < oINT64_MIN or as_int > oUINT64_MAX:
                            raise ValueError('Integer out of range.')

                        if as_int >= 0:
                            uints[i] = as_int
                        if as_int <= oINT64_MAX:
                            ints[i] = as_int
                else:
                    seen.float_ = True
            except (TypeError, ValueError) as e:
                if not seen.coerce_numeric:
                    raise type(e)(str(e) + ' at position {}'.format(i))
                elif "uint64" in str(e):  # Exception from check functions.
                    raise
                seen.saw_null()
                floats[i] = nan

    if seen.check_uint64_conflict():
        return values

    if seen.complex_:
        return complexes
    elif seen.float_:
        return floats
    elif seen.int_:
        if seen.uint_:
            return uints
        else:
            return ints
    elif seen.bool_:
        return bools.view(np.bool_)
    elif seen.uint_:
        return uints
    return ints


@cython.boundscheck(False)
@cython.wraparound(False)
def maybe_convert_objects(ndarray[object] objects, bint try_float=0,
                          bint safe=0, bint convert_datetime=0,
                          bint convert_timedelta=0):
    """
    Type inference function-- convert object array to proper dtype
    """
    cdef:
        Py_ssize_t i, n
        ndarray[float64_t] floats
        ndarray[complex128_t] complexes
        ndarray[int64_t] ints
        ndarray[uint64_t] uints
        ndarray[uint8_t] bools
        ndarray[int64_t] idatetimes
        ndarray[int64_t] itimedeltas
        Seen seen = Seen();
        object val, onan
        float64_t fval, fnan

    n = len(objects)

    floats = np.empty(n, dtype='f8')
    complexes = np.empty(n, dtype='c16')
    ints = np.empty(n, dtype='i8')
    uints = np.empty(n, dtype='u8')
    bools = np.empty(n, dtype=np.uint8)

    if convert_datetime:
        datetimes = np.empty(n, dtype='M8[ns]')
        idatetimes = datetimes.view(np.int64)

    if convert_timedelta:
        timedeltas = np.empty(n, dtype='m8[ns]')
        itimedeltas = timedeltas.view(np.int64)

    onan = np.nan
    fnan = np.nan

    for i from 0 <= i < n:
        val = objects[i]

        if val is None:
            seen.null_ = 1
            floats[i] = complexes[i] = fnan
        elif val is NaT:
            if convert_datetime:
                idatetimes[i] = iNaT
                seen.datetime_ = 1
            if convert_timedelta:
                itimedeltas[i] = iNaT
                seen.timedelta_ = 1
            if not (convert_datetime or convert_timedelta):
                seen.object_ = 1
        elif util.is_bool_object(val):
            seen.bool_ = 1
            bools[i] = val
        elif util.is_float_object(val):
            floats[i] = complexes[i] = val
            seen.float_ = 1
        elif util.is_datetime64_object(val):
            if convert_datetime:
                idatetimes[i] = convert_to_tsobject(
                    val, None, None, 0, 0).value
                seen.datetime_ = 1
            else:
                seen.object_ = 1
                break
        elif is_timedelta(val):
            if convert_timedelta:
                itimedeltas[i] = convert_to_timedelta64(val, 'ns')
                seen.timedelta_ = 1
            else:
                seen.object_ = 1
                break
        elif util.is_integer_object(val):
            seen.int_ = 1
            floats[i] = <float64_t> val
            complexes[i] = <double complex> val
            if not seen.null_:
                seen.saw_int(int(val))

                if seen.uint_ and seen.sint_:
                    seen.object_ = 1
                    break

                if seen.uint_:
                    uints[i] = val
                elif seen.sint_:
                    ints[i] = val
                else:
                    uints[i] = val
                    ints[i] = val

        elif util.is_complex_object(val):
            complexes[i] = val
            seen.complex_ = 1
        elif PyDateTime_Check(val) or util.is_datetime64_object(val):

            # if we have an tz's attached then return the objects
            if convert_datetime:
                if getattr(val, 'tzinfo', None) is not None:
                    seen.datetimetz_ = 1
                    break
                else:
                    seen.datetime_ = 1
                    idatetimes[i] = convert_to_tsobject(
                        val, None, None, 0, 0).value
            else:
                seen.object_ = 1
                break
        elif try_float and not util.is_string_object(val):
            # this will convert Decimal objects
            try:
                floats[i] = float(val)
                complexes[i] = complex(val)
                seen.float_ = 1
            except Exception:
                seen.object_ = 1
                break
        else:
            seen.object_ = 1
            break

    # we try to coerce datetime w/tz but must all have the same tz
    if seen.datetimetz_:
        if len(set([getattr(val, 'tzinfo', None) for val in objects])) == 1:
            from pandas import DatetimeIndex
            return DatetimeIndex(objects)
        seen.object_ = 1

    if not seen.object_:
        if not safe:
            if seen.null_:
                if seen.is_float_or_complex:
                    if seen.complex_:
                        return complexes
                    elif seen.float_ or seen.int_:
                        return floats
            else:
                if not seen.bool_:
                    if seen.datetime_:
                        if not seen.numeric_:
                            return datetimes
                    elif seen.timedelta_:
                        if not seen.numeric_:
                            return timedeltas
                    else:
                        if seen.complex_:
                            return complexes
                        elif seen.float_:
                            return floats
                        elif seen.int_:
                            if seen.uint_:
                                return uints
                            else:
                                return ints
                elif seen.is_bool:
                    return bools.view(np.bool_)

        else:
            # don't cast int to float, etc.
            if seen.null_:
                if seen.is_float_or_complex:
                    if seen.complex_:
                        if not seen.int_:
                            return complexes
                    elif seen.float_:
                        if not seen.int_:
                            return floats
            else:
                if not seen.bool_:
                    if seen.datetime_:
                        if not seen.numeric_:
                            return datetimes
                    elif seen.timedelta_:
                        if not seen.numeric_:
                            return timedeltas
                    else:
                        if seen.complex_:
                            if not seen.int_:
                                return complexes
                        elif seen.float_:
                            if not seen.int_:
                                return floats
                        elif seen.int_:
                            if seen.uint_:
                                return uints
                            else:
                                return ints
                elif seen.is_bool:
                    return bools.view(np.bool_)

    return objects


def convert_sql_column(x):
    return maybe_convert_objects(x, try_float=1)


def try_parse_dates(ndarray[object] values, parser=None,
                    dayfirst=False, default=None):
    cdef:
        Py_ssize_t i, n
        ndarray[object] result

    n = len(values)
    result = np.empty(n, dtype='O')

    if parser is None:
        if default is None: # GH2618
            date=datetime.now()
            default=datetime(date.year, date.month, 1)

        try:
            from dateutil.parser import parse
            parse_date = lambda x: parse(x, dayfirst=dayfirst, default=default)
        except ImportError: # pragma: no cover
            def parse_date(s):
                try:
                    return datetime.strptime(s, '%m/%d/%Y')
                except Exception:
                    return s
        # EAFP here
        try:
            for i from 0 <= i < n:
                if values[i] == '':
                    result[i] = np.nan
                else:
                    result[i] = parse_date(values[i])
        except Exception:
            # failed
            return values
    else:
        parse_date = parser

        try:
            for i from 0 <= i < n:
                if values[i] == '':
                    result[i] = np.nan
                else:
                    result[i] = parse_date(values[i])
        except Exception:
            # raise if passed parser and it failed
            raise

    return result


def try_parse_date_and_time(ndarray[object] dates, ndarray[object] times,
                            date_parser=None, time_parser=None,
                            dayfirst=False, default=None):
    cdef:
        Py_ssize_t i, n
        ndarray[object] result

    from datetime import date, time, datetime, timedelta

    n = len(dates)
    if len(times) != n:
        raise ValueError('Length of dates and times must be equal')
    result = np.empty(n, dtype='O')

    if date_parser is None:
        if default is None: # GH2618
            date=datetime.now()
            default=datetime(date.year, date.month, 1)

        try:
            from dateutil.parser import parse
            parse_date = lambda x: parse(x, dayfirst=dayfirst, default=default)
        except ImportError: # pragma: no cover
            def parse_date(s):
                try:
                    return date.strptime(s, '%m/%d/%Y')
                except Exception:
                    return s
    else:
        parse_date = date_parser

    if time_parser is None:
        try:
            from dateutil.parser import parse
            parse_time = lambda x: parse(x)
        except ImportError: # pragma: no cover
            def parse_time(s):
                try:
                    return time.strptime(s, '%H:%M:%S')
                except Exception:
                    return s

    else:
        parse_time = time_parser

    for i from 0 <= i < n:
        d = parse_date(str(dates[i]))
        t = parse_time(str(times[i]))
        result[i] = datetime(d.year, d.month, d.day,
                             t.hour, t.minute, t.second)

    return result


def try_parse_year_month_day(ndarray[object] years, ndarray[object] months,
                             ndarray[object] days):
    cdef:
        Py_ssize_t i, n
        ndarray[object] result

    from datetime import datetime

    n = len(years)
    if len(months) != n or len(days) != n:
        raise ValueError('Length of years/months/days must all be equal')
    result = np.empty(n, dtype='O')

    for i from 0 <= i < n:
        result[i] = datetime(int(years[i]), int(months[i]), int(days[i]))

    return result


def try_parse_datetime_components(ndarray[object] years,
                                  ndarray[object] months,
                                  ndarray[object] days,
                                  ndarray[object] hours,
                                  ndarray[object] minutes,
                                  ndarray[object] seconds):

    cdef:
        Py_ssize_t i, n
        ndarray[object] result
        int secs
        double float_secs
        double micros

    from datetime import datetime

    n = len(years)
    if (len(months) != n or len(days) != n or len(hours) != n or
        len(minutes) != n or len(seconds) != n):
        raise ValueError('Length of all datetime components must be equal')
    result = np.empty(n, dtype='O')

    for i from 0 <= i < n:
        float_secs = float(seconds[i])
        secs = int(float_secs)

        micros = float_secs - secs
        if micros > 0:
            micros = micros * 1000000

        result[i] = datetime(int(years[i]), int(months[i]), int(days[i]),
                             int(hours[i]), int(minutes[i]), secs,
                             int(micros))

    return result


def sanitize_objects(ndarray[object] values, set na_values,
                     convert_empty=True):
    cdef:
        Py_ssize_t i, n
        object val, onan
        Py_ssize_t na_count = 0
        dict memo = {}

    n = len(values)
    onan = np.nan

    for i from 0 <= i < n:
        val = values[i]
        if (convert_empty and val == '') or (val in na_values):
            values[i] = onan
            na_count += 1
        elif val in memo:
            values[i] = memo[val]
        else:
            memo[val] = val

    return na_count


def maybe_convert_bool(ndarray[object] arr,
                       true_values=None, false_values=None):
    cdef:
        Py_ssize_t i, n
        ndarray[uint8_t] result
        object val
        set true_vals, false_vals
        int na_count = 0

    n = len(arr)
    result = np.empty(n, dtype=np.uint8)

    # the defaults
    true_vals = set(('True', 'TRUE', 'true'))
    false_vals = set(('False', 'FALSE', 'false'))

    if true_values is not None:
        true_vals = true_vals | set(true_values)

    if false_values is not None:
        false_vals = false_vals | set(false_values)

    for i from 0 <= i < n:
        val = arr[i]

        if cpython.PyBool_Check(val):
            if val is True:
                result[i] = 1
            else:
                result[i] = 0
        elif val in true_vals:
            result[i] = 1
        elif val in false_vals:
            result[i] = 0
        elif PyFloat_Check(val):
            result[i] = UINT8_MAX
            na_count += 1
        else:
            return arr

    if na_count > 0:
        mask = result == UINT8_MAX
        arr = result.view(np.bool_).astype(object)
        np.putmask(arr, mask, np.nan)
        return arr
    else:
        return result.view(np.bool_)


def map_infer_mask(ndarray arr, object f, ndarray[uint8_t] mask,
                   bint convert=1):
    """
    Substitute for np.vectorize with pandas-friendly dtype inference

    Parameters
    ----------
    arr : ndarray
    f : function

    Returns
    -------
    mapped : ndarray
    """
    cdef:
        Py_ssize_t i, n
        ndarray[object] result
        object val

    n = len(arr)
    result = np.empty(n, dtype=object)
    for i in range(n):
        if mask[i]:
            val = util.get_value_at(arr, i)
        else:
            val = f(util.get_value_at(arr, i))

            # unbox 0-dim arrays, GH #690
            if is_array(val) and PyArray_NDIM(val) == 0:
                # is there a faster way to unbox?
                val = val.item()

        result[i] = val

    if convert:
        return maybe_convert_objects(result,
                                     try_float=0,
                                     convert_datetime=0,
                                     convert_timedelta=0)

    return result


def map_infer(ndarray arr, object f, bint convert=1):
    """
    Substitute for np.vectorize with pandas-friendly dtype inference

    Parameters
    ----------
    arr : ndarray
    f : function

    Returns
    -------
    mapped : ndarray
    """
    cdef:
        Py_ssize_t i, n
        ndarray[object] result
        object val

    n = len(arr)
    result = np.empty(n, dtype=object)
    for i in range(n):
        val = f(util.get_value_at(arr, i))

        # unbox 0-dim arrays, GH #690
        if is_array(val) and PyArray_NDIM(val) == 0:
            # is there a faster way to unbox?
            val = val.item()

        result[i] = val

    if convert:
        return maybe_convert_objects(result,
                                     try_float=0,
                                     convert_datetime=0,
                                     convert_timedelta=0)

    return result


def to_object_array(list rows, int min_width=0):
    """
    Convert a list of lists into an object array.

    Parameters
    ----------
    rows : 2-d array (N, K)
        A list of lists to be converted into an array
    min_width : int
        The minimum width of the object array. If a list
        in `rows` contains fewer than `width` elements,
        the remaining elements in the corresponding row
        will all be `NaN`.

    Returns
    -------
    obj_array : numpy array of the object dtype
    """
    cdef:
        Py_ssize_t i, j, n, k, tmp
        ndarray[object, ndim=2] result
        list row

    n = len(rows)

    k = min_width
    for i from 0 <= i < n:
        tmp = len(rows[i])
        if tmp > k:
            k = tmp

    result = np.empty((n, k), dtype=object)

    for i from 0 <= i < n:
        row = rows[i]

        for j from 0 <= j < len(row):
            result[i, j] = row[j]

    return result


def tuples_to_object_array(ndarray[object] tuples):
    cdef:
        Py_ssize_t i, j, n, k, tmp
        ndarray[object, ndim=2] result
        tuple tup

    n = len(tuples)
    k = len(tuples[0])
    result = np.empty((n, k), dtype=object)
    for i in range(n):
        tup = tuples[i]
        for j in range(k):
            result[i, j] = tup[j]

    return result


def to_object_array_tuples(list rows):
    cdef:
        Py_ssize_t i, j, n, k, tmp
        ndarray[object, ndim=2] result
        tuple row

    n = len(rows)

    k = 0
    for i from 0 <= i < n:
        tmp = len(rows[i])
        if tmp > k:
            k = tmp

    result = np.empty((n, k), dtype=object)

    try:
        for i in range(n):
            row = rows[i]
            for j from 0 <= j < len(row):
                result[i, j] = row[j]
    except Exception:
        # upcast any subclasses to tuple
        for i in range(n):
            row = tuple(rows[i])
            for j from 0 <= j < len(row):
                result[i, j] = row[j]

    return result


def fast_multiget(dict mapping, ndarray keys, default=np.nan):
    cdef:
        Py_ssize_t i, n = len(keys)
        object val
        ndarray[object] output = np.empty(n, dtype='O')

    if n == 0:
        # kludge, for Series
        return np.empty(0, dtype='f8')

    keys = getattr(keys, 'values', keys)

    for i in range(n):
        val = util.get_value_1d(keys, i)
        if val in mapping:
            output[i] = mapping[val]
        else:
            output[i] = default

    return maybe_convert_objects(output)


def downcast_int64(ndarray[int64_t] arr, object na_values,
                   bint use_unsigned=0):
    cdef:
        Py_ssize_t i, n = len(arr)
        int64_t mx = INT64_MIN + 1, mn = INT64_MAX
        int64_t NA = na_values[np.int64]
        int64_t val
        ndarray[uint8_t] mask
        int na_count = 0

    _mask = np.empty(n, dtype=bool)
    mask = _mask.view(np.uint8)

    for i in range(n):
        val = arr[i]

        if val == NA:
            mask[i] = 1
            na_count += 1
            continue

        # not NA
        mask[i] = 0

        if val > mx:
            mx = val

        if val < mn:
            mn = val

    if mn >= 0 and use_unsigned:
        if mx <= UINT8_MAX - 1:
            result = arr.astype(np.uint8)
            if na_count:
                np.putmask(result, _mask, na_values[np.uint8])
            return result

        if mx <= UINT16_MAX - 1:
            result = arr.astype(np.uint16)
            if na_count:
                np.putmask(result, _mask, na_values[np.uint16])
            return result

        if mx <= UINT32_MAX - 1:
            result = arr.astype(np.uint32)
            if na_count:
                np.putmask(result, _mask, na_values[np.uint32])
            return result

    else:
        if mn >= INT8_MIN + 1 and mx <= INT8_MAX:
            result = arr.astype(np.int8)
            if na_count:
                np.putmask(result, _mask, na_values[np.int8])
            return result

        if mn >= INT16_MIN + 1 and mx <= INT16_MAX:
            result = arr.astype(np.int16)
            if na_count:
                np.putmask(result, _mask, na_values[np.int16])
            return result

        if mn >= INT32_MIN + 1 and mx <= INT32_MAX:
            result = arr.astype(np.int32)
            if na_count:
                np.putmask(result, _mask, na_values[np.int32])
            return result

    return arr
