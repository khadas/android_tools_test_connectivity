#!/usr/bin/env python3
#
# Copyright (C) 2018 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.
"""This script shows simple examples of how to get started with bluetooth
   low energy testing in acts.
"""

import pprint
import random
import time

from acts.controllers import android_device
from acts.test_utils.bt.BluetoothBaseTest import BluetoothBaseTest
from acts.test_utils.bt.bt_constants import adv_succ
from acts.test_utils.bt.bt_constants import scan_result
from acts.test_utils.bt.bt_test_utils import cleanup_scanners_and_advertisers
from acts.test_utils.bt.bt_test_utils import reset_bluetooth


class BleFuchsiaAndroidTest(BluetoothBaseTest):
    default_timeout = 10
    active_scan_callback_list = []
    active_adv_callback_list = []
    droid = None

    def __init__(self, controllers):
        BluetoothBaseTest.__init__(self, controllers)

        self.droid, self.droid_ed = (self.android_devices[0].droid,
                                     self.android_devices[0].ed)
        self.fuchsia = self.fuchsia_devices[0]
        self.log.info("There are: {} fuchsia and {} android devices.".format(
            len(self.fuchsia_devices), len(self.android_devices)))

    # An optional function. This overrides the default
    # on_exception in base_test. If the test throws an
    # unexpected exception, you can customise it.
    def on_exception(self, test_name, begin_time):
        self.log.debug(
            "Test {} failed. Gathering bugreport and btsnoop logs".format(
                test_name))
        android_devices.take_bug_reports(self.android_devices, test_name,
                                         begin_time)

    def teardown_test(self):
        self.fuchsia.clean_up()

    def _start_generic_advertisement_include_device_name(self):
        self.droid.bleSetAdvertiseDataIncludeDeviceName(True)
        advertise_data = self.droid.bleBuildAdvertiseData()
        advertise_settings = self.droid.bleBuildAdvertiseSettings()
        advertise_callback = self.droid.bleGenBleAdvertiseCallback()
        self.droid.bleStartBleAdvertising(advertise_callback, advertise_data,
                                          advertise_settings)
        self.droid_ed.pop_event(
            adv_succ.format(advertise_callback), self.default_timeout)
        self.active_adv_callback_list.append(advertise_callback)
        return advertise_callback

    # Basic test for android device as advertiser and fuchsia device as scanner
    # Returns True if scan result has an entry corresponding to sample_android_name
    @BluetoothBaseTest.bt_test_wrap
    def test_fuchsia_scan_android_adv(self):
        sample_android_name = "Pixel1234"
        self.droid.bluetoothSetLocalName(sample_android_name)
        adv_callback = self._start_generic_advertisement_include_device_name()
        droid_name = self.droid.bluetoothGetLocalName()
        self.log.info("Android device name: {}".format(droid_name))

        # Generate input params for command
        scan_time = 30000
        scan_filter = {"name_substring": "Pixel"}
        scan_count = 1
        scan_res = self.fuchsia.ble_lib.bleStartBleScan(
            scan_time, scan_filter, scan_count)

        # Get the result and validate
        self.log.info("Scan res: {}".format(scan_res))

        try:
            scan_res = scan_res["result"]
            #Validate result
            res = False
            for device in scan_res:
                name, did, connectable = device["name"], device["id"], device[
                    "connectable"]
                if (name):
                    self.log.info(
                        "Discovered device with name: {}".format(name))
                if (name == droid_name):
                    self.log.info(
                        "Successfully found android device advertising! name, id: {}, {}".
                        format(name, did))
                    res = True

        except:
            self.log.error("Failed to discovered android device")
            res = False

        #Print clients to validate results are saved
        self.fuchsia.print_clients()

        #Stop android advertising
        self.droid.bleStopBleAdvertising(adv_callback)

        return res

    # Test for fuchsia device attempting to connect to android device (peripheral)
    # Also tests the list_services and discconect to a peripheral
    @BluetoothBaseTest.bt_test_wrap
    def test_fuchsia_connect_android_periph(self):
        sample_android_name = "Pixel1234"
        self.droid.bluetoothSetLocalName(sample_android_name)
        adv_callback = self._start_generic_advertisement_include_device_name()
        droid_name = self.droid.bluetoothGetLocalName()
        self.log.info("Android device name: {}".format(droid_name))

        # Generate input params for command
        # Set scan time for 30 seconds (30,000 ms) and filter by android name
        # Resolve scan after device is found (scan_count = 1)
        scan_time_ms = 30000
        scan_filter = {"name_substring": droid_name}
        scan_count = 1
        scan_res = self.fuchsia.ble_lib.bleStartBleScan(
            scan_time_ms, scan_filter, scan_count)

        # Get the result and validate
        self.log.info("Scan res: {}".format(scan_res))

        try:
            scan_res = scan_res["result"]
            #Validate result
            res = False
            for device in scan_res:
                name, did, connectable = device["name"], device["id"], device[
                    "connectable"]
                if (name):
                    self.log.info(
                        "Discovered device with name: {}".format(name))
                if (name == droid_name):
                    self.log.info(
                        "Successfully found android device advertising! name, id: {}, {}".
                        format(name, did))
                    res = True

        except:
            self.log.error("Failed to discovered Android device")
            res = False

        connect = self.fuchsia.ble_lib.bleConnectToPeripheral(did)
        self.log.info("Connecting returned status: {}".format(connect))

        services = self.fuchsia.ble_lib.bleListServices(did)
        self.log.info("Listing services returned: {}".format(services))

        dconnect = self.fuchsia.ble_lib.bleDisconnectPeripheral(did)
        self.log.info("Disconnect status: {}".format(dconnect))

        #Print clients to validate results are saved
        self.fuchsia.print_clients()

        #Stop android advertising + cleanup sl4f
        self.droid.bleStopBleAdvertising(adv_callback)

        return res

    # Currently, this test doesn't work. The android device does not scan
    # TODO(): Debug android scan
    @BluetoothBaseTest.bt_test_wrap
    def test_fuchsia_adv_android_scan(self):
        #Initialize advertising on fuchsia device with name and interval
        fuchsia_name = "testADV123"
        adv_data = {"name": fuchsia_name}
        interval = 1000

        #Start advertising
        self.fuchsia.ble_lib.bleStartBleAdvertising(adv_data, interval)

        # Initialize scan on android device which scan settings + callback
        filter_list = self.droid.bleGenFilterList()
        self.droid.bleSetScanFilterDeviceName(fuchsia_name)
        scan_settings = self.droid.bleBuildScanSetting()
        scan_callback = self.droid.bleGenScanCallback()
        self.droid.bleBuildScanFilter(filter_list)
        self.droid.bleStartBleScan(filter_list, scan_settings, scan_callback)
        self.active_scan_callback_list.append(scan_callback)
        event_name = scan_result.format(scan_callback)
        try:
            event = self.droid.ed.pop_event(event_name, self.default_timeout)
            self.log.info("Found scan result: {}".format(
                pprint.pformat(event)))

            # Stop fuchsia advertise
            self.fuchsia.ble_lib.bleStopBleAdvertising()
        except Exception:
            self.log.error("Didn't find any scan results.")
            # Stop fuchsia advertise
            self.fuchsia.ble_lib.bleStopBleAdvertising()
            return False

        # TODO(): Validate result
        return True