# Copyright (c) 2016 Avaya, Inc
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock
from oslotest import base

from networking_avaya.sdn import client


FAKE_ENDPOINTS = {"fake": "fake_endpoint",
                  "fake_with_param": "fake_endpoint/{fake_param}",
                  "fake_with_openstack_id": "fake_endpoint/{openstack_id}"}

FAKE_OPENSTACK_ID = "fake_openstack_id"
FAKE_URL = "fake_url"
FAKE_STATUS = "fake_status"
BAD_STATUS = "bad_status"
FAKE_PARAM = "fake_param"
FAKE_TX_ID = "fake_tx_id"
FAKE_TX_ID2 = "fake_tx_id_2"
FAKE_RESPONSE = "fake_response"
FAKE_NETWORK = "fake_network"
FAKE_MAPPING = "fake_mapping"


class AvayaClientBaseTestCase(base.BaseTestCase):
    def setUp(self):
        super(AvayaClientBaseTestCase, self).setUp()
        fake_base_ep = mock.patch(
            'networking_avaya.sdn.client.BASE_ENDPOINT',
            "FAKE_BASE/")
        fake_base_ep.start()
        self.client = client.AvayaSDNClient("FAKE_URL/", "FAKE_USER",
                                            "FAKE_PASSWORD", "FAKE_CA_PATH")


class AvayaClientGetUrlTestCase(AvayaClientBaseTestCase):
    def setUp(self):
        super(AvayaClientGetUrlTestCase, self).setUp()
        fake_eps = mock.patch('networking_avaya.sdn.client.ENDPOINTS',
                              FAKE_ENDPOINTS)
        fake_eps.start()

    def test_get_url(self):
        res = self.client._get_url(kind='fake')
        self.assertEqual(res, "FAKE_URL/FAKE_BASE/fake_endpoint")

    def test_get_url_with_param(self):
        res = self.client._get_url(kind='fake_with_param',
                                   fake_param="FAKE_PARAM")
        self.assertEqual(res, "FAKE_URL/FAKE_BASE/fake_endpoint/FAKE_PARAM")

    def test_get_url_with_openstack_id(self):
        with mock.patch.object(self.client, "openstack_id", FAKE_OPENSTACK_ID):
            res = self.client._get_url(kind='fake_with_openstack_id')
            self.assertEqual(res, "FAKE_URL/FAKE_BASE/fake_endpoint/"
                             "fake_openstack_id")


class AvayaClientTryRequestTestCase(AvayaClientBaseTestCase):
    def setUp(self):
        super(AvayaClientTryRequestTestCase, self).setUp()
        self.fake_response = mock.Mock()
        self.fake_response.status_code = FAKE_STATUS
        self.fake_method = mock.Mock(return_value=self.fake_response)

    def test_ok(self):
        self.client._try_request(self.fake_method,
                                 expected_status=FAKE_STATUS)
        self.fake_method.assert_called_once_with(timeout=client.SDN_TIMEOUT)
        self.fake_response.raise_for_status.assert_called_once_with()

    def test_with_param(self):
        self.client._try_request(self.fake_method,
                                 expected_status=FAKE_STATUS,
                                 fake_param=FAKE_PARAM)
        self.fake_method.assert_called_once_with(fake_param=FAKE_PARAM,
                                                 timeout=client.SDN_TIMEOUT)
        self.fake_response.raise_for_status.assert_called_once_with()

    def test_wrong_status(self):
        self.assertRaises(Exception, self.client._try_request,  # noqa
                          self.fake_method,
                          expected_status=BAD_STATUS)
        self.fake_method.assert_called_once_with(timeout=client.SDN_TIMEOUT)
        self.fake_response.raise_for_status.assert_called_once_with()


class AvayaClientRequestBaseTestCase(AvayaClientBaseTestCase):
    def setUp(self):
        super(AvayaClientRequestBaseTestCase, self).setUp()
        mock_get_url = mock.patch.object(self.client, "_get_url",
                                         return_value=FAKE_URL)
        self.mock_get_url = mock_get_url.start()
        mock_try_request = mock.patch.object(self.client, "_try_request")
        self.mock_try_request = mock_try_request.start()
        self.mock_session = mock.patch.object(self.client, "_session")
        self.fake_session = self.mock_session.start()


class AvayaClientGetOpenstackIdTestCase(AvayaClientRequestBaseTestCase):
    def test_ok(self):
        fake_response = mock.Mock()
        fake_response.json.return_value = {
            "openstack_id": FAKE_OPENSTACK_ID
        }
        self.mock_try_request.return_value = fake_response
        ret = self.client.get_openstack_id()
        self.assertEqual(ret, FAKE_OPENSTACK_ID)
        self.mock_get_url.assert_called_once_with('register')
        self.mock_try_request.assert_called_once_with(self.fake_session.post,
                                                      200, url=FAKE_URL)


class AvayaClientMappingRequestTestCase(AvayaClientRequestBaseTestCase):
    def setUp(self):
        super(AvayaClientMappingRequestTestCase, self).setUp()
        self.mock_try_request.return_value = FAKE_RESPONSE
        mock_format_network = mock.patch.object(
            self.client, "_format_network_from_mapping",
            return_value=FAKE_NETWORK)
        self.mock_format_network = mock_format_network.start()
        mock_parse_tx = mock.patch.object(
            self.client, "_parse_tx_id_from_response",
            return_value=FAKE_TX_ID)
        self.mock_parse_tx = mock_parse_tx.start()

    def test_create_network(self):
        ret = self.client.create_network(FAKE_MAPPING)
        self.assertEqual(ret, FAKE_TX_ID)
        self.mock_get_url.assert_called_once_with()
        self.mock_format_network.assert_called_once_with(FAKE_MAPPING)
        self.mock_try_request.assert_called_once_with(
            self.fake_session.post, 202, url=FAKE_URL, log_location=True,
            json=FAKE_NETWORK)
        self.mock_parse_tx.assert_called_once_with(FAKE_RESPONSE)

    def test_delete_network(self):
        ret = self.client.delete_network(FAKE_MAPPING)
        self.assertEqual(ret, FAKE_TX_ID)
        self.mock_get_url.assert_called_once_with()
        self.mock_format_network.assert_called_once_with(FAKE_MAPPING)
        self.mock_try_request.assert_called_once_with(
            self.fake_session.delete, 202, url=FAKE_URL, log_location=True,
            json=FAKE_NETWORK)
        self.mock_parse_tx.assert_called_once_with(FAKE_RESPONSE)


class AvayaClientTxStatusTestCase(AvayaClientRequestBaseTestCase):
    def setUp(self):
        super(AvayaClientTxStatusTestCase, self).setUp()
        fake_response = mock.Mock()
        self.fake_tx_statuses = [{"status": "Completed",
                                 "transaction_id": FAKE_TX_ID}]
        fake_response.json.return_value = self.fake_tx_statuses
        self.mock_try_request.return_value = fake_response

    def test_no_tx_ids(self):
        self.assertIsNone(self.client.get_transactions_status([]))
        self.assertFalse(self.mock_try_request.called)
        self.assertFalse(self.mock_get_url.called)

    def test_one_tx(self):
        ret = self.client.get_transactions_status([FAKE_TX_ID])
        self.assertEqual(ret, set([FAKE_TX_ID]))
        self.mock_get_url.assert_called_once_with("transaction",
                                                  tx_ids=FAKE_TX_ID)
        self.mock_try_request.assert_called_once_with(self.fake_session.get,
                                                      200, url=FAKE_URL)

    def test_two_txs(self):
        self.fake_tx_statuses.append({"status": "Completed",
                                      "transaction_id": FAKE_TX_ID2})
        ret = self.client.get_transactions_status([FAKE_TX_ID, FAKE_TX_ID2])
        self.assertEqual(ret, set([FAKE_TX_ID, FAKE_TX_ID2]))
        self.mock_get_url.assert_called_once_with(
            "transaction", tx_ids=",".join([FAKE_TX_ID, FAKE_TX_ID2]))
        self.mock_try_request.assert_called_once_with(self.fake_session.get,
                                                      200, url=FAKE_URL)

    def test_two_txs_one_completed(self):
        self.fake_tx_statuses.append({"status": "SOME_OTHER_STATUS",
                                      "transaction_id": FAKE_TX_ID2})
        ret = self.client.get_transactions_status([FAKE_TX_ID, FAKE_TX_ID2])
        self.assertEqual(ret, set([FAKE_TX_ID]))
        self.mock_get_url.assert_called_once_with(
            "transaction", tx_ids=",".join([FAKE_TX_ID, FAKE_TX_ID2]))
        self.mock_try_request.assert_called_once_with(self.fake_session.get,
                                                      200, url=FAKE_URL)


class AvayaClientUtilityFunctionsTestCase(AvayaClientBaseTestCase):
    def test_format_network(self):
        mapping = {"switch_ports": [
            ("switch_ip1", "port1"),
            ("switch_ip2", "port2")]}
        mapping["vlan"] = "vlan1"
        mapping["isid"] = "isid1"
        expected_binding = {"vlan": "vlan1", "isid": "isid1"}
        expected_network = {"switch_port_bindings": [
            {"switch_ip": "switch_ip1", "port": "port1", "bindings":
                [expected_binding]},
            {"switch_ip": "switch_ip2", "port": "port2", "bindings":
                [expected_binding]}]}
        ret = self.client._format_network_from_mapping(mapping)
        self.assertEqual(ret, expected_network)
        mapping["management_ip"] = "mgmt_ip1"
        mapping["bridge_name"] = "bridge_name1"
        expected_network["compute_host_ip"] = "mgmt_ip1"
        expected_network["ovs_bridge"] = "bridge_name1"
        ret = self.client._format_network_from_mapping(mapping)
        self.assertEqual(ret, expected_network)

    def test_parse_tx_id(self):
        response = mock.Mock()
        response.headers = {}
        self.assertEqual("", self.client._parse_tx_id_from_response(response))
        response.headers = {"Location": "/".join(["BEFORE", FAKE_TX_ID])}
        self.assertEqual(FAKE_TX_ID,
                         self.client._parse_tx_id_from_response(response))
