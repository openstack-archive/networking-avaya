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

from collections import defaultdict
import contextlib
import six

from neutron_lib import constants as nconst
from neutron_lib import exceptions as e
from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_utils import timeutils
import sqlalchemy as sa
from sqlalchemy import sql

from neutron._i18n import _
from neutron.db import model_base
from neutron.db import models_v2
from neutron.db import segments_db
from neutron.db import sqlalchemytypes
from neutron.extensions import portbindings
from neutron.plugins.ml2 import models as ml2_models

from networking_avaya.ml2 import const


LOG = logging.getLogger(__name__)


class MappingConflict(e.Conflict):
    message = _("Conflict of operations: mapping is in status %(status)s, "
                "while Neutron is trying to %(operation)s it")


class NoValidPhysnet(e.NeutronException):
    message = _("No valid physnet for host %(host)s")


class IsidAllocation(model_base.BASEV2):

    __tablename__ = 'avaya_isid_allocations'

    isid = sa.Column(sa.Integer, nullable=False, primary_key=True,
                     autoincrement=False)
    allocated = sa.Column(sa.Boolean, nullable=False, default=False,
                          server_default=sql.false(), index=True)


class HostNetworkMapping(model_base.BASEV2):

    __tablename__ = 'avaya_host_network_mappings'

    host = sa.Column(sa.String(255), primary_key=True, nullable=False)
    network_id = sa.Column(sa.String(255), primary_key=True, nullable=False)
    status = sa.Column(sa.String(20), nullable=False)
    tx_id = sa.Column(sa.String(36), nullable=True, unique=True)


class SwitchDynamicMapping(model_base.BASEV2):

    __tablename__ = 'avaya_switch_dynamic_mappings'

    switch = sa.Column(sa.String(255), primary_key=True, nullable=False)
    port = sa.Column(sa.String(255), primary_key=True, nullable=False)
    host = sa.Column(sa.String(255), nullable=False, index=True)
    physnet = sa.Column(sa.String(255), nullable=False)
    last_update = sa.Column(sqlalchemytypes.TruncatedDateTime,
                            default=timeutils.utcnow, nullable=False)


class OpenStackID(model_base.BASEV2):

    __tablename__ = 'avaya_openstack_id'

    id = sa.Column(sa.String(255), primary_key=True)


def _get_locked_mapping(session, host, network_id):
    qry = session.query(HostNetworkMapping).filter_by(
        host=host, network_id=network_id).with_for_update()
    return qry.one_or_none()


@lockutils.synchronized("avaya_locked_mapping")
def try_create_mapping(session, host, network_id):
    with session.begin(subtransactions=True):
        res = _get_locked_mapping(session, host, network_id)
        if not res:
            res = HostNetworkMapping(host=host, network_id=network_id,
                                     status=const.MAPPING_STATUS_NEW)
            session.add(res)
            return True
        else:
            if res.status in [const.MAPPING_STATUS_DELETING,
                              const.MAPPING_STATUS_DELETE]:
                raise MappingConflict(operation='create', status=res.status)
        return False


@lockutils.synchronized("avaya_locked_mapping")
def try_delete_mapping(session, host, network_id, port_id):
    with session.begin(subtransactions=True):
        res = _get_locked_mapping(session, host, network_id)
        if res:
            if not other_ports_exists(session, host, network_id, port_id):
                if res.status in [const.MAPPING_STATUS_CREATING,
                                  const.MAPPING_STATUS_NEW]:
                    raise MappingConflict(operation='delete',
                                          status=res.status)
                if res.status == const.MAPPING_STATUS_ACTIVE:
                    res.status = const.MAPPING_STATUS_DELETE
                    return True
        return False


@contextlib.contextmanager
def process_mapping(session, host, network_id, expected_status):
    with lockutils.lock("avaya_locked_mapping"):
        with session.begin(subtransactions=True):
            res = _get_locked_mapping(session, host, network_id)
            ret = {'process': True}
            if res and res.status == expected_status:
                yield ret
                res.tx_id = ret['tx_id']
                res.status = ret['status']
            else:
                yield None


def mapping_delete_or_set_active(session, tx_ids):
    if not tx_ids:
        return
    with session.begin(subtransactions=True):
        qry = session.query(HostNetworkMapping)
        qry = qry.filter(HostNetworkMapping.tx_id.in_(tx_ids))
        qry.filter(
            HostNetworkMapping.status == const.MAPPING_STATUS_DELETING).delete(
                synchronize_session='fetch')
        qry.filter(
            HostNetworkMapping.status == const.MAPPING_STATUS_CREATING).update(
                {'status': const.MAPPING_STATUS_ACTIVE,
                 'tx_id': None}, synchronize_session='fetch')


def other_ports_exists(session, host, network_id, exclude_port_id=None):
    ignored_statuses = [portbindings.VIF_TYPE_BINDING_FAILED,
                        portbindings.VIF_TYPE_UNBOUND]
    # Find if there are other ports in the same network on same host
    query = session.query(models_v2.Port)
    # NOTE(yar): Just to be sure that we're not locking many tables
    query = query.enable_eagerloads(False)
    if exclude_port_id:
        query = query.filter(models_v2.Port.id != exclude_port_id)
    query = query.join(ml2_models.PortBinding)
    query = query.filter(
        models_v2.Port.network_id == network_id,
        ~ml2_models.PortBinding.vif_type.in_(ignored_statuses),
        models_v2.Port.device_owner != nconst.DEVICE_OWNER_DVR_INTERFACE,
        ml2_models.PortBinding.host == host)
    query = query.with_for_update()
    with lockutils.lock("avaya_other_ports_exists"):
        return query.first() is not None


def dynamic_mapping_create_or_update(session, mapping_host, lldp_info):
    # TODO(yar): Replace multiple queries with upsert
    with session.begin(subtransactions=True):
        cur_time = timeutils.utcnow()
        qry = session.query(SwitchDynamicMapping).filter_by(host=mapping_host)
        for physnet, mappings in six.iteritems(lldp_info):
            for switch, port in mappings:
                mapping = qry.filter_by(switch=switch, port=port,
                                        physnet=physnet)
                mapping = mapping.one_or_none()
                if mapping:
                    mapping.last_update = cur_time
                else:
                    mapping = SwitchDynamicMapping(switch=switch, port=port,
                                                   host=mapping_host,
                                                   physnet=physnet)
                    mapping.last_update = cur_time
                    session.add(mapping)


def drop_dynamic_mappings(session, host):
    session.query(SwitchDynamicMapping).filter_by(host=host).delete()


def get_dynamic_mappings_for_host(context, host, dynamic_age,
                                  exclude_physnets):
    maps = defaultdict(set)
    valid_physnets = set()
    plugin_context = context._plugin_context
    session = plugin_context.session
    with session.begin(subtransactions=True):
        agent = context._plugin.get_enabled_agent_on_host(
            plugin_context, const.AVAYA_DISCOVERY_AGENT, host)
        if not agent:
            return {}
        res = session.query(SwitchDynamicMapping).filter_by(host=host)
        if exclude_physnets:
            res = res.filter(
                ~SwitchDynamicMapping.physnet.in_(exclude_physnets))
        for mapping in res.all():
            maps[mapping.physnet].add((mapping.switch, mapping.port))
            if not timeutils.is_older_than(mapping.last_update, dynamic_age):
                valid_physnets.add(mapping.physnet)
        return {k: v for k, v in six.iteritems(maps) if k in valid_physnets}


@contextlib.contextmanager
def get_physnets_from_existing_dynamic_segment(session, network_id, phys):
    with lockutils.lock("avaya_get_physnets"):
        with session.begin(subtransactions=True):
            qry = session.query(segments_db.NetworkSegment)
            qry = qry.filter_by(network_id=network_id, is_dynamic=True)
            qry = qry.filter(
                segments_db.NetworkSegment.physical_network.in_(phys))
            physnet = qry.with_for_update().one_or_none()
            if physnet:
                # Dynamic segment found
                yield [physnet.physical_network]
            else:
                yield phys


@contextlib.contextmanager
def get_openstack_id(session):
    with lockutils.lock("avaya_get_openstack_id"):
        with session.begin(subtransactions=True):
            qry = session.query(OpenStackID.id)
            res = qry.with_for_update().scalar()
            if res:
                yield {"openstack_id": res}
            else:
                res = {}
                yield res
                openstack_id = res['openstack_id']
                session.add(OpenStackID(id=openstack_id))
