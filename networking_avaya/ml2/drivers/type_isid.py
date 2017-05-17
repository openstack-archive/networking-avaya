# Copyright (c) 2016 Avaya, Inc
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

import itertools

from six import moves

from oslo_config import cfg
from oslo_db import api as oslo_db_api
from oslo_log import log

from neutron._i18n import _
from neutron._i18n import _LI
from neutron._i18n import _LW
from neutron.common import exceptions as exc
from neutron.db import api as db_api
from neutron.plugins.ml2 import driver_api as api
from neutron.plugins.ml2.drivers import helpers

from networking_avaya.db import models
from networking_avaya.ml2 import const

LOG = log.getLogger(__name__)

isid_opts = [
    cfg.ListOpt('isid_ranges',
                default=[],
                help=_("Comma-separated list of <isid_min>:<isid_max> tuples "
                       "enumerating ranges of ISID IDs that are "
                       "available for tenant network allocation")),
]

cfg.CONF.register_opts(isid_opts, "avaya_type_isid")


def chunks(iterable, chunk_size):
    """Chunks data into chunk with size<=chunk_size."""
    iterator = iter(iterable)
    chunk = list(itertools.islice(iterator, 0, chunk_size))
    while chunk:
        yield chunk
        chunk = list(itertools.islice(iterator, 0, chunk_size))


class AvayaIsidTypeDriver(helpers.SegmentTypeDriver):

    BULK_SIZE = 100

    def __init__(self):
        super(AvayaIsidTypeDriver, self).__init__(models.IsidAllocation)
        self.isid_ranges = self._parse_isid_ranges(
            cfg.CONF.avaya_type_isid.isid_ranges
        )

    def get_type(self):
        return const.TYPE_ISID

    def initialize(self):
        self._sync_allocations()
        LOG.info(_LI("AvayaIsidTypeDriver initialization complete"))

    def _verify_isid_range(self, isid_range):
        for isid in isid_range:
            if not (const.ISID_MIN <= isid <= const.ISID_MAX):
                raise exc.NetworkTunnelRangeError(
                    tunnel_range=isid_range,
                    error=_("%(id)s is not a valid %(type)s identifier") %
                    {'id': isid, 'type': self.get_type()})
        if isid_range[1] < isid_range[0]:
            raise exc.NetworkTunnelRangeError(
                tunnel_range=isid_range,
                error=_("End of isid range is less "
                        "than start of isid range"))

    def _parse_isid_ranges(self, isid_ranges):
        result_range = []
        for entry in isid_ranges:
            entry = entry.strip()
            try:
                isid_min, isid_max = entry.split(':')
                isid_min = isid_min.strip()
                isid_max = isid_max.strip()
                isid_range = int(isid_min), int(isid_max)
            except ValueError as ex:
                raise exc.NetworkTunnelRangeError(tunnel_range=entry, error=ex)
            self._verify_isid_range(isid_range)
            result_range.append(isid_range)
        LOG.info(_LI("ISID ranges: %s"), result_range)
        return result_range

    @oslo_db_api.wrap_db_retry(
        max_retries=db_api.MAX_RETRIES,
        exception_checker=db_api.is_deadlock)
    def _sync_allocations(self):
        # TODO(Yar): Needs to be completely rewritten
        isids = set()
        for isid_min, isid_max in self.isid_ranges:
            isids |= set(moves.range(isid_min, isid_max + 1))

        session = db_api.get_session()
        with session.begin(subtransactions=True):
            allocs = (session.query(models.IsidAllocation).
                      with_lockmode('update').all())
            unallocateds = (a.isid for a in allocs if not a.allocated)
            to_remove = (x for x in unallocateds if x not in isids)
            # Immediately delete tunnels in chunks. This leaves no work for
            # flush at the end of transaction
            for chunk in chunks(to_remove, self.BULK_SIZE):
                session.query(models.IsidAllocation).filter(
                    models.IsidAllocation.isid.in_(chunk)).delete(
                        synchronize_session=False)

            # collect vnis that need to be added
            existings = {a.isid for a in allocs}
            missings = list(isids - existings)
            for chunk in chunks(missings, self.BULK_SIZE):
                bulk = [{'isid': x, 'allocated': False}
                        for x in chunk]
                session.bulk_insert_mappings(models.IsidAllocation, bulk)
                # session.execute(self.model.__table__.insert(), bulk)

    def validate_provider_segment(self, segment):
        physical_network = segment.get(api.PHYSICAL_NETWORK)
        if physical_network:
            msg = _("provider:physical_network specified for %s "
                    "network") % segment.get(api.NETWORK_TYPE)
            raise exc.InvalidInput(error_message=msg)

        for key, value in segment.items():
            if value and key not in [api.NETWORK_TYPE,
                                     api.SEGMENTATION_ID]:
                msg = (_("%(key)s prohibited for %(tunnel)s provider network")
                       % {'key': key, 'tunnel': segment.get(api.NETWORK_TYPE)})
                raise exc.InvalidInput(error_message=msg)

    def allocate_tenant_segment(self, session):
        alloc = self.allocate_partially_specified_segment(session)
        if not alloc:
            return
        return {api.NETWORK_TYPE: self.get_type(),
                api.PHYSICAL_NETWORK: None,
                api.SEGMENTATION_ID: alloc.isid}

    def is_partial_segment(self, segment):
        return segment.get(api.SEGMENTATION_ID) is None

    def reserve_provider_segment(self, session, segment):
        if self.is_partial_segment(segment):
            alloc = self.allocate_partially_specified_segment(session)
            if not alloc:
                raise exc.NoNetworkAvailable()
        else:
            segmentation_id = segment.get(api.SEGMENTATION_ID)
            alloc = self.allocate_fully_specified_segment(
                session, isid=segmentation_id)
            if not alloc:
                raise exc.TunnelIdInUse(tunnel_id=segmentation_id)
        return {api.NETWORK_TYPE: self.get_type(),
                api.PHYSICAL_NETWORK: None,
                api.SEGMENTATION_ID: alloc.isid}

    def release_segment(self, session, segment):
        isid_id = segment[api.SEGMENTATION_ID]

        inside = any(lo <= isid_id <= hi for lo, hi in self.isid_ranges)

        info = {'type': self.get_type(), 'id': isid_id}
        with session.begin(subtransactions=True):
            query = (session.query(models.IsidAllocation).
                     filter_by(isid=isid_id))
            if inside:
                count = query.update({"allocated": False})
                if count:
                    LOG.debug("Releasing %(type)s %(id)s to pool",
                              info)
            else:
                count = query.delete()
                if count:
                    LOG.debug("Releasing %(type)s %(id)s outside pool",
                              info)
        if not count:
            LOG.warning(_LW("%(type)s %(id)s not found"), info)

    def _get_allocation(self, session, segment):
        return session.query(models.IsidAllocation).filter_by(
            isid=segment).first()
