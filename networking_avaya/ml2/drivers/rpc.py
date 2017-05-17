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

import oslo_messaging

from neutron.common import rpc as n_rpc

from networking_avaya.db import models
from networking_avaya.ml2 import const


class AgentMappingAPI(object):
    def __init__(self):
        target = oslo_messaging.Target(topic=const.AVAYA_MAPPING_RPC,
                                       version='1.0')
        self.client = n_rpc.get_client(target)

    def create_mapping(self, context, mapping):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'create_mapping', mapping=mapping)

    def delete_mapping(self, context, mapping):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'delete_mapping', mapping=mapping)


class ML2DriverAPI(object):
    def __init__(self):
        target = oslo_messaging.Target(topic=const.AVAYA_ML2,
                                       version='1.0')
        self.client = n_rpc.get_client(target)

    def transactions_done(self, context, tx_ids):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'transactions_done',
                          tx_ids=tx_ids)

    def update_dynamic_mapping(self, context, mapping_host, lldp_info):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'update_dynamic_mapping',
                          mapping_host=mapping_host, lldp_info=lldp_info)

    def drop_dynamic_mappings(self, context, mapping_host):
        cctxt = self.client.prepare()
        return cctxt.call(context, 'drop_dynamic_mappings',
                          mapping_host=mapping_host)


class AvayaCallbacks(object):

    def transactions_done(self, context, tx_ids):
        session = context.session
        models.mapping_delete_or_set_active(session, tx_ids)

    def update_dynamic_mapping(self, context, mapping_host, lldp_info):
        session = context.session
        models.dynamic_mapping_create_or_update(session, mapping_host,
                                                lldp_info)

    def drop_dynamic_mappings(self, context, mapping_host):
        session = context.session
        models.drop_dynamic_mappings(session, mapping_host)
