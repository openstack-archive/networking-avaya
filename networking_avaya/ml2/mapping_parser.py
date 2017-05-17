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

from neutron._i18n import _LE
from neutron._i18n import _LW
from oslo_config import cfg
from oslo_log import log as logging


LOG = logging.getLogger(__name__)


def parse_static_mappings(config_file):
    STATIC_MAPPINGS = defaultdict(lambda: defaultdict(set))
    SWITCH_PORTS = defaultdict(defaultdict)
    HOST_IPS = {}
    list_parser = cfg.types.List()
    sections = {}
    parser = cfg.ConfigParser(config_file, sections)
    try:
        parser.parse()
    except IOError as e:
        LOG.error(_LE("Error while parsing static mappings file %(file)s: "
                  "%(error)s"), {'file': config_file, 'error': e.strerror})
        return STATIC_MAPPINGS

    for host, mappings in sections.iteritems():
        host_ip = mappings.pop("host_ip", None)
        if not host_ip:
            raise ValueError("No host_ip for host %s" % host)
        HOST_IPS[host] = host_ip
        for physnet, maps in mappings.iteritems():
            for mapping in list_parser(maps[0]):
                try:
                    (switch, port) = mapping.split(":")
                except ValueError:
                    raise ValueError("Wrong format of static mapping for "
                                     "host %s: %s" % (host, mapping))
                if not switch or not port:
                    raise ValueError("Switch or port are empty")
                if (switch, port) in STATIC_MAPPINGS[host][physnet]:
                    raise ValueError("Duplicate values for ports in physnet "
                                     "%s for host %s" % (physnet, host))
                if port in SWITCH_PORTS[switch]:
                    old_host = SWITCH_PORTS[switch][port]
                    raise ValueError("Host %s is attached to same port %s on "
                                     "switch %s as host %s" %
                                     (host, port, switch, old_host))
                STATIC_MAPPINGS[host][physnet].add((switch, port))
                SWITCH_PORTS[switch][port] = host

    if not STATIC_MAPPINGS:
        LOG.warning(_LW("No mappings in config file %s"), config_file)
    return dict(STATIC_MAPPINGS), HOST_IPS
