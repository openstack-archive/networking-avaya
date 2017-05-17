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
# from six import moves
# import testtools
# from testtools import matchers

# from neutron.common import exceptions as exc
# from neutron.db import api as db
from neutron.plugins.ml2 import driver_api as api
# from neutron.tests.unit import testlib_api
from neutron.tests.unit.plugins.ml2 import _test_mech_agent as base

from networking_avaya.ml2 import const
from networking_avaya.ml2.drivers import mech_avaya


class AvayaMechanismBaseTestCase(base.AgentMechanismBaseTestCase):
    # CAP_PORT_FILTER = True
    # AGENT_TYPE = constants.AGENT_TYPE_LINUXBRIDGE

    def setUp(self):
        super(AvayaMechanismBaseTestCase, self).setUp()
        self.driver = mech_avaya.AvayaMechanismDriver()
        self.driver.initialize()
        self.mock_continue_binding = mock.patch.object(
            base.FakePortContext,
            'continue_binding').start()
        self.mock_segment_isid = mock.patch.object(
            mech_avaya,
            '_is_segment_isid').start()
        self.mock_allocate_dynamic_segment = mock.patch.object(
            base.FakePortContext,
            'allocate_dynamic_segment').start()
        self.mock_host = mock.patch.object(
            base.FakePortContext,
            'host',
            'FAKE_HOST').start()


class AvayaMechanismGenericTestCase(AvayaMechanismBaseTestCase,
                                    base.AgentMechanismGenericTestCase):
    pass


class AvayaMechanismVlanTestCase(AvayaMechanismBaseTestCase):
    VLAN_SEGMENTS = [{api.ID: 'vlan_segment_id',
                      api.NETWORK_TYPE: 'vlan',
                      api.PHYSICAL_NETWORK: 'fake_physical_network',
                      api.SEGMENTATION_ID: 1234}]

    def test_type_vlan(self):
        context = base.FakePortContext(self.AGENT_TYPE,
                                       self.AGENTS,
                                       self.VLAN_SEGMENTS,
                                       vnic_type=self.VNIC_TYPE)
        self.mock_segment_isid.return_value = False
        self.driver.bind_port(context)
        self._check_unbound(context)
        self.mock_segment_isid.assert_called_once_with(self.VLAN_SEGMENTS[0])
        self.assertFalse(self.mock_allocate_dynamic_segment.called)
        self.assertFalse(self.mock_continue_binding.called)


class AvayaMechanismIsidTestCase(AvayaMechanismBaseTestCase):
    ISID_SEGMENTS = [{api.ID: 'isid_segment_id',
                      api.NETWORK_TYPE: const.TYPE_ISID,
                      api.SEGMENTATION_ID: 1234}]
    VLAN_SEGMENT = {api.NETWORK_TYPE: 'vlan',
                    api.PHYSICAL_NETWORK: 'FAKE_HOST',
                    const.AVAYA_VLAN_SEGMENT: True}

    def setUp(self):
        super(AvayaMechanismIsidTestCase, self).setUp()
        self.context = base.FakePortContext(self.AGENT_TYPE,
                                            self.AGENTS,
                                            self.ISID_SEGMENTS,
                                            vnic_type=self.VNIC_TYPE)
        self.mock_segment_isid.return_value = True

    def test_type_isid(self):
        fake_segment = mock.Mock()
        self.mock_allocate_dynamic_segment.return_value = fake_segment
        self.driver.bind_port(self.context)
        self.mock_segment_isid.assert_called_once_with(self.ISID_SEGMENTS[0])
        self.mock_allocate_dynamic_segment.assert_called_once_with(
            self.VLAN_SEGMENT)
        self.mock_continue_binding.assert_called_once_with(
            'isid_segment_id',
            [fake_segment])

    def test_cannot_allocate_dynamic_segment(self):
        self.mock_allocate_dynamic_segment.return_value = None
        self.driver.bind_port(self.context)
        self.mock_segment_isid.assert_called_once_with(self.ISID_SEGMENTS[0])
        self.mock_allocate_dynamic_segment.assert_called_once_with(
            self.VLAN_SEGMENT)
        self.assertFalse(self.mock_continue_binding.called)
