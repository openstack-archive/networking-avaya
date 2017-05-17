# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
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

import random

from oslo_config import cfg
from oslo_log import log
from six import moves

from neutron.common import exceptions as exc
from neutron.db import api as db_api
from neutron.plugins.common import constants as p_const
from neutron.plugins.ml2 import driver_api as api
from neutron.plugins.ml2.drivers import type_vlan

from networking_avaya.ml2 import const


LOG = log.getLogger(__name__)


dynamic_vlan_opts = [
    cfg.StrOpt('dynamic_vlan_range',
               default="%s:%s" % (p_const.MIN_VLAN_TAG, p_const.MAX_VLAN_TAG))
]

CONF = cfg.CONF
CONF.register_opts(dynamic_vlan_opts, "avaya_type_vlan")


class AvayaVlanTypeDriver(type_vlan.VlanTypeDriver):

    def __init__(self):
        super(AvayaVlanTypeDriver, self).__init__()
        v_min, v_max = CONF.avaya_type_vlan.dynamic_vlan_range.split(":")
        self._all_vlan_ids = frozenset(moves.range(int(v_min), int(v_max) + 1))
        LOG.debug("Initalized Avaya VLAN type driver, dynamic_vlan_range = "
                  "%s:%s", v_min, v_max)

    @db_api.retry_db_errors
    def _allocate_avaya_dynamic_segment(self, session, segment):
        physical_network = segment.get(api.PHYSICAL_NETWORK)
        with session.begin(subtransactions=True):
            allocs = session.query(type_vlan.VlanAllocation).filter_by(
                physical_network=physical_network)
            allocated_vlans = {alloc.vlan_id for alloc in allocs}
            available_vlans = tuple(self._all_vlan_ids - allocated_vlans)
            if len(available_vlans) > 0:
                vlan_id = random.choice(available_vlans)
                alloc = type_vlan.VlanAllocation(
                    allocated=True,
                    physical_network=physical_network,
                    vlan_id=vlan_id)
                alloc.save(session)
                return {api.NETWORK_TYPE: self.get_type(),
                        api.PHYSICAL_NETWORK: alloc.physical_network,
                        api.SEGMENTATION_ID: alloc.vlan_id,
                        api.MTU: self.get_mtu(alloc.physical_network)}
            else:
                raise exc.NoNetworkAvailable()

    def reserve_provider_segment(self, session, segment):
        if segment.get(const.AVAYA_VLAN_SEGMENT):
            return self._allocate_avaya_dynamic_segment(session, segment)
        else:
            return super(AvayaVlanTypeDriver, self).reserve_provider_segment(
                session,
                segment)
