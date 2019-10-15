#!/usr/bin/env python3
#
#   Copyright 2019 - The Android Open Source Project
#
#   Licensed under the Apache License, Version 2.0 (the 'License');
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an 'AS IS' BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import bisect
import math

import numpy as np
from acts.test_utils.instrumentation import instrumentation_proto_parser \
    as parser

# Unit type constants
CURRENT = 'current'
POWER = 'power'
TIME = 'time'

# Unit constants
MILLIAMP = 'mA'
AMP = 'A'
AMPERE = AMP
MILLIWATT = 'mW'
WATT = 'W'
MILLISECOND = 'ms'
SECOND = 's'
MINUTE = 'm'
HOUR = 'h'

CONVERSION_TABLES = {
    CURRENT: {
        MILLIAMP: 0.001,
        AMP: 1
    },
    POWER: {
        MILLIWATT: 0.001,
        WATT: 1
    },
    TIME: {
        MILLISECOND: 0.001,
        SECOND: 1,
        MINUTE: 60,
        HOUR: 3600
    }
}


class Measurement(object):
    """Base class for describing power measurement values. Each object contains
    an value and a unit. Enables some basic arithmetic operations with other
    measurements of the same unit type.

    Attributes:
        _value: Numeric value of the measurement
        _unit_type: Unit type of the measurement (e.g. current, power)
        _unit: Unit of the measurement (e.g. W, mA)
    """

    def __init__(self, value, unit_type, unit):
        if unit_type not in CONVERSION_TABLES:
            raise TypeError('%s is not a valid unit type' % unit_type)
        self._value = value
        self._unit_type = unit_type
        self._unit = unit

    # Convenience constructor methods
    @staticmethod
    def amps(amps):
        """Create a new current measurement, in amps."""
        return Measurement(amps, CURRENT, AMP)

    @staticmethod
    def watts(watts):
        """Create a new power measurement, in watts."""
        return Measurement(watts, POWER, WATT)

    @staticmethod
    def seconds(seconds):
        """Create a new time measurement, in seconds."""
        return Measurement(seconds, TIME, SECOND)

    # Comparison methods

    def __eq__(self, other):
        return self.value == other.to_unit(self._unit).value

    def __lt__(self, other):
        return self.value < other.to_unit(self._unit).value

    def __le__(self, other):
        return self == other or self < other

    # Addition and subtraction with other measurements

    def __add__(self, other):
        """Adds measurements of compatible unit types. The result will be in the
        same units as self.
        """
        return Measurement(self.value + other.to_unit(self._unit).value,
                           self._unit_type, self._unit)

    def __sub__(self, other):
        """Subtracts measurements of compatible unit types. The result will be
        in the same units as self.
        """
        return Measurement(self.value - other.to_unit(self._unit).value,
                           self._unit_type, self._unit)

    # String representation

    def __str__(self):
        return '%g%s' % (self._value, self._unit)

    def __repr__(self):
        return str(self)

    @property
    def value(self):
        return self._value

    def to_unit(self, new_unit):
        """Create an equivalent measurement under a different unit.
        e.g. 0.5W -> 500mW

        Args:
            new_unit: Target unit. Must be compatible with current unit.

        Returns: A new measurement with the converted value and unit.
        """
        try:
            new_value = self._value * (
                    CONVERSION_TABLES[self._unit_type][self._unit] /
                    CONVERSION_TABLES[self._unit_type][new_unit])
        except KeyError:
            raise TypeError('Incompatible units: %s, %s' %
                            (self._unit, new_unit))
        return Measurement(new_value, self._unit_type, new_unit)


class PowerMetrics(object):
    """Class for processing raw power metrics generated by Monsoon measurements.
    Provides useful metrics such as average current, max current, and average
    power. Can generate individual test metrics.

    See section "Numeric metrics" below for available metrics.
    """

    def __init__(self, voltage, start_time=0):
        """Create a PowerMetrics.

        Args:
            voltage: Voltage of the measurement
            start_time: Start time of the measurement. Used for generating
                test-specific metrics.
        """
        self._voltage = voltage
        self._start_time = start_time
        self._num_samples = 0
        self._sum_currents = 0
        self._sum_squares = 0
        self._max_current = None
        self._min_current = None
        self.test_metrics = {}

    @staticmethod
    def import_raw_data(path):
        """Create a generator from a Monsoon data file.

        Args:
            path: path to raw data file

        Returns: generator that yields (timestamp, sample) per line
        """
        with open(path, 'r') as f:
            for line in f:
                time, sample = line.split()
                yield float(time[:-1]), float(sample)

    def update_metrics(self, sample):
        """Update the running metrics with the current sample.

        Args:
            sample: A current sample.
        """
        self._num_samples += 1
        self._sum_currents += sample
        self._sum_squares += sample ** 2
        if self._max_current is None or sample > self._max_current:
            self._max_current = sample
        if self._min_current is None or sample < self._min_current:
            self._min_current = sample

    def generate_test_metrics(self, raw_data, test_timestamps=None):
        """Split the data into individual test metrics, based on the timestamps
        given as a dict.

        Args:
            raw_data: raw data as list or generator of (timestamp, sample)
            test_timestamps: dict following the output format of
                instrumentation_proto_parser.get_test_timestamps()
        """

        # Initialize metrics for each test
        if test_timestamps is None:
            test_timestamps = {}
        test_starts = {}
        test_ends = {}
        for test_name, times in test_timestamps.items():
            self.test_metrics[test_name] = PowerMetrics(
                self._voltage, self._start_time)
            test_starts[test_name] = Measurement(
                times[parser.START_TIMESTAMP], TIME, MILLISECOND)\
                .to_unit(SECOND).value - self._start_time
            test_ends[test_name] = Measurement(
                times[parser.END_TIMESTAMP], TIME, MILLISECOND)\
                .to_unit(SECOND).value - self._start_time

        # Assign data to tests based on timestamps
        for timestamp, sample in raw_data:
            self.update_metrics(sample)
            for test_name in test_timestamps:
                if test_starts[test_name] <= timestamp <= test_ends[test_name]:
                    self.test_metrics[test_name].update_metrics(sample)

    # Numeric metrics

    ALL_METRICS = ('avg_current', 'max_current', 'min_current', 'stdev_current',
                   'avg_power')

    @property
    def avg_current(self):
        """Average current, in amps."""
        if not self._num_samples:
            return Measurement.amps(0)
        return Measurement.amps(self._sum_currents / self._num_samples)

    @property
    def max_current(self):
        """Max current, in amps."""
        return Measurement.amps(self._max_current or 0)

    @property
    def min_current(self):
        """Min current, in amps."""
        return Measurement.amps(self._min_current or 0)

    @property
    def stdev_current(self):
        """Standard deviation of current values, in amps."""
        if self._num_samples < 2:
            return Measurement.amps(0)

        return Measurement.amps(math.sqrt(
            (self._sum_squares - (
                    self._num_samples * self.avg_current.value ** 2))
            / (self._num_samples - 1)))

    def current_to_power(self, current):
        """Converts a current value to a power value."""
        return Measurement.watts(current.to_unit(AMP).value * self._voltage)

    @property
    def avg_power(self):
        """Average power, in watts."""
        return self.current_to_power(self.avg_current)

    @property
    def summary(self):
        """A summary of test metrics"""
        return {'average_current': str(self.avg_current),
                'max_current': str(self.max_current),
                'average_power': str(self.avg_power)}
