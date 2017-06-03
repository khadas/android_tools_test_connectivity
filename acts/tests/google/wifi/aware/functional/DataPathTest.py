#!/usr/bin/python3.4
#
#   Copyright 2017 - The Android Open Source Project
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

import time

from acts.test_utils.net import connectivity_const as cconsts
from acts.test_utils.wifi.aware import aware_const as aconsts
from acts.test_utils.wifi.aware import aware_test_utils as autils
from acts.test_utils.wifi.aware.AwareBaseTest import AwareBaseTest


class DataPathTest(AwareBaseTest):
  """Set of tests for Wi-Fi Aware discovery."""

  # configuration parameters used by tests
  ENCR_TYPE_OPEN = 0
  ENCR_TYPE_PASSPHRASE = 1

  PASSPHRASE = "This is some random passphrase - very very secure!!"

  PING_MSG = "ping"

  # message re-transmit counter (increases reliability in open-environment)
  # Note: reliability of message transmission is tested elsewhere
  MSG_RETX_COUNT = 5  # hard-coded max value, internal API

  def __init__(self, controllers):
    AwareBaseTest.__init__(self, controllers)

  def create_config(self, dtype):
    """Create a base configuration based on input parameters.

    Args:
      dtype: Publish or Subscribe discovery type

    Returns:
      Discovery configuration object.
    """
    config = {}
    config[aconsts.DISCOVERY_KEY_DISCOVERY_TYPE] = dtype
    config[aconsts.DISCOVERY_KEY_SERVICE_NAME] = "GoogleTestServiceDataPath"
    return config

  def request_network(self, dut, ns):
    """Request a Wi-Fi Aware network.

    Args:
      dut: Device
      ns: Network specifier
    Returns: the request key
    """
    network_req = {"TransportType": 5, "NetworkSpecifier": ns}
    return dut.droid.connectivityRequestWifiAwareNetwork(network_req)

  def run_ib_data_path_test(self, ptype, stype, encr_type, use_peer_id):
    """Runs the in-band data-path tests.

    Args:
      ptype: Publish discovery type
      stype: Subscribe discovery type
      encr_type: Encryption type, one of ENCR_TYPE_*
      use_peer_id: On Responder (publisher): True to use peer ID, False to
                   accept any request
    """
    p_dut = self.android_devices[0]
    p_dut.pretty_name = "Publisher"
    s_dut = self.android_devices[1]
    s_dut.pretty_name = "Subscriber"

    # Publisher+Subscriber: attach and wait for confirmation
    p_id = p_dut.droid.wifiAwareAttach()
    autils.wait_for_event(p_dut, aconsts.EVENT_CB_ON_ATTACHED)
    s_id = s_dut.droid.wifiAwareAttach()
    autils.wait_for_event(s_dut, aconsts.EVENT_CB_ON_ATTACHED)

    # Publisher: start publish and wait for confirmation
    p_disc_id = p_dut.droid.wifiAwarePublish(p_id, self.create_config(ptype))
    autils.wait_for_event(p_dut, aconsts.SESSION_CB_ON_PUBLISH_STARTED)

    # Subscriber: start subscribe and wait for confirmation
    s_disc_id = s_dut.droid.wifiAwareSubscribe(s_id, self.create_config(stype))
    autils.wait_for_event(s_dut, aconsts.SESSION_CB_ON_SUBSCRIBE_STARTED)

    # Subscriber: wait for service discovery
    discovery_event = autils.wait_for_event(
        s_dut, aconsts.SESSION_CB_ON_SERVICE_DISCOVERED)
    peer_id_on_sub = discovery_event["data"][aconsts.SESSION_CB_KEY_PEER_ID]

    if use_peer_id: # only need message to receive peer ID
      # Subscriber: send message to peer (Publisher - so it knows our address)
      s_dut.droid.wifiAwareSendMessage(s_disc_id, peer_id_on_sub,
                                       self.get_next_msg_id(), self.PING_MSG,
                                       self.MSG_RETX_COUNT)
      autils.wait_for_event(s_dut, aconsts.SESSION_CB_ON_MESSAGE_SENT)

      # Publisher: wait for received message
      pub_rx_msg_event = autils.wait_for_event(
          p_dut, aconsts.SESSION_CB_ON_MESSAGE_RECEIVED)
      peer_id_on_pub = pub_rx_msg_event["data"][aconsts.SESSION_CB_KEY_PEER_ID]

    # Publisher: request network
    p_req_key = self.request_network(
        p_dut,
        p_dut.droid.wifiAwareCreateNetworkSpecifier(
            p_disc_id, peer_id_on_pub if use_peer_id else None, self.PASSPHRASE
            if encr_type == self.ENCR_TYPE_PASSPHRASE else None))

    # Subscriber: request network
    s_req_key = self.request_network(
        s_dut,
        s_dut.droid.wifiAwareCreateNetworkSpecifier(
            s_disc_id, peer_id_on_sub, self.PASSPHRASE
            if encr_type == self.ENCR_TYPE_PASSPHRASE else None))

    # Publisher & Subscriber: wait for network formation
    p_net_event = autils.wait_for_event_with_keys(
        p_dut, cconsts.EVENT_NETWORK_CALLBACK,
        autils.EVENT_TIMEOUT,
        (cconsts.NETWORK_CB_KEY_EVENT,
         cconsts.NETWORK_CB_LINK_PROPERTIES_CHANGED),
        (cconsts.NETWORK_CB_KEY_ID, p_req_key))
    s_net_event = autils.wait_for_event_with_keys(
        s_dut, cconsts.EVENT_NETWORK_CALLBACK,
        autils.EVENT_TIMEOUT,
        (cconsts.NETWORK_CB_KEY_EVENT,
         cconsts.NETWORK_CB_LINK_PROPERTIES_CHANGED),
        (cconsts.NETWORK_CB_KEY_ID, s_req_key))

    p_aware_if = p_net_event["data"][cconsts.NETWORK_CB_KEY_INTERFACE_NAME]
    s_aware_if = s_net_event["data"][cconsts.NETWORK_CB_KEY_INTERFACE_NAME]
    self.log.info("Interface names: p=%s, s=%s", p_aware_if, s_aware_if)

    p_ipv6 = p_dut.droid.connectivityGetLinkLocalIpv6Address(p_aware_if).split(
        "%")[0]
    s_ipv6 = s_dut.droid.connectivityGetLinkLocalIpv6Address(s_aware_if).split(
        "%")[0]
    self.log.info("Interface addresses (IPv6): p=%s, s=%s", p_ipv6, s_ipv6)

    # TODO: possibly send messages back and forth, prefer to use netcat/nc

    # clean-up
    p_dut.droid.connectivityUnregisterNetworkCallback(p_req_key)
    s_dut.droid.connectivityUnregisterNetworkCallback(s_req_key)

  #######################################
  # Positive In-Band (IB) tests key:
  #
  # names is: test_ib_<pub_type>_<sub_type>_<encr_type>_<peer_spec>
  # where:
  #
  # pub_type: Type of publish discovery session: unsolicited or solicited.
  # sub_type: Type of subscribe discovery session: passive or active.
  # encr_type: Encription type: open, passphrase
  # peer_spec: Peer specification method: any or specific
  #
  # Note: In-Band means using Wi-Fi Aware for discovery and referring to the
  # peer using the Aware-provided peer handle (as opposed to a MAC address).
  #######################################

  def test_ib_unsolicited_passive_open_specific(self):
    """Data-path: in-band, unsolicited/passive, open encryption, specific peer

    Verifies end-to-end discovery + data-path creation.
    """
    self.run_ib_data_path_test(
        ptype=aconsts.PUBLISH_TYPE_UNSOLICITED,
        stype=aconsts.SUBSCRIBE_TYPE_PASSIVE,
        encr_type=self.ENCR_TYPE_OPEN,
        use_peer_id=True)

  def test_ib_unsolicited_passive_open_any(self):
    """Data-path: in-band, unsolicited/passive, open encryption, any peer

    Verifies end-to-end discovery + data-path creation.
    """
    self.run_ib_data_path_test(
        ptype=aconsts.PUBLISH_TYPE_UNSOLICITED,
        stype=aconsts.SUBSCRIBE_TYPE_PASSIVE,
        encr_type=self.ENCR_TYPE_OPEN,
        use_peer_id=False)

  def test_ib_unsolicited_passive_passphrase_specific(self):
    """Data-path: in-band, unsolicited/passive, passphrase, specific peer

    Verifies end-to-end discovery + data-path creation.
    """
    self.run_ib_data_path_test(
        ptype=aconsts.PUBLISH_TYPE_UNSOLICITED,
        stype=aconsts.SUBSCRIBE_TYPE_PASSIVE,
        encr_type=self.ENCR_TYPE_PASSPHRASE,
        use_peer_id=True)

  def test_ib_unsolicited_passive_passphrase_any(self):
    """Data-path: in-band, unsolicited/passive, passphrase, any peer

    Verifies end-to-end discovery + data-path creation.
    """
    self.run_ib_data_path_test(
        ptype=aconsts.PUBLISH_TYPE_UNSOLICITED,
        stype=aconsts.SUBSCRIBE_TYPE_PASSIVE,
        encr_type=self.ENCR_TYPE_PASSPHRASE,
        use_peer_id=False)

  def test_ib_solicited_active_open_specific(self):
      """Data-path: in-band, solicited/active, open encryption, specific peer

      Verifies end-to-end discovery + data-path creation.
      """
      self.run_ib_data_path_test(
          ptype=aconsts.PUBLISH_TYPE_SOLICITED,
          stype=aconsts.SUBSCRIBE_TYPE_ACTIVE,
          encr_type=self.ENCR_TYPE_OPEN,
          use_peer_id=True)

  def test_ib_solicited_active_open_any(self):
      """Data-path: in-band, solicited/active, open encryption, any peer

      Verifies end-to-end discovery + data-path creation.
      """
      self.run_ib_data_path_test(
          ptype=aconsts.PUBLISH_TYPE_SOLICITED,
          stype=aconsts.SUBSCRIBE_TYPE_ACTIVE,
          encr_type=self.ENCR_TYPE_OPEN,
          use_peer_id=False)

  def test_ib_solicited_active_passphrase_specific(self):
      """Data-path: in-band, solicited/active, passphrase, specific peer

      Verifies end-to-end discovery + data-path creation.
      """
      self.run_ib_data_path_test(
          ptype=aconsts.PUBLISH_TYPE_SOLICITED,
          stype=aconsts.SUBSCRIBE_TYPE_ACTIVE,
          encr_type=self.ENCR_TYPE_PASSPHRASE,
          use_peer_id=True)

  def test_ib_solicited_active_passphrase_any(self):
      """Data-path: in-band, solicited/active, passphrase, any peer

      Verifies end-to-end discovery + data-path creation.
      """
      self.run_ib_data_path_test(
          ptype=aconsts.PUBLISH_TYPE_SOLICITED,
          stype=aconsts.SUBSCRIBE_TYPE_ACTIVE,
          encr_type=self.ENCR_TYPE_PASSPHRASE,
          use_peer_id=False)

