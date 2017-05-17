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


from collections import defaultdict
import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_service import service

from neutron._i18n import _LE
from neutron._i18n import _LI
from neutron._i18n import _LW
from neutron.agent.common import config
from neutron.agent.linux import async_process
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


lldp_opts = [
    cfg.StrOpt('lldp_physnet_interfaces',
               default=[],
               help='Comma-separated list of <physnet>:<intf1>[:<intf2>]... '
                    'mappings. Each physnet should have at least one '
                    'interface. If physnet attached to bond, all of slaves '
                    'should be included'),
    cfg.IntOpt('lldp_timeout',
               default=30,
               help='The amount of seconds to wait for LLDP packets.'),
    cfg.IntOpt('lldp_monitor_interval',
               default=5,
               help='The amount of seconds between checks for LLDP packets'),
    cfg.IPOpt('management_ip',
              help='IP address which will be used by SDN to configure OVS'),
]

cfg.CONF.register_opts(lldp_opts, "avaya_discovery_agent")


class AvayaLLDPAgent(manager.Manager):

    def __init__(self, host):
        super(AvayaLLDPAgent, self).__init__(host=host)
        self.agent_state = {
            'binary': 'avaya-discovery-agent',
            'host': host,
            'topic': 'N/A',
            'configurations': {},
            'start_flag': True,
            'agent_type': const.AVAYA_DISCOVERY_AGENT}
        mgmt_ip = cfg.CONF.avaya_discovery_agent.management_ip
        if mgmt_ip:
            self.agent_state['configurations']['management_ip'] = mgmt_ip
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.REPORTS)
        self.avaya_driver_rpc = rpc.ML2DriverAPI()
        self.context = n_context.get_admin_context_without_session()
        report_interval = cfg.CONF.AGENT.report_interval
        if report_interval:
            self.heartbeat = loopingcall.FixedIntervalLoopingCall(
                self._report_state)
            self.heartbeat.start(interval=report_interval)
        self.first_start = True
        interfaces = cfg.CONF.avaya_discovery_agent.lldp_physnet_interfaces
        timeout = str(cfg.CONF.avaya_discovery_agent.lldp_timeout)
        self.lldp_catcher = async_process.AsyncProcess(
            ["avaya-lldp-catcher", "-t", timeout, interfaces],
            run_as_root=True)
        self.lldp_monitor = loopingcall.FixedIntervalLoopingCall(
            self._process_lldp)

    def send_lldp(self, lldp_info):
        LOG.debug("Will send this info %s", lldp_info)
        self.avaya_driver_rpc.update_dynamic_mapping(self.context,
                                                     self.host, lldp_info)

    def _process_lldp(self):
        lldp_info = defaultdict(set)
        for line in self.lldp_catcher.iter_stdout():
            physnet, switch, port = line.split(' ')
            lldp_info[physnet].add((switch, port))
        if lldp_info:
            self.send_lldp(lldp_info)

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

    def after_start(self):
        self.avaya_driver_rpc.drop_dynamic_mappings(self.context, self.host)
        self.lldp_catcher.start()
        interval = cfg.CONF.avaya_discovery_agent.lldp_monitor_interval
        self.lldp_monitor.start(interval=interval)
        LOG.info(_LI("Agent started"))


def main():
    # cfg.CONF(project='neutron')
    common_config.init(sys.argv[1:])
    config.register_agent_state_opts_helper(cfg.CONF)
    config.setup_logging()
    mgr = 'networking_avaya.ml2.agent.avaya_discovery_agent.AvayaLLDPAgent'
    server = neutron_service.Service.create(
        binary='avaya-discovery-agent',
        topic=None,
        report_interval=0,
        manager=mgr)
    service.launch(cfg.CONF, server).wait()
