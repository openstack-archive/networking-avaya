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

import Queue
import uuid

from oslo_config import cfg
import oslo_messaging

from neutron.agent import rpc as a_rpc
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron import context

from networking_avaya.ml2 import const


class FakeMappingAgent(object):
    def __init__(self, rpc_url, host):
        self.state = {
            'binary': 'avaya-mapping-agent',
            'host': host,
            'topic': 'N/A',
            'configurations': {},
            'start_flag': True,
            'agent_type': const.AVAYA_MAPPING_AGENT}
        oslo_messaging.set_transport_defaults(control_exchange='neutron')
        n_rpc.TRANSPORT = oslo_messaging.get_transport(cfg.CONF, url=rpc_url)
        self.report_api = a_rpc.PluginReportStateAPI(topics.REPORTS)
        self.ctx = context.get_admin_context_without_session()
        self.report_state()
        serializer = n_rpc.RequestContextSerializer(None)
        target = oslo_messaging.Target(topic=const.AVAYA_MAPPING_RPC,
                                       version='1.0', server=host)
        self.rpc_server = oslo_messaging.get_rpc_server(
            n_rpc.TRANSPORT, target, [self], 'blocking', serializer)
        self.events = Queue.Queue()

    def report_state(self):
        self.report_api.report_state(self.ctx, self.state)
        self.state.pop('start_flag', None)

    def create_mapping(self, context, openstack_id, mapping):
        tx_id = str(uuid.uuid4())
        self.events.put({'action': 'create', 'request_id': context.request_id,
                         'tx_id': tx_id, 'mapping': mapping})
        return tx_id

    def delete_mapping(self, context, openstack_id, mapping):
        tx_id = str(uuid.uuid4())
        self.events.put({'action': 'delete', 'request_id': context.request_id,
                         'tx_id': tx_id, 'mapping': mapping})
        return tx_id

    def get_openstack_id(self, context):
        return "fake-openstack-id"

    def transactions_done(self, tx_ids):
        target = oslo_messaging.Target(topic=const.AVAYA_ML2,
                                       version='1.0')
        cctxt = n_rpc.get_client(target).prepare()
        cctxt.call(self.ctx, 'transactions_done', tx_ids=tx_ids)

    def start(self):
        self.rpc_server.start()

    def stop(self):
        self.rpc_server.stop()
        self.rpc_server.wait()

    def get_mapping_event(self, timeout=30):
        try:
            return self.events.get(timeout=timeout)
        except Queue.Empty:
            return None
