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

import unittest

from acts.test_utils.instrumentation.config_wrapper import ConfigWrapper
from acts.test_utils.instrumentation.instrumentation_power_test \
    import ACCEPTANCE_THRESHOLD
from acts.test_utils.instrumentation.instrumentation_power_test \
    import InstrumentationPowerTest
from acts.test_utils.instrumentation.power_metrics import PowerMetrics

from acts import signals


class MockInstrumentationPowerTest(InstrumentationPowerTest):
    """Mock test class to initialize required attributes."""

    # avg: 2.214, stdev: 1.358, max: 4.78, min: 0.61
    SAMPLE_DATA = [1.64, 2.98, 1.72, 3.45, 1.31, 4.78, 3.43, 0.61, 1.19, 1.03]

    def __init__(self):
        self.current_test_name = 'test_case'
        self._power_metrics = PowerMetrics(4.2)
        self._power_metrics.test_metrics = {
            'instrTestCase': PowerMetrics(4.2)
        }
        self._power_metrics.test_metrics['instrTestCase'].generate_test_metrics(
            list(zip(range(10), self.SAMPLE_DATA))
        )
        self._instrumentation_config = ConfigWrapper(
            {
                self.__class__.__name__: {
                    self.current_test_name: {
                        ACCEPTANCE_THRESHOLD: {}
                    }
                }
            }
        )

    def set_criteria(self, criteria):
        """Set the acceptance criteria for metrics validation."""
        test_config = self._instrumentation_config[
            self.__class__.__name__][self.current_test_name]
        test_config[ACCEPTANCE_THRESHOLD] = ConfigWrapper(criteria)


class InstrumentationPowerTestTest(unittest.TestCase):
    """Unit tests for InstrumentationPowerTest."""
    def setUp(self):
        self.instrumentation_power_test = MockInstrumentationPowerTest()

    def test_validate_power_results_lower_and_upper_limit_accept(self):
        """Test that validate_power_results accept passing measurements
        given a lower and upper limit.
        """
        criteria_accept = {
            'avg_current': {
                'unit_type': 'current',
                'unit': 'A',
                'lower_limit': 0.0015,
                'upper_limit': 0.0025
            },
            'max_current': {
                'unit_type': 'current',
                'unit': 'mA',
                'upper_limit': 5
            }
        }
        self.instrumentation_power_test.set_criteria(criteria_accept)
        with self.assertRaises(signals.TestPass):
            self.instrumentation_power_test.validate_power_results(
                'instrTestCase')

    def test_validate_power_results_lower_and_upper_limit_reject(self):
        """Test that validate_power_results reject failing measurements
        given a lower and upper limit.
        """
        criteria_reject = {
            'avg_current': {
                'unit_type': 'current',
                'unit': 'A',
                'lower_limit': 0.0015,
                'upper_limit': 0.002
            },
            'max_current': {
                'unit_type': 'current',
                'unit': 'mA',
                'upper_limit': 4
            }
        }
        self.instrumentation_power_test.set_criteria(criteria_reject)
        with self.assertRaises(signals.TestFailure):
            self.instrumentation_power_test.validate_power_results(
                'instrTestCase')

    def test_validate_power_results_expected_value_and_deviation_accept(self):
        """Test that validate_power_results accept passing measurements
        given an expected value and percent deviation.
        """
        criteria_accept = {
            'stdev_current': {
                'unit_type': 'current',
                'unit': 'A',
                'expected_value': 0.0015,
                'percent_deviation': 20
            }
        }
        self.instrumentation_power_test.set_criteria(criteria_accept)
        with self.assertRaises(signals.TestPass):
            self.instrumentation_power_test.validate_power_results(
                'instrTestCase')

    def test_validate_power_results_expected_value_and_deviation_reject(self):
        """Test that validate_power_results reject failing measurements
        given an expected value and percent deviation.
        """
        criteria_reject = {
            'min_current': {
                'unit_type': 'current',
                'unit': 'mA',
                'expected_value': 0.5,
                'percent_deviation': 10
            }
        }
        self.instrumentation_power_test.set_criteria(criteria_reject)
        with self.assertRaises(signals.TestFailure):
            self.instrumentation_power_test.validate_power_results(
                'instrTestCase')

    def test_validate_power_results_no_such_metric(self):
        """Test that validate_power_results skip validation if the specified
        metric is invalid.
        """
        criteria_invalid_metric = {
            'no_such_metric': {
                'unit_type': 'current',
                'unit': 'A',
                'lower_limit': 0.005,
                'upper_limit': 0.007
            }
        }
        self.instrumentation_power_test.set_criteria(criteria_invalid_metric)
        with self.assertRaises(signals.TestPass):
            self.instrumentation_power_test.validate_power_results(
                'instrTestCase')

    def test_validate_power_results_criteria_missing_params(self):
        """Test that validate_power_results skip validation if the specified
        metric has missing parameters.
        """
        criteria_missing_params = {
            'avg_current': {
                'unit': 'A',
                'lower_limit': 0.001,
                'upper_limit': 0.002
            }
        }
        self.instrumentation_power_test.set_criteria(criteria_missing_params)
        with self.assertRaises(signals.TestPass):
            self.instrumentation_power_test.validate_power_results(
                'instrTestCase')


if __name__ == '__main__':
    unittest.main()
