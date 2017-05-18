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


import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_service import periodic_task
from oslo_service import service

from neutron._i18n import _LE
from neutron._i18n import _LW
from neutron.agent.common import config
from neutron.agent import rpc as agent_rpc
from neutron.common import config as common_config
from neutron.common import eventlet_utils
from neutron.common import topics
from neutron import context as n_context
from neutron import manager
from neutron import service as neutron_service

from networking_avaya.ml2 import const
from networking_avaya.ml2.drivers import rpc
from networking_avaya.sdn import client


eventlet_utils.monkey_patch()


LOG = logging.getLogger(__name__)


agent_opts = [
    cfg.IntOpt('tx_check_interval',
               default=30,
               help='The amount of seconds between checks of transaction '
                    'status on SDN controller'),
    cfg.URIOpt('sdn_url',
               required=True,
               help='Base url of SDN REST API'),
    cfg.StrOpt('sdn_username',
               required=True,
               help='Username for authorization on SDN'),
    cfg.StrOpt('sdn_password',
               required=True,
               help='Password for authorization on SDN'),
    cfg.StrOpt('sdn_cert_path',
               help='Path to a file with CA certificate for SDN. If it is not '
                    'specified, default CAs will be used. If empty string, '
                    'verification will be disabled.'),
]


cfg.CONF.register_opts(agent_opts, "avaya_mapping_agent")


class NoOpenStackID(Exception):
    pass


class AvayaMappingAgent(manager.Manager):

    def __init__(self, host):
        super(AvayaMappingAgent, self).__init__(host=host)
        self.agent_state = {
            'binary': 'avaya-mapping-agent',
            'host': host,
            'topic': const.AVAYA_MAPPING_RPC,
            'configurations': {},
            'start_flag': True,
            'agent_type': const.AVAYA_MAPPING_AGENT}
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.REPORTS)
        self.avaya_driver_rpc = rpc.ML2DriverAPI()
        self.context = n_context.get_admin_context_without_session()
        report_interval = cfg.CONF.AGENT.report_interval
        if report_interval:
            self.heartbeat = loopingcall.FixedIntervalLoopingCall(
                self._report_state)
            self.heartbeat.start(interval=report_interval)
        self.first_start = True
        self.tx_ids = set()
        agent_conf = cfg.CONF.avaya_mapping_agent
        self.sdn_client = client.AvayaSDNClient(
            agent_conf.sdn_url, agent_conf.sdn_username,
            agent_conf.sdn_password, agent_conf.sdn_cert_path)

    def _report_state(self):
        try:
            self.state_rpc.report_state(self.context,
                                        self.agent_state,
                                        self.first_start)
        except AttributeError:
            # This means the server does not support report_state
            LOG.warning(_LW('Neutron server does not support state report.'
                            ' State report for this agent will be disabled.'))
            self.heartbeat.stop()
            return
        except Exception:
            LOG.exception(_LE("Failed reporting state!"))
            return
        self.agent_state.pop("start_flag", None)
        self.first_start = False

    def _compare_and_set_openstack_id(self, openstack_id):
        old_id = self.sdn_client.openstack_id
        if not old_id:
            self.sdn_client.openstack_id = openstack_id
        elif old_id != openstack_id:
            LOG.error(_LE("Openstack id changed from %(old)s to %(new)s"),
                      {"old": old_id, "new": openstack_id})

    def create_mapping(self, context, openstack_id, mapping):
        LOG.debug("Got create_mapping call for mapping %s", mapping)
        self._compare_and_set_openstack_id(openstack_id)
        tx_id = self.sdn_client.create_network(mapping)
        self.tx_ids.add(tx_id)
        LOG.debug("Got transaction_id %s", tx_id)
        return tx_id

    def delete_mapping(self, context, openstack_id, mapping):
        LOG.debug("Got delete_mapping call for mapping %s", mapping)
        self._compare_and_set_openstack_id(openstack_id)
        tx_id = self.sdn_client.delete_network(mapping)
        self.tx_ids.add(tx_id)
        LOG.debug("Got transaction_id %s", tx_id)
        return tx_id

    def get_openstack_id(self, context):
        LOG.debug("Got get_openstack_id call")
        return self.sdn_client.get_openstack_id()

    @periodic_task.periodic_task(spacing=1)
    def check_transactions_state(self, context):
        tx_ids = set(self.tx_ids)
        LOG.debug("Periodical check of transactions state %s", tx_ids)
        if tx_ids:
            completed = self.sdn_client.get_transactions_status(tx_ids)
            LOG.debug("Completed transactions: %s", tx_ids)
            self.avaya_driver_rpc.transactions_done(context, completed)
            self.tx_ids -= completed

    def after_start(self):
        pass


def main():
    # cfg.CONF(project='neutron')
    common_config.init(sys.argv[1:])
    config.register_agent_state_opts_helper(cfg.CONF)
    config.setup_logging()
    mgr = 'networking_avaya.ml2.agent.avaya_mapping_agent.AvayaMappingAgent'
    server = neutron_service.Service.create(
        binary='avaya-mapping-agent',
        topic=const.AVAYA_MAPPING_RPC,
        report_interval=0,
        periodic_interval=cfg.CONF.avaya_mapping_agent.tx_check_interval,
        manager=mgr)
    service.launch(cfg.CONF, server).wait()
