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

from neutron_lib import constants as lib_const
from oslo_log import log as logging

from neutron._i18n import _LE
from neutron._i18n import _LI
from neutron._i18n import _LW
from neutron import context as ncontext
from neutron.db import models_v2
from neutron.extensions import portbindings
from neutron.plugins.common import constants as n_const
from neutron.plugins.ml2 import driver_api as api

from networking_avaya.ml2 import const

LOG = logging.getLogger(__name__)


def _is_segment_isid(segment):
    return segment[api.NETWORK_TYPE] == const.TYPE_ISID


class AvayaMechanismDriver(api.MechanismDriver):

    def initialize(self):
        LOG.info(_LI("Avaya mechanism driver initialized"))

    def _other_ports_on_host_exists(self, context, host):
        # Find if there are other ports in the same network on same host
        ctx = ncontext.get_admin_context()
        # TODO(Yar): Check for DVR
        filters = {'network_id': [context.network.current[api.ID]],
                   portbindings.HOST_ID: [host]}
        ports = context._plugin._get_ports_query(ctx, filters=filters)
        ports = ports.filter(models_v2.Port.id != context.current[api.ID])
        return ports.first() is not None

    def _create_mapping(self, host, vlan, isid=None):
        if isid is None:
            LOG.debug("Mapping will be created for host %s: vlan %s",
                      host, vlan)
        else:
            LOG.debug("Mapping will be created for host %s: isid %s, "
                      "vlan %s", host, isid, vlan)

    def _delete_mapping(self, host, isid, vlan):
        if isid is None:
            LOG.debug("Mapping will be deleted for host %s: vlan %s",
                      host, vlan)
        else:
            LOG.debug("Mapping will be deleted for host %s: isid %s, "
                      "vlan %s", host, isid, vlan)

    def _process_mapping(self, context, host, top_segment, bottom_segment,
                         func):
        other_ports = self._other_ports_on_host_exists(context, host)
        if other_ports:
            LOG.debug("There are other ports in network %s on the host %s, "
                      "nothing will be done on SDN side",
                      context.network.current[api.ID], host)
            return
        if _is_segment_isid(top_segment):
            func(host, top_segment[api.SEGMENTATION_ID],
                 bottom_segment[api.SEGMENTATION_ID])
        elif top_segment[api.NETWORK_TYPE] == n_const.TYPE_VLAN:
            func(host, None, top_segment[api.SEGMENTATION_ID])
        else:
            LOG.warning(_LW("Wrong type of segment for port %s, no mapping "
                        "will be processed"), context.current[api.ID])

    def _is_migrating(self, context):
        if context.original_host != context.host:
            if context.original_binding_levels and not context.binding_levels:
                return True
            LOG.warning(_LW("Host changed, but binding was not dropped for "
                        "port %s"), context.current[api.ID])
        return False

    def update_port_postcommit(self, context):
        LOG.debug("Update port: old host %s, new host %s, old binding_levels: "
                  "%s, new binding_levels: %s", context.original_host,
                  context.host, context.original_binding_levels,
                  context.binding_levels)
        if self._is_migrating(context):
            self._process_mapping(context, context.original_host,
                                  context.original_top_bound_segment,
                                  context.original_bottom_bound_segment,
                                  self._delete_mapping)
        elif context.binding_levels and not context.original_binding_levels:
            self._process_mapping(context, context.host,
                                  context.top_bound_segment,
                                  context.bottom_bound_segment,
                                  self._create_mapping)

    def delete_port_postcommit(self, context):
        # TODO(Yar) use release_dynamic_segment here
        self._process_mapping(context, context.host,
                              context.top_bound_segment,
                              context.bottom_bound_segment,
                              self._delete_mapping)

    def bind_port(self, context):
        LOG.debug("bind_port: %s %s", context.current,
                  context.host_agents(lib_const.AGENT_TYPE_OVS))
        for segment in context.segments_to_bind:
            if _is_segment_isid(segment):
                vlan_segment = {api.NETWORK_TYPE: n_const.TYPE_VLAN,
                                api.PHYSICAL_NETWORK: context.host,
                                const.AVAYA_VLAN_SEGMENT: True}
                dynamic_segment = context.allocate_dynamic_segment(
                    vlan_segment)
                if dynamic_segment:
                    context.continue_binding(segment[api.ID],
                                             [dynamic_segment])
                else:
                    LOG.error(_LE("Cannot allocate dynamic segment for port "
                              "%s"), context.current[api.ID])
            else:
                LOG.debug("No binding required for segment %s",
                          segment[api.ID])
