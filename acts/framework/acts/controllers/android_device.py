#!/usr/bin/env python3.4
#
#   Copyright 2016 - The Android Open Source Project
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from builtins import str
from builtins import open

import logging
import os
import time

from acts import logger as acts_logger
from acts import signals
from acts import utils
from acts.controllers import adb
from acts.controllers import android
from acts.controllers import event_dispatcher
from acts.controllers import fastboot

ACTS_CONTROLLER_CONFIG_NAME = "AndroidDevice"
ACTS_CONTROLLER_REFERENCE_NAME = "android_devices"

ANDROID_DEVICE_PICK_ALL_TOKEN = "*"
# Key name for adb logcat extra params in config file.
ANDROID_DEVICE_ADB_LOGCAT_PARAM_KEY = "adb_logcat_param"
ANDROID_DEVICE_EMPTY_CONFIG_MSG = "Configuration is empty, abort!"
ANDROID_DEVICE_NOT_LIST_CONFIG_MSG = "Configuration should be a list, abort!"


class AndroidDeviceError(signals.ControllerError):
    pass


class DoesNotExistError(AndroidDeviceError):
    """Raised when something that does not exist is referenced.
    """


def create(configs):
    if not configs:
        raise AndroidDeviceError(ANDROID_DEVICE_EMPTY_CONFIG_MSG)
    elif configs == ANDROID_DEVICE_PICK_ALL_TOKEN:
        ads = get_all_instances()
    elif not isinstance(configs, list):
        raise AndroidDeviceError(ANDROID_DEVICE_NOT_LIST_CONFIG_MSG)
    elif isinstance(configs[0], str):
        # Configs is a list of serials.
        ads = get_instances(configs)
    else:
        # Configs is a list of dicts.
        ads = get_instances_with_configs(configs)
    connected_ads = list_adb_devices()
    active_ads = []

    for ad in ads:
        if ad.serial not in connected_ads:
            raise DoesNotExistError(("Android device %s is specified in config"
                                     " but is not attached.") % ad.serial)

    def _cleanup(msg, ad, active_ads):
        # This exception is logged here to help with debugging under py2,
        # because "exception raised while processing another exception" is
        # only printed under py3.
        logging.exception(msg)
        # Incrementally clean up subprocesses in current ad
        # before we continue
        if ad.adb_logcat_process:
            ad.stop_adb_logcat()
        if ad.ed:
            ad.ed.clean_up()
        # Clean up all already-active ads before bombing out
        destroy(active_ads)
        raise AndroidDeviceError(msg)

    for ad in ads:
        try:
            ad.start_adb_logcat()
        except:
            msg = "Failed to start logcat %s" % ad.serial
            _cleanup(msg, ad, active_ads)

        try:
            # TODO(angli): This is a temporary solution for tests that don't want
            # to require SL4A, which shall be replaced when b/29157104 is done.
            if not getattr(ad, "skip_sl4a", False):
                ad.get_droid()
                ad.ed.start()
        except:
            msg = "Failed to start sl4a on %s" % ad.serial
            _cleanup(msg, ad, active_ads)

        active_ads.append(ad)
    return ads


def destroy(ads):
    for ad in ads:
        try:
            ad.terminate_all_sessions()
        except:
            pass
        if ad.adb_logcat_process:
            ad.stop_adb_logcat()


def _parse_device_list(device_list_str, key):
    """Parses a byte string representing a list of devices. The string is
    generated by calling either adb or fastboot.

    Args:
        device_list_str: Output of adb or fastboot.
        key: The token that signifies a device in device_list_str.

    Returns:
        A list of android device serial numbers.
    """
    clean_lines = str(device_list_str, 'utf-8').strip().split('\n')
    results = []
    for line in clean_lines:
        tokens = line.strip().split('\t')
        if len(tokens) == 2 and tokens[1] == key:
            results.append(tokens[0])
    return results


def list_adb_devices():
    """List all android devices connected to the computer that are detected by
    adb.

    Returns:
        A list of android device serials. Empty if there's none.
    """
    out = adb.AdbProxy().devices()
    return _parse_device_list(out, "device")


def list_fastboot_devices():
    """List all android devices connected to the computer that are in in
    fastboot mode. These are detected by fastboot.

    Returns:
        A list of android device serials. Empty if there's none.
    """
    out = fastboot.FastbootProxy().devices()
    return _parse_device_list(out, "fastboot")


def get_instances(serials):
    """Create AndroidDevice instances from a list of serials.

    Args:
        serials: A list of android device serials.

    Returns:
        A list of AndroidDevice objects.
    """
    results = []
    for s in serials:
        results.append(AndroidDevice(s))
    return results


def get_instances_with_configs(configs):
    """Create AndroidDevice instances from a list of json configs.

    Each config should have the required key-value pair "serial".

    Args:
        configs: A list of dicts each representing the configuration of one
            android device.

    Returns:
        A list of AndroidDevice objects.
    """
    results = []
    for c in configs:
        try:
            serial = c.pop("serial")
        except KeyError:
            raise AndroidDeviceError(
                "Required value 'serial' is missing in AndroidDevice config %s."
                % c)
        ad = AndroidDevice(serial)
        ad.load_config(c)
        results.append(ad)
    return results


def get_all_instances(include_fastboot=False):
    """Create AndroidDevice instances for all attached android devices.

    Args:
        include_fastboot: Whether to include devices in bootloader mode or not.

    Returns:
        A list of AndroidDevice objects each representing an android device
        attached to the computer.
    """
    if include_fastboot:
        serial_list = list_adb_devices() + list_fastboot_devices()
        return get_instances(serial_list)
    return get_instances(list_adb_devices())


def filter_devices(ads, func):
    """Finds the AndroidDevice instances from a list that match certain
    conditions.

    Args:
        ads: A list of AndroidDevice instances.
        func: A function that takes an AndroidDevice object and returns True
            if the device satisfies the filter condition.

    Returns:
        A list of AndroidDevice instances that satisfy the filter condition.
    """
    results = []
    for ad in ads:
        if func(ad):
            results.append(ad)
    return results


def get_device(ads, **kwargs):
    """Finds a unique AndroidDevice instance from a list that has specific
    attributes of certain values.

    Example:
        get_device(android_devices, label="foo", phone_number="1234567890")
        get_device(android_devices, model="angler")

    Args:
        ads: A list of AndroidDevice instances.
        kwargs: keyword arguments used to filter AndroidDevice instances.

    Returns:
        The target AndroidDevice instance.

    Raises:
        AndroidDeviceError is raised if none or more than one device is
        matched.
    """

    def _get_device_filter(ad):
        for k, v in kwargs.items():
            if not hasattr(ad, k):
                return False
            elif getattr(ad, k) != v:
                return False
        return True

    filtered = filter_devices(ads, _get_device_filter)
    if not filtered:
        raise AndroidDeviceError(
            "Could not find a target device that matches condition: %s." %
            kwargs)
    elif len(filtered) == 1:
        return filtered[0]
    else:
        serials = [ad.serial for ad in filtered]
        raise AndroidDeviceError("More than one device matched: %s" % serials)


def take_bug_reports(ads, test_name, begin_time):
    """Takes bug reports on a list of android devices.

    If you want to take a bug report, call this function with a list of
    android_device objects in on_fail. But reports will be taken on all the
    devices in the list concurrently. Bug report takes a relative long
    time to take, so use this cautiously.

    Args:
        ads: A list of AndroidDevice instances.
        test_name: Name of the test case that triggered this bug report.
        begin_time: Logline format timestamp taken when the test started.
    """
    begin_time = acts_logger.normalize_log_line_timestamp(begin_time)

    def take_br(test_name, begin_time, ad):
        ad.take_bug_report(test_name, begin_time)

    args = [(test_name, begin_time, ad) for ad in ads]
    utils.concurrent_exec(take_br, args)


class AndroidDevice:
    """Class representing an android device.

    Each object of this class represents one Android device in ACTS, including
    handles to adb, fastboot, and sl4a clients. In addition to direct adb
    commands, this object also uses adb port forwarding to talk to the Android
    device.

    Attributes:
        serial: A string that's the serial number of the Androi device.
        h_port: An integer that's the port number for adb port forwarding used
                on the computer the Android device is connected
        d_port: An integer  that's the port number used on the Android device
                for adb port forwarding.
        log_path: A string that is the path where all logs collected on this
                  android device should be stored.
        log: A logger adapted from root logger with added token specific to an
             AndroidDevice instance.
        adb_logcat_process: A process that collects the adb logcat.
        adb_logcat_file_path: A string that's the full path to the adb logcat
                              file collected, if any.
        adb: An AdbProxy object used for interacting with the device via adb.
        fastboot: A FastbootProxy object used for interacting with the device
                  via fastboot.
    """

    def __init__(self, serial="", host_port=None, device_port=8080):
        self.serial = serial
        self.h_port = host_port
        self.d_port = device_port
        # logging.log_path only exists when this is used in an ACTS test run.
        log_path_base = getattr(logging, "log_path", "/tmp/logs")
        self.log_path = os.path.join(log_path_base, "AndroidDevice%s" % serial)
        self.log = AndroidDeviceLoggerAdapter(logging.getLogger(),
                                              {"serial": self.serial})
        self._droid_sessions = {}
        self._event_dispatchers = {}
        self.adb_logcat_process = None
        self.adb_logcat_file_path = None
        self.adb = adb.AdbProxy(serial)
        self.fastboot = fastboot.FastbootProxy(serial)
        if not self.is_bootloader:
            self.root_adb()

    def __del__(self):
        if self.h_port:
            self.adb.forward("--remove tcp:%d" % self.h_port)
        if self.adb_logcat_process:
            self.stop_adb_logcat()

    @property
    def is_bootloader(self):
        """True if the device is in bootloader mode.
        """
        return self.serial in list_fastboot_devices()

    @property
    def is_adb_root(self):
        """True if adb is running as root for this device.
        """
        return "root" in self.adb.shell("id -u").decode("utf-8")

    @property
    def model(self):
        """The Android code name for the device.
        """
        # If device is in bootloader mode, get mode name from fastboot.
        if self.is_bootloader:
            out = self.fastboot.getvar("product").strip()
            # "out" is never empty because of the "total time" message fastboot
            # writes to stderr.
            lines = out.decode("utf-8").split('\n', 1)
            if lines:
                tokens = lines[0].split(' ')
                if len(tokens) > 1:
                    return tokens[1].lower()
            return None
        out = self.adb.shell('getprop | grep ro.build.product')
        model = out.decode("utf-8").strip().split('[')[-1][:-1].lower()
        if model == "sprout":
            return model
        else:
            out = self.adb.shell('getprop | grep ro.product.name')
            model = out.decode("utf-8").strip().split('[')[-1][:-1].lower()
            return model

    @property
    def droid(self):
        """The first sl4a session initiated on this device. None if there isn't
        one.
        """
        try:
            session_id = sorted(self._droid_sessions)[0]
            return self._droid_sessions[session_id][0]
        except IndexError:
            return None

    @property
    def ed(self):
        """The first event_dispatcher instance created on this device. None if
        there isn't one.
        """
        try:
            session_id = sorted(self._event_dispatchers)[0]
            return self._event_dispatchers[session_id]
        except IndexError:
            return None

    @property
    def droids(self):
        """A list of the active sl4a sessions on this device.

        If multiple connections exist for the same session, only one connection
        is listed.
        """
        keys = sorted(self._droid_sessions)
        results = []
        for k in keys:
            results.append(self._droid_sessions[k][0])
        return results

    @property
    def eds(self):
        """A list of the event_dispatcher objects on this device.

        The indexing of the list matches that of the droids property.
        """
        keys = sorted(self._event_dispatchers)
        results = []
        for k in keys:
            results.append(self._event_dispatchers[k])
        return results

    @property
    def is_adb_logcat_on(self):
        """Whether there is an ongoing adb logcat collection.
        """
        if self.adb_logcat_process:
            return True
        return False

    def load_config(self, config):
        """Add attributes to the AndroidDevice object based on json config.

        Args:
            config: A dictionary representing the configs.

        Raises:
            AndroidDeviceError is raised if the config is trying to overwrite
            an existing attribute.
        """
        for k, v in config.items():
            if hasattr(self, k):
                raise AndroidDeviceError(
                    "Attempting to set existing attribute %s on %s" %
                    (k, self.serial))
            setattr(self, k, v)

    def root_adb(self):
        """Change adb to root mode for this device.
        """
        if not self.is_adb_root:
            self.adb.root()
            self.adb.wait_for_device()
            self.adb.remount()
            self.adb.wait_for_device()

    def get_droid(self, handle_event=True):
        """Create an sl4a connection to the device.

        Return the connection handler 'droid'. By default, another connection
        on the same session is made for EventDispatcher, and the dispatcher is
        returned to the caller as well.
        If sl4a server is not started on the device, try to start it.

        Args:
            handle_event: True if this droid session will need to handle
                events.

        Returns:
            droid: Android object used to communicate with sl4a on the android
                device.
            ed: An optional EventDispatcher to organize events for this droid.

        Examples:
            Don't need event handling:
            >>> ad = AndroidDevice()
            >>> droid = ad.get_droid(False)

            Need event handling:
            >>> ad = AndroidDevice()
            >>> droid, ed = ad.get_droid()
        """
        if not self.h_port or not adb.is_port_available(self.h_port):
            self.h_port = adb.get_available_host_port()
        self.adb.tcp_forward(self.h_port, self.d_port)
        try:
            droid = self.start_new_session()
        except:
            self.adb.start_sl4a()
            droid = self.start_new_session()
        if handle_event:
            ed = self.get_dispatcher(droid)
            return droid, ed
        return droid

    def get_dispatcher(self, droid):
        """Return an EventDispatcher for an sl4a session

        Args:
            droid: Session to create EventDispatcher for.

        Returns:
            ed: An EventDispatcher for specified session.
        """
        ed_key = self.serial + str(droid.uid)
        if ed_key in self._event_dispatchers:
            if self._event_dispatchers[ed_key] is None:
                raise AndroidDeviceError("EventDispatcher Key Empty")
            self.log.debug("Returning existing key %s for event dispatcher!",
                           ed_key)
            return self._event_dispatchers[ed_key]
        event_droid = self.add_new_connection_to_session(droid.uid)
        ed = event_dispatcher.EventDispatcher(event_droid)
        self._event_dispatchers[ed_key] = ed
        return ed

    def _is_timestamp_in_range(self, target, begin_time, end_time):
        low = acts_logger.logline_timestamp_comparator(begin_time, target) <= 0
        high = acts_logger.logline_timestamp_comparator(end_time, target) >= 0
        return low and high

    def cat_adb_log(self, tag, begin_time):
        """Takes an excerpt of the adb logcat log from a certain time point to
        current time.

        Args:
            tag: An identifier of the time period, usualy the name of a test.
            begin_time: Logline format timestamp of the beginning of the time
                period.
        """
        if not self.adb_logcat_file_path:
            raise AndroidDeviceError(
                ("Attempting to cat adb log when none has"
                 " been collected on Android device %s.") % self.serial)
        end_time = acts_logger.get_log_line_timestamp()
        self.log.debug("Extracting adb log from logcat.")
        adb_excerpt_path = os.path.join(self.log_path, "AdbLogExcerpts")
        utils.create_dir(adb_excerpt_path)
        f_name = os.path.basename(self.adb_logcat_file_path)
        out_name = f_name.replace("adblog,", "").replace(".txt", "")
        out_name = ",{},{}.txt".format(begin_time, out_name)
        tag_len = utils.MAX_FILENAME_LEN - len(out_name)
        tag = tag[:tag_len]
        out_name = tag + out_name
        full_adblog_path = os.path.join(adb_excerpt_path, out_name)
        with open(full_adblog_path, 'w', encoding='utf-8') as out:
            in_file = self.adb_logcat_file_path
            with open(in_file, 'r', encoding='utf-8', errors='replace') as f:
                in_range = False
                while True:
                    line = None
                    try:
                        line = f.readline()
                        if not line:
                            break
                    except:
                        continue
                    line_time = line[:acts_logger.log_line_timestamp_len]
                    if not acts_logger.is_valid_logline_timestamp(line_time):
                        continue
                    if self._is_timestamp_in_range(line_time, begin_time,
                                                   end_time):
                        in_range = True
                        if not line.endswith('\n'):
                            line += '\n'
                        out.write(line)
                    else:
                        if in_range:
                            break

    def start_adb_logcat(self):
        """Starts a standing adb logcat collection in separate subprocesses and
        save the logcat in a file.
        """
        if self.is_adb_logcat_on:
            raise AndroidDeviceError(("Android device {} already has an adb "
                                      "logcat thread going on. Cannot start "
                                      "another one.").format(self.serial))
        # Disable adb log spam filter.
        self.adb.shell("logpersist.start")
        f_name = "adblog,{},{}.txt".format(self.model, self.serial)
        utils.create_dir(self.log_path)
        logcat_file_path = os.path.join(self.log_path, f_name)
        try:
            extra_params = self.adb_logcat_param
        except AttributeError:
            extra_params = "-b all"
        cmd = "adb -s {} logcat -v threadtime {} >> {}".format(
            self.serial, extra_params, logcat_file_path)
        self.adb_logcat_process = utils.start_standing_subprocess(cmd)
        self.adb_logcat_file_path = logcat_file_path

    def stop_adb_logcat(self):
        """Stops the adb logcat collection subprocess.
        """
        if not self.is_adb_logcat_on:
            raise AndroidDeviceError(
                "Android device %s does not have an ongoing adb logcat collection."
                % self.serial)
        utils.stop_standing_subprocess(self.adb_logcat_process)
        self.adb_logcat_process = None

    def take_bug_report(self, test_name, begin_time):
        """Takes a bug report on the device and stores it in a file.

        Args:
            test_name: Name of the test case that triggered this bug report.
            begin_time: Logline format timestamp taken when the test started.
        """
        new_br = True
        try:
            self.adb.shell("bugreportz -v")
        except adb.AdbError:
            new_br = False
        br_path = os.path.join(self.log_path, "BugReports")
        utils.create_dir(br_path)
        base_name = ",{},{}.txt".format(begin_time, self.serial)
        if new_br:
            base_name = base_name.replace(".txt", ".zip")
        test_name_len = utils.MAX_FILENAME_LEN - len(base_name)
        out_name = test_name[:test_name_len] + base_name
        full_out_path = os.path.join(br_path, out_name.replace(' ', '\ '))
        # in case device restarted, wait for adb interface to return
        self.wait_for_boot_completion()
        self.log.info("Taking bugreport for %s.", test_name)
        if new_br:
            out = self.adb.shell("bugreportz").decode("utf-8")
            if not out.startswith("OK"):
                raise AndroidDeviceError("Failed to take bugreport on %s" %
                                         self.serial)
            br_out_path = out.split(':')[1].strip()
            self.adb.pull("%s %s" % (br_out_path, full_out_path))
        else:
            self.adb.bugreport(" > {}".format(full_out_path))
        self.log.info("Bugreport for %s taken at %s.", test_name,
                      full_out_path)

    def start_new_session(self):
        """Start a new session in sl4a.

        Also caches the droid in a dict with its uid being the key.

        Returns:
            An Android object used to communicate with sl4a on the android
                device.

        Raises:
            SL4AException: Something is wrong with sl4a and it returned an
            existing uid to a new session.
        """
        droid = android.Android(port=self.h_port)
        if droid.uid in self._droid_sessions:
            raise android.SL4AException(
                "SL4A returned an existing uid for a new session. Abort.")
        self._droid_sessions[droid.uid] = [droid]
        return droid

    def add_new_connection_to_session(self, session_id):
        """Create a new connection to an existing sl4a session.

        Args:
            session_id: UID of the sl4a session to add connection to.

        Returns:
            An Android object used to communicate with sl4a on the android
                device.

        Raises:
            DoesNotExistError: Raised if the session it's trying to connect to
            does not exist.
        """
        if session_id not in self._droid_sessions:
            raise DoesNotExistError("Session %d doesn't exist." % session_id)
        droid = android.Android(cmd='continue',
                                uid=session_id,
                                port=self.h_port)
        return droid

    def terminate_session(self, session_id):
        """Terminate a session in sl4a.

        Send terminate signal to sl4a server; stop dispatcher associated with
        the session. Clear corresponding droids and dispatchers from cache.

        Args:
            session_id: UID of the sl4a session to terminate.
        """
        if self._droid_sessions and (session_id in self._droid_sessions):
            for droid in self._droid_sessions[session_id]:
                droid.closeSl4aSession()
                droid.close()
            del self._droid_sessions[session_id]
        ed_key = self.serial + str(session_id)
        if ed_key in self._event_dispatchers:
            self._event_dispatchers[ed_key].clean_up()
            del self._event_dispatchers[ed_key]

    def terminate_all_sessions(self):
        """Terminate all sl4a sessions on the AndroidDevice instance.

        Terminate all sessions and clear caches.
        """
        if self._droid_sessions:
            session_ids = list(self._droid_sessions.keys())
            for session_id in session_ids:
                try:
                    self.terminate_session(session_id)
                except:
                    self.log.exception("Failed to terminate session %d.",
                                       session_id)
            if self.h_port:
                self.adb.forward("--remove tcp:%d" % self.h_port)
                self.h_port = None

    def run_iperf_client(self, server_host, extra_args=""):
        """Start iperf client on the device.

        Return status as true if iperf client start successfully.
        And data flow information as results.

        Args:
            server_host: Address of the iperf server.
            extra_args: A string representing extra arguments for iperf client,
                e.g. "-i 1 -t 30".

        Returns:
            status: true if iperf client start successfully.
            results: results have data flow information
        """
        out = self.adb.shell("iperf3 -c {} {}".format(server_host, extra_args))
        clean_out = str(out, 'utf-8').strip().split('\n')
        if "error" in clean_out[0].lower():
            return False, clean_out
        return True, clean_out

    def run_iperf_server(self, extra_args=""):
        """Start iperf server on the device

        Return status as true if iperf server started successfully.

        Args:
            extra_args: A string representing extra arguments for iperf server.

        Returns:
            status: true if iperf server started successfully.
            results: results have output of command
        """
        out = self.adb.shell("iperf3 -s {}".format(extra_args))
        clean_out = str(out,'utf-8').strip().split('\n')
        if "error" in clean_out[0].lower():
            return False, clean_out
        return True, clean_out

    def wait_for_boot_completion(self):
        """Waits for Android framework to broadcast ACTION_BOOT_COMPLETED.

        This function times out after 15 minutes.
        """
        timeout_start = time.time()
        timeout = 15 * 60

        self.adb.wait_for_device()
        while time.time() < timeout_start + timeout:
            try:
                out = self.adb.shell("getprop sys.boot_completed")
                completed = out.decode('utf-8').strip()
                if completed == '1':
                    return
            except adb.AdbError:
                # adb shell calls may fail during certain period of booting
                # process, which is normal. Ignoring these errors.
                pass
            time.sleep(5)
        raise AndroidDeviceError("Device %s booting process timed out." %
                                 self.serial)

    def reboot(self):
        """Reboots the device.

        Terminate all sl4a sessions, reboot the device, wait for device to
        complete booting, and restart an sl4a session.

        This is a blocking method.

        This is probably going to print some error messages in console. Only
        use if there's no other option.

        Example:
            droid, ed = ad.reboot()

        Returns:
            An sl4a session with an event_dispatcher.

        Raises:
            AndroidDeviceError is raised if waiting for completion timed
            out.
        """
        if self.is_bootloader:
            self.fastboot.reboot()
            return
        has_adb_log = self.is_adb_logcat_on
        if has_adb_log:
            self.stop_adb_logcat()
        self.terminate_all_sessions()
        self.adb.reboot()
        self.wait_for_boot_completion()
        self.root_adb()
        droid, ed = self.get_droid()
        ed.start()
        if has_adb_log:
            self.start_adb_logcat()
        return droid, ed


class AndroidDeviceLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        msg = "[AndroidDevice|%s] %s" % (self.extra["serial"], msg)
        return (msg, kwargs)
