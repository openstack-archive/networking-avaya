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
from six import moves
import testtools
from testtools import matchers

from neutron.common import exceptions as exc
from neutron.db import api as db
from neutron.plugins.ml2 import driver_api as api
from neutron.tests.unit import testlib_api

from networking_avaya.ml2 import const
from networking_avaya.ml2.drivers import type_isid

ISID_MIN = 100
ISID_MAX = 109
ISID_RANGES = [(ISID_MIN, ISID_MAX)]
UPDATED_ISID_RANGES = [(ISID_MIN + 5, ISID_MAX + 5)]


class AvayaIsidTypeTest(testlib_api.SqlTestCase):

    def setUp(self):
        super(AvayaIsidTypeTest, self).setUp()
        self.TYPE = const.TYPE_ISID
        self.driver = type_isid.AvayaIsidTypeDriver()
        self.driver.isid_ranges = ISID_RANGES
        self.driver._sync_allocations()
        self.session = db.get_session()

    def test_get_type(self):
        self.assertEqual(self.TYPE, self.driver.get_type())

    def test_validate_provider_segment(self):
        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.PHYSICAL_NETWORK: "phys_net",
                   api.SEGMENTATION_ID: None}

        with testtools.ExpectedException(exc.InvalidInput, ".*specified.*"):
            self.driver.validate_provider_segment(segment)

        segment[api.PHYSICAL_NETWORK] = None
        self.driver.validate_provider_segment(segment)

        segment[api.SEGMENTATION_ID] = 1
        self.driver.validate_provider_segment(segment)

        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.SEGMENTATION_ID: None,
                   'bad_key': "bad_value"}

        with testtools.ExpectedException(exc.InvalidInput, ".*prohibited.*"):
            self.driver.validate_provider_segment(segment)

    def test_sync_isid_allocations(self):
        self.assertIsNone(
            self.driver._get_allocation(self.session, (ISID_MIN - 1)))
        self.assertFalse(
            self.driver._get_allocation(self.session, (ISID_MIN)).allocated)
        self.assertFalse(
            self.driver._get_allocation(self.session,
                                        (ISID_MIN + 1)).allocated)
        self.assertFalse(
            self.driver._get_allocation(self.session,
                                        (ISID_MAX - 1)).allocated)
        self.assertFalse(
            self.driver._get_allocation(self.session, (ISID_MAX)).allocated)
        self.assertIsNone(
            self.driver._get_allocation(self.session, (ISID_MAX + 1)))

        self.driver.isid_ranges = UPDATED_ISID_RANGES
        self.driver._sync_allocations()

        self.assertIsNone(
            self.driver._get_allocation(self.session, (ISID_MIN + 5 - 1)))
        self.assertFalse(
            self.driver._get_allocation(self.session,
                                        (ISID_MIN + 5)).allocated)
        self.assertFalse(
            self.driver._get_allocation(self.session,
                                        (ISID_MIN + 5 + 1)).allocated)
        self.assertFalse(
            self.driver._get_allocation(self.session,
                                        (ISID_MAX + 5 - 1)).allocated)
        self.assertFalse(
            self.driver._get_allocation(self.session,
                                        (ISID_MAX + 5)).allocated)
        self.assertIsNone(
            self.driver._get_allocation(self.session, (ISID_MAX + 5 + 1)))

    def _test_sync_allocations_and_allocated(self, isid):
        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.PHYSICAL_NETWORK: None,
                   api.SEGMENTATION_ID: isid}
        self.driver.reserve_provider_segment(self.session, segment)

        self.driver.isid_ranges = UPDATED_ISID_RANGES
        self.driver._sync_allocations()

        self.assertTrue(
            self.driver._get_allocation(self.session, isid).allocated)

    def test_sync_allocations_and_allocated_in_initial_range(self):
        self._test_sync_allocations_and_allocated(ISID_MIN + 2)

    def test_sync_allocations_and_allocated_in_final_range(self):
        self._test_sync_allocations_and_allocated(ISID_MAX + 2)

    def test_sync_allocations_no_op(self):

        def verify_no_chunk(iterable, chunk_size):
            # no segment removed/added
            self.assertEqual(0, len(list(iterable)))
            return []
        with mock.patch.object(
                type_isid, 'chunks', side_effect=verify_no_chunk) as chunks:
            self.driver._sync_allocations()
            self.assertEqual(2, len(chunks.mock_calls))

    def test_partial_segment_is_partial_segment(self):
        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.PHYSICAL_NETWORK: None,
                   api.SEGMENTATION_ID: None}
        self.assertTrue(self.driver.is_partial_segment(segment))

    def test_specific_segment_is_not_partial_segment(self):
        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.PHYSICAL_NETWORK: None,
                   api.SEGMENTATION_ID: 101}
        self.assertFalse(self.driver.is_partial_segment(segment))

    def test_reserve_provider_segment_full_specs(self):
        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.PHYSICAL_NETWORK: None,
                   api.SEGMENTATION_ID: 101}
        observed = self.driver.reserve_provider_segment(self.session, segment)
        alloc = self.driver._get_allocation(self.session,
                                            observed[api.SEGMENTATION_ID])
        self.assertTrue(alloc.allocated)

        with testtools.ExpectedException(exc.TunnelIdInUse):
            self.driver.reserve_provider_segment(self.session, segment)

        self.driver.release_segment(self.session, segment)
        alloc = self.driver._get_allocation(self.session,
                                            observed[api.SEGMENTATION_ID])
        self.assertFalse(alloc.allocated)

        segment[api.SEGMENTATION_ID] = 1000
        observed = self.driver.reserve_provider_segment(self.session, segment)
        alloc = self.driver._get_allocation(self.session,
                                            observed[api.SEGMENTATION_ID])
        self.assertTrue(alloc.allocated)

        self.driver.release_segment(self.session, segment)
        alloc = self.driver._get_allocation(self.session,
                                            observed[api.SEGMENTATION_ID])
        self.assertIsNone(alloc)

    def test_reserve_provider_segment(self):
        isid_ids = set()
        specs = {api.NETWORK_TYPE: self.TYPE,
                 api.PHYSICAL_NETWORK: None,
                 api.SEGMENTATION_ID: None}

        for x in moves.range(ISID_MIN, ISID_MAX + 1):
            segment = self.driver.reserve_provider_segment(self.session,
                                                           specs)
            self.assertEqual(self.TYPE, segment[api.NETWORK_TYPE])
            self.assertThat(segment[api.SEGMENTATION_ID],
                            matchers.GreaterThan(ISID_MIN - 1))
            self.assertThat(segment[api.SEGMENTATION_ID],
                            matchers.LessThan(ISID_MAX + 1))
            isid_ids.add(segment[api.SEGMENTATION_ID])

        with testtools.ExpectedException(exc.NoNetworkAvailable):
            segment = self.driver.reserve_provider_segment(self.session,
                                                           specs)

        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.PHYSICAL_NETWORK: None,
                   api.SEGMENTATION_ID: isid_ids.pop()}
        self.driver.release_segment(self.session, segment)
        segment = self.driver.reserve_provider_segment(self.session, specs)
        self.assertThat(segment[api.SEGMENTATION_ID],
                        matchers.GreaterThan(ISID_MIN - 1))
        self.assertThat(segment[api.SEGMENTATION_ID],
                        matchers.LessThan(ISID_MAX + 1))
        isid_ids.add(segment[api.SEGMENTATION_ID])

        for isid_id in isid_ids:
            segment[api.SEGMENTATION_ID] = isid_id
            self.driver.release_segment(self.session, segment)

    def test_allocate_tenant_segment(self):
        isid_ids = set()
        for x in moves.range(ISID_MIN, ISID_MAX + 1):
            segment = self.driver.allocate_tenant_segment(self.session)
            self.assertThat(segment[api.SEGMENTATION_ID],
                            matchers.GreaterThan(ISID_MIN - 1))
            self.assertThat(segment[api.SEGMENTATION_ID],
                            matchers.LessThan(ISID_MAX + 1))
            isid_ids.add(segment[api.SEGMENTATION_ID])

        segment = self.driver.allocate_tenant_segment(self.session)
        self.assertIsNone(segment)

        segment = {api.NETWORK_TYPE: self.TYPE,
                   api.PHYSICAL_NETWORK: None,
                   api.SEGMENTATION_ID: isid_ids.pop()}
        self.driver.release_segment(self.session, segment)
        segment = self.driver.allocate_tenant_segment(self.session)
        self.assertThat(segment[api.SEGMENTATION_ID],
                        matchers.GreaterThan(ISID_MIN - 1))
        self.assertThat(segment[api.SEGMENTATION_ID],
                        matchers.LessThan(ISID_MAX + 1))
        isid_ids.add(segment[api.SEGMENTATION_ID])

        for isid_id in isid_ids:
            segment[api.SEGMENTATION_ID] = isid_id
            self.driver.release_segment(self.session, segment)

    def test_parse_non_integer_range(self):
        bad_range = ["abc:def"]
        with mock.patch.object(self.driver, "_verify_isid_range") as verify:
            with testtools.ExpectedException(exc.NetworkTunnelRangeError):
                self.driver._parse_isid_ranges(bad_range)
            self.assertEqual(0, len(verify.mock_calls))

    def test_parse_good_range(self):
        good_range = ["100:200"]
        with mock.patch.object(self.driver, "_verify_isid_range") as verify:
            self.assertEqual([(100, 200)],
                             self.driver._parse_isid_ranges(good_range))
            self.assertEqual(1, len(verify.mock_calls))

    def test_parse_multiple_good_ranges(self):
        good_ranges = ["100:200", "300:400"]
        with mock.patch.object(self.driver, "_verify_isid_range") as verify:
            self.assertEqual([(100, 200), (300, 400)],
                             self.driver._parse_isid_ranges(good_ranges))
            self.assertEqual(2, len(verify.mock_calls))

    def test_verify_out_of_range(self):
        bad_range = (const.ISID_MIN, const.ISID_MAX + 1)
        with testtools.ExpectedException(exc.NetworkTunnelRangeError,
                                         ".*identifier.*"):
            self.driver._verify_isid_range(bad_range)

        bad_range = (const.ISID_MIN - 1, const.ISID_MAX)
        with testtools.ExpectedException(exc.NetworkTunnelRangeError,
                                         ".*identifier.*"):
            self.driver._verify_isid_range(bad_range)

    def test_verify_wrong_order_of_range(self):
        bad_range = (200, 100)
        with testtools.ExpectedException(exc.NetworkTunnelRangeError,
                                         ".*is less.*"):
            self.driver._verify_isid_range(bad_range)

    def test_verify_good_range(self):
        good_range = (100, 200)
        self.assertIsNone(self.driver._verify_isid_range(good_range))


class AvayaIsidTypeMultiRangeTest(testlib_api.SqlTestCase):
    ISID_MIN0 = 100
    ISID_MAX0 = 101
    ISID_MIN1 = 200
    ISID_MAX1 = 201
    ISID_MULTI_RANGES = [(ISID_MIN0, ISID_MAX0), (ISID_MIN1, ISID_MAX1)]

    def setUp(self):
        super(AvayaIsidTypeMultiRangeTest, self).setUp()
        self.driver = type_isid.AvayaIsidTypeDriver()
        self.driver.isid_ranges = self.ISID_MULTI_RANGES
        self.driver._sync_allocations()
        self.session = db.get_session()

    def test_release_segment(self):
        segments = [self.driver.allocate_tenant_segment(self.session)
                    for i in range(4)]

        # Release them in random order. No special meaning.
        for i in (0, 2, 1, 3):
            self.driver.release_segment(self.session, segments[i])

        for key in (self.ISID_MIN0, self.ISID_MAX0,
                    self.ISID_MIN1, self.ISID_MAX1):
            alloc = self.driver._get_allocation(self.session, key)
            self.assertFalse(alloc.allocated)
