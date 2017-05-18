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

import datetime
import mock

from neutron import context

mock.patch("oslo_concurrency.lockutils.synchronized")
from networking_avaya.db import models
from networking_avaya.ml2 import const

from neutron.tests.unit import testlib_api

FAKE_HOST = "fake_host"
FAKE_NETWORK_ID = "fake_network_id"
FAKE_TX_ID = "fake_tx_id"
FAKE_STATUS = "FAKE_STATUS"
FAKE_PORT_ID = "fake_port_id"
FAKE_OPENSTACK_ID = "fake_openstack_id"
FAKE_PHYSNET = "fake_physnet"
FAKE_PHYSNET1 = "fake_physnet_1"
FAKE_SWITCH = "fake_switch"
FAKE_PORT = "fake_port"
FAKE_PORT1 = "fake_port_1"
FAKE_LLDP = (FAKE_SWITCH, FAKE_PORT)
FAKE_LLDP1 = (FAKE_SWITCH, FAKE_PORT1)
FAKE_LLDP_SINGLE = {FAKE_PHYSNET: [FAKE_LLDP]}
FAKE_LLDP_BOND = {FAKE_PHYSNET: [FAKE_LLDP, FAKE_LLDP1]}
FAKE_LLDP_MULTI = {FAKE_PHYSNET: [FAKE_LLDP], FAKE_PHYSNET1: [FAKE_LLDP1]}


class AvayaDBBaseTestCase(testlib_api.SqlTestCaseLight):
    def setUp(self):
        super(AvayaDBBaseTestCase, self).setUp()
        ctx = context.Context(user_id=None,
                              tenant_id=None,
                              is_admin=True,
                              overwrite=False)
        self.session = ctx.session


class AvayaDBGetMappingTestCase(AvayaDBBaseTestCase):
    def test_get_locked_mapping(self):
        self.fake_session = mock.MagicMock()
        ret = models._get_locked_mapping(self.fake_session,
                                         FAKE_HOST, FAKE_NETWORK_ID)
        self.fake_session.query.assert_called_once_with(
            models.HostNetworkMapping)
        self.fake_session.query().filter_by.assert_called_once_with(
            host=FAKE_HOST, network_id=FAKE_NETWORK_ID)
        self.assertEqual(ret,
                         self.fake_session.query().filter_by().
                         with_for_update().one_or_none())


class AvayaDBGetOpenstackId(AvayaDBBaseTestCase):
    def test_get_openstack_id(self):
        with models.get_openstack_id(self.session) as r:
            self.assertEqual(r, {})
            r["openstack_id"] = FAKE_OPENSTACK_ID
        with models.get_openstack_id(self.session) as r:
            self.assertEqual(r["openstack_id"], FAKE_OPENSTACK_ID)


class AvayaDBMappingsBaseTestCase(AvayaDBBaseTestCase):
    def setUp(self):
        super(AvayaDBMappingsBaseTestCase, self).setUp()
        mock_other_ports = mock.patch.object(models, 'other_ports_exists',
                                             return_value=False)
        self.mock_other_ports = mock_other_ports.start()
        self.assertTrue(models.try_create_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID))
        self.first_mapping = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)


class AvayaDBMappingsTestCase(AvayaDBMappingsBaseTestCase):
    def test_create_mapping(self):
        self.assertIsNotNone(self.first_mapping)
        self.assertEqual(self.first_mapping.status, const.MAPPING_STATUS_NEW)
        self.assertIsNone(self.first_mapping.tx_id)
        self.assertFalse(self.mock_other_ports.called)

    def test_create_same_mapping(self):
        self.assertFalse(models.try_create_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID))
        self.assertFalse(self.mock_other_ports.called)

    def test_process_mapping(self):
        with models.process_mapping(
                self.session, FAKE_HOST, FAKE_NETWORK_ID,
                const.MAPPING_STATUS_NEW) as res:
            res['status'] = FAKE_STATUS
            res['tx_id'] = FAKE_TX_ID
        ret = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)
        self.assertIsNotNone(ret)
        self.assertEqual(ret.status, FAKE_STATUS)
        self.assertEqual(ret.tx_id, FAKE_TX_ID)
        self.assertFalse(self.mock_other_ports.called)

    def test_process_mapping_different_status(self):
        with models.process_mapping(
                self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_STATUS) as res:
            self.assertIsNone(res)
        ret = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)
        self.assertIsNotNone(ret)
        self.assertEqual(ret, self.first_mapping)
        self.assertFalse(self.mock_other_ports.called)

    def test_create_conflicting_mapping(self):
        with models.process_mapping(
                self.session, FAKE_HOST, FAKE_NETWORK_ID,
                const.MAPPING_STATUS_NEW) as res:
            res['status'] = const.MAPPING_STATUS_DELETING
            res['tx_id'] = FAKE_TX_ID
        self.assertRaises(
            models.MappingConflict, models.try_create_mapping, self.session,
            FAKE_HOST, FAKE_NETWORK_ID)
        self.assertFalse(self.mock_other_ports.called)

    def test_delete_conflicting_mapping(self):
        self.assertRaises(
            models.MappingConflict, models.try_delete_mapping, self.session,
            FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID)
        ret = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)
        self.assertEqual(ret, self.first_mapping)
        self.mock_other_ports.assert_called_once_with(
            self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID)

    def test_mapping_set_active(self):
        with models.process_mapping(
                self.session, FAKE_HOST, FAKE_NETWORK_ID,
                const.MAPPING_STATUS_NEW) as res:
            res['status'] = const.MAPPING_STATUS_CREATING
            res['tx_id'] = FAKE_TX_ID
        models.mapping_delete_or_set_active(self.session, [FAKE_TX_ID])
        ret = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)
        self.assertIsNotNone(ret)
        self.assertEqual(ret.status, const.MAPPING_STATUS_ACTIVE)
        self.assertIsNone(ret.tx_id)


class AvayaDBMappingsDeleteTestCase(AvayaDBMappingsBaseTestCase):
    def setUp(self):
        super(AvayaDBMappingsDeleteTestCase, self).setUp()
        with models.process_mapping(
                self.session, FAKE_HOST, FAKE_NETWORK_ID,
                const.MAPPING_STATUS_NEW) as res:
            res['status'] = const.MAPPING_STATUS_ACTIVE
            res['tx_id'] = None

    def test_delete_mapping(self):
        self.assertTrue(models.try_delete_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID))
        ret = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)
        self.assertEqual(ret.status, const.MAPPING_STATUS_DELETE)
        self.assertIsNone(ret.tx_id)
        self.mock_other_ports.assert_called_once_with(
            self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID)

    def test_delete_already_deleting_mapping(self):
        self.assertTrue(models.try_delete_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID))
        self.assertFalse(models.try_delete_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID))
        ret = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)
        self.assertEqual(ret.status, const.MAPPING_STATUS_DELETE)
        self.assertIsNone(ret.tx_id)

    def test_delete_other_port_exists(self):
        self.mock_other_ports.return_value = True
        self.assertFalse(models.try_delete_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID))
        self.mock_other_ports.assert_called_once_with(
            self.session, FAKE_HOST, FAKE_NETWORK_ID, FAKE_PORT_ID)
        ret = models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID)
        self.assertIsNotNone(ret)

    def test_delete_mapping_for_real(self):
        with models.process_mapping(
                self.session, FAKE_HOST, FAKE_NETWORK_ID,
                const.MAPPING_STATUS_ACTIVE) as res:
            res['status'] = const.MAPPING_STATUS_DELETING
            res['tx_id'] = FAKE_TX_ID
        models.mapping_delete_or_set_active(self.session, [FAKE_TX_ID])
        self.assertIsNone(models._get_locked_mapping(
            self.session, FAKE_HOST, FAKE_NETWORK_ID))


class AvayaDBDynamicMappingBaseTestCase(AvayaDBBaseTestCase):
    def setUp(self):
        super(AvayaDBDynamicMappingBaseTestCase, self).setUp()
        self.mock_utcnow = mock.patch('oslo_utils.timeutils.utcnow').start()
        self.fake_time = datetime.datetime(2016, 12, 2, 0, 0)
        self.mock_utcnow.return_value = self.fake_time


class AvayaDBDynamicMappingTestCase(AvayaDBDynamicMappingBaseTestCase):
    def _get_dynamic_mappings_for_host(self, host):
        qry = self.session.query(models.SwitchDynamicMapping)
        return qry.filter_by(host=host)

    def _assert_dynamic_mapping(self, mapping, port=FAKE_PORT, time=None):
        if not time:
            time = self.fake_time
        self.assertEqual(mapping.physnet, FAKE_PHYSNET)
        self.assertEqual(mapping.switch, FAKE_SWITCH)
        self.assertEqual(mapping.port, port)
        self.assertEqual(mapping.last_update, time)

    def test_dynamic_mapping_create(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_SINGLE)
        ret = self._get_dynamic_mappings_for_host(FAKE_HOST).one_or_none()
        self.assertIsNotNone(ret)
        self._assert_dynamic_mapping(ret)

    def test_dynamic_mapping_create_bond(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_BOND)
        ret = self._get_dynamic_mappings_for_host(FAKE_HOST).all()
        self.assertEqual(len(ret), 2)
        self._assert_dynamic_mapping(ret[0])
        self._assert_dynamic_mapping(ret[1], FAKE_PORT1)

    def test_update_dynamic_mapping(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_SINGLE)
        new_time = datetime.datetime(2016, 12, 3, 0, 0)
        self.mock_utcnow.return_value = new_time
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_SINGLE)
        ret = self._get_dynamic_mappings_for_host(FAKE_HOST).one_or_none()
        self.assertIsNotNone(ret)
        self._assert_dynamic_mapping(ret, time=new_time)

    def test_drop_dynamic_mappings(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_BOND)
        models.drop_dynamic_mappings(self.session, FAKE_HOST)
        ret = self._get_dynamic_mappings_for_host(FAKE_HOST).all()
        self.assertEqual(ret, [])


class AvayaDBGetDynamicMappingTestCase(AvayaDBDynamicMappingBaseTestCase):
    def setUp(self):
        super(AvayaDBGetDynamicMappingTestCase, self).setUp()
        self.fake_ctx = mock.Mock()
        self.fake_ctx._plugin_context.session = self.session
        self.fake_get_agent = self.fake_ctx._plugin.get_enabled_agent_on_host
        self.fake_get_agent.return_value = True

    def test_get_dynamic_mappings(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_MULTI)
        ret = models.get_dynamic_mappings_for_host(self.fake_ctx,
                                                   FAKE_HOST, 3, None)
        expected = {k: set(v) for k, v in FAKE_LLDP_MULTI.items()}
        self.assertEqual(ret, expected)
        self.fake_get_agent.assert_called_once_with(
            self.fake_ctx._plugin_context,
            const.AVAYA_DISCOVERY_AGENT,
            FAKE_HOST)

    def test_get_dynamic_mappings_no_agents(self):
        self.fake_get_agent.return_value = False
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_MULTI)
        ret = models.get_dynamic_mappings_for_host(self.fake_ctx,
                                                   FAKE_HOST, 3, None)
        self.assertEqual(ret, {})
        self.fake_get_agent.assert_called_once_with(
            self.fake_ctx._plugin_context,
            const.AVAYA_DISCOVERY_AGENT,
            FAKE_HOST)

    def test_get_dynamic_mappings_exclude_physnet(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_MULTI)
        ret = models.get_dynamic_mappings_for_host(
            self.fake_ctx, FAKE_HOST, 3, [FAKE_PHYSNET1])
        expected = {FAKE_PHYSNET: set([(FAKE_SWITCH, FAKE_PORT)])}
        self.assertEqual(ret, expected)

    def test_get_dynamic_mappings_outdated(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_SINGLE)
        new_time = datetime.datetime(2016, 12, 3, 0, 0)
        self.mock_utcnow.return_value = new_time
        ret = models.get_dynamic_mappings_for_host(self.fake_ctx,
                                                   FAKE_HOST, 3, None)
        self.assertEqual(ret, {})

    def test_get_dynamic_mappings_bond_outdated(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_BOND)
        new_time = datetime.datetime(2016, 12, 3, 0, 0)
        self.mock_utcnow.return_value = new_time
        ret = models.get_dynamic_mappings_for_host(self.fake_ctx,
                                                   FAKE_HOST, 3, None)
        self.assertEqual(ret, {})

    def test_get_dynamic_mappings_bond_one_link_outdated(self):
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, FAKE_LLDP_SINGLE)
        new_time = datetime.datetime(2016, 12, 3, 0, 0)
        self.mock_utcnow.return_value = new_time
        models.dynamic_mapping_create_or_update(
            self.session, FAKE_HOST, {FAKE_PHYSNET: [FAKE_LLDP1]})
        ret = models.get_dynamic_mappings_for_host(self.fake_ctx,
                                                   FAKE_HOST, 3, None)
        expected = {k: set(v) for k, v in FAKE_LLDP_BOND.items()}
        self.assertEqual(ret, expected)
