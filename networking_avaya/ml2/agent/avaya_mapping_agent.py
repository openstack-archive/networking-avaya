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
import uuid

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


eventlet_utils.monkey_patch()


LOG = logging.getLogger(__name__)


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

    def create_mapping(self, context, mapping):
        LOG.debug("Got create_mapping call for mapping %s", mapping)
        tx_id = str(uuid.uuid4())
        self.tx_ids.add(tx_id)
        return tx_id

    def delete_mapping(self, context, mapping):
        LOG.debug("Got delete_mapping call for mapping %s", mapping)
        tx_id = str(uuid.uuid4())
        self.tx_ids.add(tx_id)
        return tx_id

    @periodic_task.periodic_task(spacing=1, run_immediately=True)
    def check_transactions_state(self, context):
        tx_ids = set(self.tx_ids)
        LOG.debug("Periodical check of transactions state %s", tx_ids)
        if tx_ids:
            self.avaya_driver_rpc.transactions_done(context, tx_ids)
            self.tx_ids -= tx_ids


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
        manager=mgr)
    service.launch(cfg.CONF, server).wait()
