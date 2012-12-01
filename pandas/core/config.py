"""
The config module holds package-wide configurables and provides
a uniform API for working with them.
"""

"""
Overview
========

This module supports the following requirements:
- options are referenced using keys in dot.notation, e.g. "x.y.option - z".
- keys are case-insensitive.
- functions should accept partial/regex keys, when unambiguous.
- options can be registered by modules at import time.
- options can be registered at init-time (via core.config_init)
- options have a default value, and (optionally) a description and
  validation function associated with them.
- options can be deprecated, in which case referencing them
  should produce a warning.
- deprecated options can optionally be rerouted to a replacement
  so that accessing a deprecated option reroutes to a differently
  named option.
- options can be reset to their default value.
- all option can be reset to their default value at once.
- all options in a certain sub - namespace can be reset at once.
- the user can set / get / reset or ask for the description of an option.
- a developer can register and mark an option as deprecated.


Implementation
==============

- Data is stored using nested dictionaries, and should be accessed
  through the provided API.

- "Registered options" and "Deprecated options" have metadata associcated
  with them, which are stored in auxilary dictionaries keyed on the
  fully-qualified key, e.g. "x.y.z.option".

- the config_init module is imported by the package's __init__.py file.
  placing any register_option() calls there will ensure those options
  are available as soon as pandas is loaded. If you use register_option
  in a module, it will only be available after that module is imported,
  which you should be aware of.

- `config_prefix` is a context_manager (for use with the `with` keyword)
  which can save developers some typing, see the docstring.

"""

import re

from collections import namedtuple
import warnings

DeprecatedOption = namedtuple('DeprecatedOption', 'key msg rkey removal_ver')
RegisteredOption = namedtuple('RegisteredOption', 'key defval doc validator')

_deprecated_options = {}  # holds deprecated option metdata
_registered_options = {}  # holds registered option metdata
_global_config = {}  # holds the current values for registered options
_reserved_keys = ['all']  # keys which have a special meaning


##########################################
# User API

def _get_option(pat):
    keys = _select_options(pat)
    if len(keys) == 0:
        _warn_if_deprecated(pat)
        raise KeyError('No such keys(s)')
    if len(keys) > 1:
        raise KeyError('Pattern matched multiple keys')
    key = keys[0]

    _warn_if_deprecated(key)

    key = _translate_key(key)

    # walk the nested dict
    root, k = _get_root(key)

    return root[k]


def _set_option(pat, value):

    keys = _select_options(pat)
    if len(keys) == 0:
        _warn_if_deprecated(pat)
        raise KeyError('No such keys(s)')
    if len(keys) > 1:
        raise KeyError('Pattern matched multiple keys')
    key = keys[0]

    _warn_if_deprecated(key)
    key = _translate_key(key)

    o = _get_registered_option(key)
    if o and o.validator:
        o.validator(value)

    # walk the nested dict
    root, k = _get_root(key)
    root[k] = value


def _describe_option(pat='', _print_desc=True):

    keys = _select_options(pat)
    if len(keys) == 0:
        raise KeyError('No such keys(s)')

    s = u''
    for k in keys:  # filter by pat
        s += _build_option_description(k)

    if _print_desc:
        print s
    else:
        return s


def _reset_option(pat):

    keys = _select_options(pat)

    if pat == u'':
        raise ValueError('You must provide a non-empty pattern')

    if len(keys) == 0:
        raise KeyError('No such keys(s)')

    if len(keys) > 1 and len(pat) < 4 and pat != 'all':
        raise ValueError('You must specify at least 4 characters when '
                         'resetting multiple keys')

    for k in keys:
        _set_option(k, _registered_options[k].defval)


# For user convenience,  we'd like to have the available options described
# in the docstring. For dev convenience we'd like to generate the docstrings
# dynamically instead of maintaining them by hand. To this, we use the
# class below which wraps functions inside a callable, and converts
# __doc__ into a propery function. The doctsrings below are templates
# using the py2.6+ advanced formatting syntax to plug in a concise list
# of options, and option descriptions.

class CallableDyanmicDoc(object):

    def __init__(self, func, doc_tmpl):
        self.__doc_tmpl__ = doc_tmpl
        self.__func__ = func

    def __call__(self, *args, **kwds):
        return self.__func__(*args, **kwds)

    @property
    def __doc__(self):
        opts_desc = _describe_option('all', _print_desc=False)
        opts_list = pp_options_list(_registered_options.keys())
        return self.__doc_tmpl__.format(opts_desc=opts_desc,
                opts_list=opts_list)

_get_option_tmpl = """"get_option(pat) - Retrieves the value of the specified option

Available options:
{opts_list}

Parameters
----------
pat - str/regexp which should match a single option.

Note: partial matches are supported for convenience, but unless you use the
full option name (e.g. x.y.z.option_name), your code may break in future
versions if new options with similar names are introduced.

Returns
-------
result - the value of the option

Raises
------
KeyError if no such option exists

{opts_desc}
"""

_set_option_tmpl="""set_option(pat,value) - Sets the value of the specified option

Available options:
{opts_list}

Parameters
----------
pat - str/regexp which should match a single option.

Note: partial matches are supported for convenience, but unless you use the
full option name (e.g. x.y.z.option_name), your code may break in future
versions if new options with similar names are introduced.

value - new value of function.

Returns
-------
None

Raises
------
KeyError if no such option exists

{opts_desc}
"""

_describe_option_tmpl="""describe_option(pat,_print_desc=False) Prints the description
for one or more registered options.

Call with not arguments to get a listing for all registered options.

Available options:
{opts_list}

Parameters
----------
pat - str, a regexp pattern. All matching keys will have their
      description displayed.

_print_desc - if True (default) the description(s) will be printed
             to stdout otherwise, the description(s) will be returned
             as a unicode string (for testing).

Returns
-------
None by default, the description(s) as a unicode string if _print_desc
is False

{opts_desc}
"""

_reset_option_tmpl="""reset_option(pat) - Reset one or more options to their default value.

Pass "all" as argument to reset all options.

Available options:
{opts_list}

Parameters
----------
pat - str/regex  if specified only options matching `prefix`* will be reset

Note: partial matches are supported for convenience, but unless you use the
full option name (e.g. x.y.z.option_name), your code may break in future
versions if new options with similar names are introduced.

Returns
-------
None

{opts_desc}
"""

# bind the functions with their docstrings into a Callable
# and use that as the functions exposed in pd.api
get_option = CallableDyanmicDoc(_get_option, _get_option_tmpl)
set_option = CallableDyanmicDoc(_set_option, _set_option_tmpl)
reset_option = CallableDyanmicDoc(_reset_option, _reset_option_tmpl)
describe_option = CallableDyanmicDoc(_describe_option, _describe_option_tmpl)


######################################################
# Functions for use by pandas developers, in addition to User - api

def register_option(key, defval, doc='', validator=None):
    """Register an option in the package-wide pandas config object

    Parameters
    ----------
    key       - a fully-qualified key, e.g. "x.y.option - z".
    defval    - the default value of the option
    doc       - a string description of the option
    validator - a function of a single argument, should raise `ValueError` if
                called with a value which is not a legal value for the option.

    Returns
    -------
    Nothing.

    Raises
    ------
    ValueError if `validator` is specified and `defval` is not a valid value.

    """

    key = key.lower()

    if key in _registered_options:
        raise KeyError("Option '%s' has already been registered" % key)
    if key in _reserved_keys:
        raise KeyError("Option '%s' is a reserved key" % key)

    # the default value should be legal
    if validator:
        validator(defval)

    # walk the nested dict, creating dicts as needed along the path
    path = key.split('.')
    cursor = _global_config
    for i, p in enumerate(path[:-1]):
        if not isinstance(cursor, dict):
            raise KeyError("Path prefix to option '%s' is already an option"
                           % '.'.join(path[:i]))
        if not cursor.has_key(p):
            cursor[p] = {}
        cursor = cursor[p]

    if not isinstance(cursor, dict):
        raise KeyError("Path prefix to option '%s' is already an option"
                       % '.'.join(path[:-1]))

    cursor[path[-1]] = defval  # initialize

    # save the option metadata
    _registered_options[key] = RegisteredOption(key=key, defval=defval,
            doc=doc, validator=validator)


def deprecate_option(key, msg=None, rkey=None, removal_ver=None):
    """
    Mark option `key` as deprecated, if code attempts to access this option,
    a warning will be produced, using `msg` if given, or a default message
    if not.
    if `rkey` is given, any access to the key will be re-routed to `rkey`.

    Neither the existence of `key` nor that if `rkey` is checked. If they
    do not exist, any subsequence access will fail as usual, after the
    deprecation warning is given.

    Parameters
    ----------
    key - the name of the option to be deprecated. must be a fully-qualified
          option name (e.g "x.y.z.rkey").

    msg - (Optional) a warning message to output when the key is referenced.
          if no message is given a default message will be emitted.

    rkey - (Optional) the name of an option to reroute access to.
           If specified, any referenced `key` will be re-routed to `rkey`
           including set/get/reset.
           rkey must be a fully-qualified option name (e.g "x.y.z.rkey").
           used by the default message if no `msg` is specified.

    removal_ver - (Optional) specifies the version in which this option will
                  be removed. used by the default message if no `msg`
                  is specified.

    Returns
    -------
    Nothing

    Raises
    ------
    KeyError - if key has already been deprecated.

    """

    key = key.lower()

    if key in _deprecated_options:
        raise KeyError("Option '%s' has already been defined as deprecated."
                       % key)

    _deprecated_options[key] = DeprecatedOption(key, msg, rkey, removal_ver)


################################
# functions internal to the module

def _select_options(pat):
    """returns a list of keys matching `pat`

    if pat=="all", returns all registered options
    """

    keys = sorted(_registered_options.keys())
    if pat == 'all':  # reserved key
        return keys

    return [k for k in keys if re.search(pat, k, re.I)]


def _get_root(key):
    path = key.split('.')
    cursor = _global_config
    for p in path[:-1]:
        cursor = cursor[p]
    return cursor, path[-1]


def _is_deprecated(key):
    """ Returns True if the given option has been deprecated """

    key = key.lower()
    return _deprecated_options.has_key(key)


def _get_deprecated_option(key):
    """
    Retrieves the metadata for a deprecated option, if `key` is deprecated.

    Returns
    -------
    DeprecatedOption (namedtuple) if key is deprecated, None otherwise
    """

    try:
        d = _deprecated_options[key]
    except KeyError:
        return None
    else:
        return d


def _get_registered_option(key):
    """
    Retrieves the option metadata if `key` is a registered option.

    Returns
    -------
    RegisteredOption (namedtuple) if key is deprecated, None otherwise
    """

    try:
        d = _registered_options[key]
    except KeyError:
        return None
    else:
        return d


def _translate_key(key):
    """
    if key id deprecated and a replacement key defined, will return the
    replacement key, otherwise returns `key` as - is
    """

    d = _get_deprecated_option(key)
    if d:
        return d.rkey or key
    else:
        return key


def _warn_if_deprecated(key):
    """
    Checks if `key` is a deprecated option and if so, prints a warning.

    Returns
    -------
    bool - True if `key` is deprecated, False otherwise.
    """

    d = _get_deprecated_option(key)
    if d:
        if d.msg:
            warnings.warn(d.msg, DeprecationWarning)
        else:
            msg = "'%s' is deprecated" % key
            if d.removal_ver:
                msg += ' and will be removed in %s' % d.removal_ver
            if d.rkey:
                msg += ", please use '%s' instead." % d.rkey
            else:
                msg += ', please refrain from using it.'

            warnings.warn(msg, DeprecationWarning)
        return True
    return False


def _build_option_description(k):
    """ Builds a formatted description of a registered option and prints it """

    o = _get_registered_option(k)
    d = _get_deprecated_option(k)
    s = u'%s: ' % k
    if o.doc:
        s += '\n' + '\n    '.join(o.doc.strip().split('\n'))
    else:
        s += 'No description available.\n'

    if d:
        s += u'\n\t(Deprecated'
        s += (u', use `%s` instead.' % d.rkey if d.rkey else '')
        s += u')\n'

    s += '\n'
    return s


def pp_options_list(keys, width=80, _print=False):
    """ Builds a concise listing of available options, grouped by prefix """

    from textwrap import wrap
    from itertools import groupby

    def pp(name, ks):
        pfx = (name + '.[' if name else '')
        ls = wrap(', '.join(ks), width, initial_indent=pfx,
                  subsequent_indent=' ' * len(pfx), break_long_words=False)
        if ls and ls[-1] and name:
            ls[-1] = ls[-1] + ']'
        return ls

    ls = []
    singles = [x for x in sorted(keys) if x.find('.') < 0]
    if singles:
        ls += pp('', singles)
    keys = [x for x in keys if x.find('.') >= 0]

    for k, g in groupby(sorted(keys), lambda x: x[:x.rfind('.')]):
        ks = [x[len(k) + 1:] for x in list(g)]
        ls += pp(k, ks)
    s = '\n'.join(ls)
    if _print:
        print s
    else:
        return s


##############
# helpers

from contextlib import contextmanager


@contextmanager
def config_prefix(prefix):
    """contextmanager for multiple invocations of API  with a common prefix

    supported API functions: (register / get / set )__option

    Warning: This is not thread - safe, and won't work properly if you import
    the API functions into your module using the "from x import y" construct.

    Example:

    import pandas.core.config as cf
    with cf.config_prefix("display.font"):
        cf.register_option("color", "red")
        cf.register_option("size", " 5 pt")
        cf.set_option(size, " 6 pt")
        cf.get_option(size)
        ...

        etc'

    will register options "display.font.color", "display.font.size", set the
    value of "display.font.size"... and so on.
    """

    # Note: reset_option relies on set_option, and on key directly
    # it does not fit in to this monkey-patching scheme

    global register_option, get_option, set_option, reset_option

    def wrap(func):

        def inner(key, *args, **kwds):
            pkey = '%s.%s' % (prefix, key)
            return func(pkey, *args, **kwds)

        return inner

    _register_option = register_option
    _get_option = get_option
    _set_option = set_option
    set_option = wrap(set_option)
    get_option = wrap(get_option)
    register_option = wrap(register_option)
    yield None
    set_option = _set_option
    get_option = _get_option
    register_option = _register_option


# These factories and methods are handy for use as the validator
# arg in register_option

def is_type_factory(_type):
    """

    Parameters
    ----------
    `_type` - a type to be compared against (e.g. type(x) == `_type`)

    Returns
    -------
    validator - a function of a single argument x , which returns the
                True if type(x) is equal to `_type`

    """

    def inner(x):
        if type(x) != _type:
            raise ValueError("Value must have type '%s'" % str(_type))

    return inner


def is_instance_factory(_type):
    """

    Parameters
    ----------
    `_type` - the type to be checked against

    Returns
    -------
    validator - a function of a single argument x , which returns the
                True if x is an instance of `_type`

    """

    def inner(x):
        if not isinstance(x, _type):
            raise ValueError("Value must be an instance of '%s'" % str(_type))

    return inner


# common type validators, for convenience
# usage: register_option(... , validator = is_int)
is_int = is_type_factory(int)
is_bool = is_type_factory(bool)
is_float = is_type_factory(float)
is_str = is_type_factory(str)
is_unicode = is_type_factory(unicode)
is_text = is_instance_factory(basestring)
