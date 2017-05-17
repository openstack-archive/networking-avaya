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
from neutron_lib import exceptions as lib_exc
from oslo_config import cfg
from oslo_log import log as logging

from neutron._i18n import _
from neutron._i18n import _LE
from neutron._i18n import _LI
from neutron.common import rpc as n_rpc
from neutron.plugins.common import constants as n_const
from neutron.plugins.common import utils as plugin_utils
from neutron.plugins.ml2 import driver_api as api

from networking_avaya.db import models
from networking_avaya.ml2 import const
from networking_avaya.ml2.drivers import rpc
from networking_avaya.ml2 import mapping_parser


LOG = logging.getLogger(__name__)


mech_driver_opts = [
    cfg.StrOpt('static_mapping_path',
               default="/etc/neutron/plugins/ml2/avaya_static_mappings.ini",
               help=_("Path to file with static mappings host->switch/port")),
    cfg.IntOpt('dynamic_entry_age',
               default=30,
               help=_("Time in seconds after which dynamic mapping will be "
                      "invalid")),
    cfg.BoolOpt('fallback_to_static',
                default=True,
                help=_("If this option is True, driver will fallback to "
                       "reading static mapping file if no valid dynamic "
                       "mapping for host and physnet can be found")),
]

cfg.CONF.register_opts(mech_driver_opts, "avaya_ml2")


class NoValidMappings(lib_exc.NeutronException):
    message = _("No valid mappings for host %(host)s")


class NoValidMappingsPhysnet(lib_exc.NeutronException):
    message = _("No valid mappings for host %(host)s and physnet %(physnet)s")


class NoBridgeName(lib_exc.NeutronException):
    message = _("No bridge name for host %(host)s, physnet %(physnet)s")


class NoMgmtIP(lib_exc.NeutronException):
    message = _("No management IP for host %(host)s")


def _is_segment_isid(segment):
    return segment[api.NETWORK_TYPE] == const.TYPE_ISID


def _is_supported_network(network):
    segment = network.network_segments[0]
    return ((_is_segment_isid(segment) or
            (segment[api.NETWORK_TYPE] == n_const.TYPE_VLAN)))


def _is_migrating(ctx):
    original_host = ctx.original_host
    host = ctx.host
    drop_bindings = ctx.original_binding_levels and not ctx.binding_levels
    changed = original_host and host and (original_host != host)
    return changed and drop_bindings


def _is_binding(ctx):
    original_host = ctx.original_host
    host = ctx.host
    binding = not ctx.original_binding_levels and ctx.binding_levels
    return host and (original_host == host) and binding


def _mapping(host, top, bottom):
    ret = {'host': host}
    if top is None:
        return None
    if _is_segment_isid(top):
        ret['physnet'] = bottom[api.PHYSICAL_NETWORK]
        ret['vlan'] = bottom[api.SEGMENTATION_ID]
        ret['isid'] = top[api.SEGMENTATION_ID]
        return ret
    elif top[api.NETWORK_TYPE] == n_const.TYPE_VLAN:
        ret['physnet'] = top[api.PHYSICAL_NETWORK]
        ret['vlan'] = top[api.SEGMENTATION_ID]
        ret['isid'] = None
        return ret
    return None


def check_supported_network(fn):
    def wrapped(self, context):
        network_id = context.network.current[api.ID]
        if not _is_supported_network(context.network):
            LOG.debug("Network %s is unsupported", network_id)
            return
        return fn(self, context, network_id)
    return wrapped


class AvayaMechanismDriver(api.MechanismDriver):

    def __init__(self):
        super(AvayaMechanismDriver, self).__init__()
        self._start_rpc_listeners()
        self.agent_api = rpc.AgentMappingAPI()
        network_vlan_ranges = plugin_utils.parse_network_vlan_ranges(
            cfg.CONF.ml2_type_vlan.network_vlan_ranges)
        self.vlan_physnets = network_vlan_ranges.keys()
        self.dynamic_age = cfg.CONF.avaya_ml2.dynamic_entry_age
        if cfg.CONF.avaya_ml2.fallback_to_static:
            static_mappings, mgmt_ips = mapping_parser.parse_static_mappings(
                cfg.CONF.avaya_ml2.static_mapping_path)
            self.static_mappings = static_mappings
            self.mgmt_ips = mgmt_ips
        else:
            self.static_mappings = {}
            self.mgmt_ips = {}

    def _start_rpc_listeners(self):
        self.endpoints = [rpc.AvayaCallbacks()]
        self.topic = const.AVAYA_ML2
        self.conn = n_rpc.create_connection()
        self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        return self.conn.consume_in_threads()

    def initialize(self):
        LOG.info(_LI("Avaya mechanism driver initialized"))

    def _get_mappings(self, context, exclude_physnets=[]):
        host = context.host
        mappings = models.get_dynamic_mappings_for_host(
            context, host, self.dynamic_age, exclude_physnets)
        if not mappings:
            mappings = self.static_mappings.get(context.host, [])
            mappings = {physnet: maps for physnet, maps in mappings.iteritems()
                        if physnet not in exclude_physnets}
        if not mappings:
            raise NoValidMappings(host=host)
        return mappings

    def _populate_switch_ports(self, context, mapping):
        physnet = mapping['physnet']
        host = mapping['host']
        # NOTE(Yar): To be sure that they're always the same
        assert context.host == host, "mapping has wrong host"
        try:
            mapping['switch_ports'] = self._get_mappings(context)[physnet]
        except KeyError:
            raise NoValidMappingsPhysnet(host=host, physnet=physnet)

    def _populate_mgmt_ip(self, context, mapping):
        host = mapping['host']
        discovery_agent = context.host_agents(const.AVAYA_DISCOVERY_AGENT)
        try:
            mgmt_ip = discovery_agent[0]['configurations']['management_ip']
            mapping['management_ip'] = mgmt_ip
        except KeyError:
            try:
                mapping['management_ip'] = self.mgmt_ips[host]
            except KeyError:
                raise NoMgmtIP(host=host)

    def _populate_bridge_name(self, context, mapping):
        host = mapping['host']
        physnet = mapping['physnet']
        ovs_agent = context.host_agents(lib_const.AGENT_TYPE_OVS)[0]
        try:
            bridge_mappings = ovs_agent['configurations']['bridge_mappings']
            mapping['bridge_name'] = bridge_mappings[physnet]
        except KeyError:
            raise NoBridgeName(host=host, physnet=physnet)

    def _create_mapping(self, context, mapping):
        self._populate_switch_ports(context, mapping)
        self._populate_mgmt_ip(context, mapping)
        self._populate_bridge_name(context, mapping)
        try:
            ctx = context._plugin_context
            tx_id = self.agent_api.create_mapping(ctx, mapping)
            LOG.debug("Transaction id %s", tx_id)
            return tx_id
        except Exception:
            LOG.error(_LE("Error while sending mapping creation request %s"),
                      mapping)

    def _delete_mapping(self, context, mapping):
        self._populate_switch_ports(context, mapping)
        try:
            ctx = context._plugin_context
            tx_id = self.agent_api.delete_mapping(ctx, mapping)
            LOG.debug("Transaction id %s", tx_id)
            return tx_id
        except Exception:
            LOG.error(_LE("Error while sending mapping deletion request %s"),
                      mapping)

    @check_supported_network
    def update_port_precommit(self, context, network_id):
        LOG.debug("Update port: old host %s, new host %s, old binding_levels: "
                  "%s, new binding_levels: %s", context.original_host,
                  context.host, context.original_binding_levels,
                  context.binding_levels)
        session = context._plugin_context.session
        if _is_migrating(context):
            # Drop binding on old host
            models.try_delete_mapping(session, context.original_host,
                                      network_id, context.current[api.ID])
        elif (_is_binding(context) or
                (context.host and not context.original_host)):
            # New mapping
            models.try_create_mapping(session, context.host, network_id)

    @check_supported_network
    def update_port_postcommit(self, context, network_id):
        session = context._plugin_context.session
        if _is_migrating(context):
            host = context.original_host
            mapping = _mapping(host, context.original_top_bound_segment,
                               context.original_bottom_bound_segment)
            if mapping:
                with models.process_mapping(session, host, network_id,
                                            const.MAPPING_STATUS_DELETE) as r:
                    if r:
                        r['tx_id'] = self._delete_mapping(context, mapping)
                        r['status'] = const.MAPPING_STATUS_DELETING
        elif _is_binding(context):
            host = context.host
            mapping = _mapping(host, context.top_bound_segment,
                               context.bottom_bound_segment)
            if mapping:
                with models.process_mapping(session, host, network_id,
                                            const.MAPPING_STATUS_NEW) as r:
                    if r:
                        r['tx_id'] = self._create_mapping(context, mapping)
                        r['status'] = const.MAPPING_STATUS_CREATING

    @check_supported_network
    def delete_port_precommit(self, context, network_id):
        session = context._plugin_context.session
        host = context.host
        port_id = context.current[api.ID]
        models.try_delete_mapping(session, host, network_id, port_id)

    @check_supported_network
    def delete_port_postcommit(self, context, network_id):
        # TODO(Yar) use release_dynamic_segment here
        session = context._plugin_context.session
        host = context.host
        mapping = _mapping(host, context.top_bound_segment,
                           context.bottom_bound_segment)
        if mapping:
            with models.process_mapping(session, host, network_id,
                                        const.MAPPING_STATUS_DELETE) as r:
                if r:
                    r['tx_id'] = self._delete_mapping(context, mapping)
                    r['status'] = const.MAPPING_STATUS_DELETING

    def _allocate_dynamic_segment(self, context):
        network_id = context.network.current[api.ID]
        physnets = self._get_mappings(context, self.vlan_physnets).keys()
        session = context._plugin_context.session
        with models.get_physnets_from_existing_dynamic_segment(
                session, network_id, physnets) as candidate_physnets:
            for physnet in candidate_physnets:
                dyn_segment = {api.NETWORK_TYPE: n_const.TYPE_VLAN,
                               const.AVAYA_VLAN_SEGMENT: True,
                               api.PHYSICAL_NETWORK: physnet}
                dynamic_segment = context.allocate_dynamic_segment(dyn_segment)
                if dynamic_segment:
                    return dynamic_segment

    def bind_port(self, context):
        LOG.debug("bind_port: %s %s", context.current,
                  context.host_agents(lib_const.AGENT_TYPE_OVS))
        for segment in context.segments_to_bind:
            if _is_segment_isid(segment):
                dynamic_segment = self._allocate_dynamic_segment(
                    context)
                if dynamic_segment:
                    context.continue_binding(segment[api.ID],
                                             [dynamic_segment])
                    return
                LOG.error(_LE("Cannot allocate dynamic segment for port "
                              "%s"), context.current[api.ID])
            else:
                LOG.debug("No binding required for segment %s",
                          segment[api.ID])
