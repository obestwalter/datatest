# -*- coding: utf-8 -*-
from __future__ import division
import inspect
import re
from unittest import TestCase

from .utils.builtins import *
from .utils import collections

from .compare import CompareSet
from .differences import _make_decimal
from .error import DataAssertionError
from .sources.base import BaseSource


__datatest = True  # Used to detect in-module stack frames (which are
                   # omitted from output).

_re_type = type(re.compile(''))


from .allow import _walk_diff
from .allow import _BaseAllowance

from .allow import _AllowOnly
from .allow import _AllowAny
from .allow import _AllowMissing
from .allow import _AllowExtra
from .allow import _AllowDeviation
from .allow import _AllowPercentDeviation


class DataTestCase(TestCase):
    """This class wraps and extends unittest.TestCase and implements
    additional properties and methods for testing data quality.  When a
    data assertion fails, it raises a DataAssertionError which
    contains a list of detected errors.

    In addition to the new functionality, the familiar TestCase methods
    (like setUp, assertEqual, etc.) are still available.
    """
    @property
    def subjectData(self):
        """A data source containing the data under test---the subject of
        the tests.  The subjectData can be defined at the class-level or
        at the module-level.  To use DataTestCase, you **must** define
        subjectData.

        When defining subjectData at the module-level, this property
        will reach into its parent scopes and return the subjectData
        from the nearest enclosed scope::

            def setUpModule():
                global subjectData
                subjectData = datatest.CsvSource('myfile.csv')

        Class-level declaration::

            class TestMyFile(datatest.DataTestCase):
                @classmethod
                def setUpClass(cls):
                    cls.subjectData = datatest.CsvSource('myfile.csv')
        """
        if hasattr(self, '_subjectData'):
            return self._subjectData
        return self._find_data_source('subjectData')

    @subjectData.setter
    def subjectData(self, value):
        self._subjectData = value

    @property
    def referenceData(self):
        """An optional data source containing data that is trusted to
        be correct.  Like the subjectData, referenceData can be defined
        at the class-level or at the module-level and this property
        will return the referenceData from the nearest enclosed scope.
        Unlike subjectData, defining referenceData is completely
        optional.

        Module-level declaration::

            def setUpModule():
                global subjectData, referenceData
                subjectData = datatest.CsvSource('myfile.csv')
                referenceData = datatest.CsvSource('myreference.csv')

        Class-level declaration::

            class TestMyFile(datatest.DataTestCase):
                @classmethod
                def setUpClass(cls):
                    cls.subjectData = datatest.CsvSource('myfile.csv')
                    cls.referenceData = datatest.CsvSource('myreference.csv')
        """
        if hasattr(self, '_referenceData'):
            return self._referenceData
        return self._find_data_source('referenceData')

    @referenceData.setter
    def referenceData(self, value):
        self._referenceData = value

    @staticmethod
    def _find_data_source(name):
        # TODO: Make this method play nice with getattr() when
        # attribute is missing.
        stack = inspect.stack()
        stack.pop()  # Skip record of current frame.
        for record in stack:   # Bubble-up stack looking for name.
            frame = record[0]
            if name in frame.f_globals:
                return frame.f_globals[name]  # <- EXIT!
        raise NameError('cannot find {0!r}'.format(name))

    def _normalize_required(self, required, method, *args, **kwds):
        """If *required* is None, query data from ``referenceData``; if
        it is another data source, query from this other source; else,
        return unchanged.
        """
        if required == None:
            required = self.referenceData

        if isinstance(required, BaseSource):
            fn = getattr(required, method)
            required = fn(*args, **kwds)

        return required

    def assertDataColumns(self, required=None, msg=None):
        """Test that the column names in subjectData match the
        *required* values.  The *required* argument can be a collection,
        callable, data source, or None::

            def test_columns(self):
                required_names = {'col1', 'col2'}
                self.assertDataColumns(required_names)

        If *required* is omitted, the column names from referenceData
        are used in its place::

            def test_columns(self):
                self.assertDataColumns()
        """
        # TODO: Explore the idea of implementing CompareList to assert
        # column order.
        subject_set = CompareSet(self.subjectData.columns())

        if callable(required):
            differences = subject_set.compare(required)
        else:
            required_list = self._normalize_required(required, 'columns')
            if subject_set != required_list:
                differences = subject_set.compare(required_list)
            else:
                differences = None

        if differences:
            if msg is None:
                msg = 'different column names'
            self.fail(msg, differences)

    def assertDataSet(self, columns, required=None, msg=None, **kwds_filter):
        """Test that the column or *columns* in subjectData contain the
        *required* values::

            def test_column1(self):
                required_values = {'a', 'b'}
                self.assertDataSet('col1', required_values)

        If *columns* is a sequence of strings, we can check for distinct
        groups of values::

            def test_column1and2(self):
                required_groups = {('a', 'x'), ('a', 'y'), ('b', 'x'), ('b', 'y')}
                self.assertDataSet(['col1', 'col2'], required_groups)

        If the *required* argument is a helper-function (or other
        callable), it is used as a key which must return True for
        acceptable values::

            def test_column1(self):
                def length_of_one(x):  # <- Helper function.
                    return len(str(x)) == 1
                self.assertDataSet('col1', length_of_one)

        If the *required* argument is omitted, then values from
        referenceData will be used in its place::

            def test_column1(self):
                self.assertDataSet('col1')

            def test_column1and2(self):
                self.assertDataSet(['col1', 'col2'])
        """
        subject_set = self.subjectData.distinct(columns, **kwds_filter)

        if callable(required):
            differences = subject_set.compare(required)
        else:
            required_set = self._normalize_required(required, 'distinct', columns, **kwds_filter)
            if subject_set != required_set:
                differences = subject_set.compare(required_set)
            else:
                differences = None

        if differences:
            if msg is None:
                msg = 'different {0!r} values'.format(columns)
            self.fail(msg, differences)

    def assertDataSum(self, column, keys, required=None, msg=None, **kwds_filter):
        """Test that the sum of *column* in subjectData, when grouped by
        *keys*, matches a dict of *required* values::

            per_dept = {'finance': 146564,
                        'marketing': 152530,
                        'research': 158397}
            self.assertDataSum('budget', 'department', per_dept)

        Grouping by multiple *keys*::

            dept_quarter = {('finance', 'q1'): 85008,
                            ('finance', 'q2'): 61556,
                            ('marketing', 'q1'): 86941,
                            ('marketing', 'q2'): 65589,
                            ('research', 'q1'): 93454,
                            ('research', 'q2'): 64943}
            self.assertDataSum('budget', ['department', 'quarter'], dept_quarter)

        If *required* argument is omitted, then values from
        referenceData are used in its place::

            self.assertDataSum('budget', ['department', 'quarter'])
        """
        subject_dict = self.subjectData.sum(column, keys, **kwds_filter)

        if callable(required):
            differences = subject_dict.compare(required)
        else:
            required_dict = self._normalize_required(required, 'sum', column, keys, **kwds_filter)
            differences = subject_dict.compare(required_dict)

        if differences:
            if not msg:
                msg = 'different {0!r} sums'.format(column)
            self.fail(msg, differences)

    def assertDataCount(self, column, keys, required=None, msg=None, **kwds_filter):
        """Test that the count of non-empty values in subjectData column
        matches the the *required* values dict.  If *required* is
        omitted, the **sum** of values in referenceData column (not the
        count) is used in its place.

        The *required* argument can be a dict, callable, data source,
        or None.  See :meth:`assertDataSet
        <datatest.DataTestCase.assertDataSet>` for more details.
        """
        subject_result = self.subjectData.count(column, keys, **kwds_filter)

        if callable(required):
            differences = subject_result.compare(required)
        else:
            # Gets 'sum' of reference column (not 'count').
            required_dict = self._normalize_required(required, 'sum', column, keys, **kwds_filter)
            differences = subject_result.compare(required_dict)

        if differences:
            if not msg:
                msg = 'row counts different than {0!r} sums'.format(column)
            self.fail(msg, differences)

    def assertDataRegex(self, column, required, msg=None, **kwds_filter):
        """Test that *column* in ``subjectData`` contains values that
        match a *required* regular expression::

            def test_date(self):
                wellformed = r'\d\d\d\d-\d\d-\d\d'  # Matches YYYY-MM-DD.
                self.assertDataRegex('date', wellformed)

        The *required* argument must be a string or a compiled regular
        expression object (it can not be omitted).
        """
        subject_result = self.subjectData.distinct(column, **kwds_filter)
        if not isinstance(required, _re_type):
            required = re.compile(required)
        func = lambda x: required.search(x) is not None

        invalid = subject_result.compare(func)
        if invalid:
            if not msg:
                msg = 'non-matching {0!r} values'.format(column)
            self.fail(msg=msg, differences=invalid)

    def assertDataNotRegex(self, column, required, msg=None, **kwds_filter):
        """Test that *column* in subjectData contains values that do
        **not** match a *required* regular expression::

            def test_name(self):
                bad_whitespace = r'^\s|\s$'  # Leading or trailing whitespace.
                self.assertDataNotRegex('name', bad_whitespace)

        The *required* argument must be a string or a compiled regular
        expression object (it can not be omitted).
        """
        subject_result = self.subjectData.distinct(column, **kwds_filter)
        if not isinstance(required, _re_type):
            required = re.compile(required)
        func = lambda x: required.search(x) is None

        invalid = subject_result.compare(func)
        if invalid:
            if not msg:
                msg = 'matching {0!r} values'.format(column)
            self.fail(msg=msg, differences=invalid)

    def allowOnly(self, differences, msg=None):
        """Context manager to allow specific *differences* without
        triggering a test failure::

            differences = [
                Extra('foo'),
                Missing('bar'),
            ]
            with self.allowOnly(differences):
                self.assertDataSet('column1')

        If the raised differences do not match *differences*, the test
        will fail with a DataAssertionError of the remaining
        differences.

        In the above example, *differences* is a list but it is also
        possible to pass a single difference or a dictionary.

        Using a single difference::

            with self.allowOnly(Extra('foo')):
                self.assertDataSet('column2')

        When using a dictionary, the keys are strings that provide
        context (for future reference and derived reports) and the
        values are the individual difference objects themselves::

            differences = {
                'Totals from state do not match totals from county.': [
                    Deviation(+436, 38032, town='Springfield'),
                    Deviation(-83, 8631, town='Union')
                ],
                'Some small towns were omitted from county report.': [
                    Deviation(-102, 102, town='Anderson'),
                    Deviation(-177, 177, town='Westfield')
                ]
            }
            with self.allowOnly(differences):
                self.assertDataSum('population', ['town'])
        """
        return _AllowOnly(differences, self, msg)

    def allowAny(self, number=None, msg=None, **kwds_filter):
        """Allows a given *number* of differences (of any kind) without
        triggering a test failure::

            with self.allowAny(10):  # Allows up to ten differences.
                self.assertDataSet('city_name')

        If *number* is omitted, allows an unlimited number of
        differences as long as they match a given keyword filter::

            with self.allowAny(city_name='not a city'):
                self.assertDataSum('population', ['city_name'])

        If the count of differences exceeds the given *number*, the
        test case will fail with a DataAssertionError containing all
        observed differences.
        """
        return _AllowAny(self, number, msg, **kwds_filter)

    def allowMissing(self, number=None, msg=None):
        """Context manager to allow for missing values without
        triggering a test failure::

            with self.allowMissing():  # Allows Missing differences.
                self.assertDataSet('column1')
        """
        return _AllowMissing(self, number, msg)

    def allowExtra(self, number=None, msg=None):
        """Context manager to allow for extra values without triggering
        a test failure::

            with self.allowExtra():  # Allows Extra differences.
                self.assertDataSet('column1')
        """
        return _AllowExtra(self, number, msg)

    def allowDeviation(self, lower, upper=None, msg=None, **kwds_filter):
        """
        allowDeviation(tolerance, /, msg=None, **kwds_filter)
        allowDeviation(lower, upper, msg=None, **kwds_filter)

        Context manager to allow for deviations from required
        numeric values without triggering a test failure.

        Allowing deviations of plus-or-minus a given *tolerance*::

            with self.allowDeviation(5):  # tolerance of +/- 5
                self.assertDataSum('column2', keys=['column1'])

        Specifying different *lower* and *upper* bounds::

            with self.allowDeviation(-2, 3):  # tolerance from -2 to +3
                self.assertDataSum('column2', keys=['column1'])

        All deviations within the accepted tolerance range are
        suppressed but those that exceed the range will trigger
        a test failure.
        """
        if msg == None and isinstance(upper, str):  # Adjust positional 'msg'
            upper, msg = None, upper                # for "tolerance" syntax.

        if upper == None:
            tolerance = lower
            assert tolerance >= 0, ('tolerance should not be negative, '
                                    'for full control of lower and upper '
                                    'bounds, use "lower, upper" syntax.')
            lower, upper = -tolerance, tolerance

        assert lower <= 0 <= upper
        return _AllowDeviation(lower, upper, self, msg, **kwds_filter)

    def allowPercentDeviation(self, deviation, msg=None, **kwds_filter):
        """Context manager to allow positive or negative numeric
        differences of less than or equal to the given *deviation* as a
        percentage of the matching reference value::

            with self.allowPercentDeviation(0.02):  # Allows +/- 2%
                self.assertDataSum('column2', keys=['column1'])

        If differences exceed *deviation*, the test case will fail with
        a DataAssertionError containing the excessive differences.
        """
        tolerance = _make_decimal(deviation)
        return _AllowPercentDeviation(deviation, self, msg, **kwds_filter)

    def fail(self, msg, differences=None):
        """Signals a test failure unconditionally, with *msg* for the
        error message.  If *differences* is provided, a
        DataAssertionError is raised instead of an AssertionError.
        """
        if differences:
            try:
                required = self.referenceData
            except NameError:
                required = None
            raise DataAssertionError(msg, differences, self.subjectData, required)
        else:
            raise self.failureException(msg)


# Prettify signature of DataTestCase.allowDeviation() by making "tolerance"
# syntax the default option when introspected.
try:
    _sig = inspect.signature(DataTestCase.allowDeviation)
    _self, _lower, _upper, _msg, _kwds_filter = _sig.parameters.values()
    _self = _self.replace(kind=inspect.Parameter.POSITIONAL_ONLY)
    _tolerance = inspect.Parameter('tolerance', inspect.Parameter.POSITIONAL_ONLY)
    _sig = _sig.replace(parameters=[_self, _tolerance, _msg, _kwds_filter])
    DataTestCase.allowDeviation.__signature__ = _sig
except AttributeError:  # Fails for Python 3.2 and earlier.
    pass
