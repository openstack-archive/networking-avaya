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


import contextlib
import ctypes
import fcntl
import re
import select
import signal
import six
import socket
import struct
import sys

from oslo_config import cfg

CONF = cfg.CONF

BPF_FAILURE = 0
BPF_JEQ = 0x15
BPF_LDH = 0x28
BPF_RET = 0x06
BPF_SUCCESS = 0x40000
ETHERTYPE_ALL = 0x0003
ETHERTYPE_OFFSET = 0x0c
IFF_PROMISC = 0x100
LLDP_ETHERTYPE = 0x88cc
PORT_MATCH = re.compile("Port (\d+/\d+)")
PORT_TLV = 4
SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914
SO_ATTACH_FILTER = 26
SWITCH_TLV = 8
TLV_HDR_LEN = 2


killed = False


lldp_opts = [
    cfg.ListOpt('interfaces',
                positional=True,
                default=[],
                help='Comma-separated list of <physnet>:<intf1>[:<intf2>]... '
                     'mappings. Each physnet should have at least one '
                     'interface. If physnet attached to bond, all of slaves '
                     'should be included'),
    cfg.IntOpt('timeout',
               default=30,
               short='t',
               help='The amount of seconds to wait for LLDP packets.'),
]


FILTERS_OPS = [
    [BPF_LDH, 0, 0, ETHERTYPE_OFFSET],
    [BPF_JEQ, 0, 1, LLDP_ETHERTYPE],
    [BPF_RET, 0, 0, BPF_SUCCESS],
    [BPF_RET, 0, 0, BPF_FAILURE]
]


FILTERS_STR = b"".join(map(lambda v: struct.pack("HBBI", *v), FILTERS_OPS))


def log_error(message, **kwargs):
    six.print_(message.format(**kwargs), file=sys.stderr)


class ifreq(ctypes.Structure):
    _fields_ = [("ifr_ifrn", ctypes.c_char * 16),
                ("ifr_flags", ctypes.c_short)]


class RawSocket(object):
    def __init__(self, intf_name, physnet):
        self.intf_name = intf_name
        self.physnet = physnet
        self.ifr = ifreq()
        self.ifr.ifr_ifrn = intf_name
        self.socket = None

    def start(self):
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, ETHERTYPE_ALL)
        fcntl.ioctl(s.fileno(), SIOCGIFFLAGS, self.ifr)
        self.ifr.ifr_flags |= IFF_PROMISC
        fcntl.ioctl(s.fileno(), SIOCSIFFLAGS, self.ifr)
        buf = ctypes.create_string_buffer(FILTERS_STR)
        fprog = struct.pack("HL", len(FILTERS_OPS), ctypes.addressof(buf))
        s.setsockopt(socket.SOL_SOCKET, SO_ATTACH_FILTER, fprog)
        s.bind((self.intf_name, ETHERTYPE_ALL))
        self.socket = s

    def stop(self):
        assert(self.socket is not None)
        self.ifr.ifr_flags ^= IFF_PROMISC
        try:
            fcntl.ioctl(self.socket.fileno(), SIOCSIFFLAGS, self.ifr)
            self.socket.close()
        except Exception as e:
            log_error("Cannot close socket for interface {name}: {error}",
                      name=self.intf_name, error=e)


def _parse_tlvs(lldp_packet):
    lldp_info = {}
    lldp_packet = lldp_packet[14:]
    while len(lldp_packet) >= TLV_HDR_LEN:
        header = struct.unpack('!H', lldp_packet[:TLV_HDR_LEN])[0]
        type_ = (header & 0xfe00) >> 9
        len_ = (header & 0x01ff)
        next_ = len_ + TLV_HDR_LEN
        lldp_info[type_] = lldp_packet[TLV_HDR_LEN:next_]
        lldp_packet = lldp_packet[next_:]
    return lldp_info


def _parse_switch_and_port(lldp_packet):
    lldp_info = _parse_tlvs(lldp_packet)
    switch_info = lldp_info.get(SWITCH_TLV, None)
    port_info = lldp_info.get(PORT_TLV, None)
    if not switch_info and not port_info:
        # log_error("No switch and port TLVs in LLDP packet, ignored")
        return
    switch_ip = ".".join([str(ord(i)) for i in switch_info[2:6]])
    port = PORT_MATCH.search(port_info)
    if not port:
        # LOG.debug("LLDP PortDesc TLV: %s", port_info)
        log_error("Port was not found in LLDP for switch {}".format(switch_ip))
        return
    return (switch_ip, port.groups()[0])


def parse_interfaces(interfaces):
    ret = {}
    physnets = set()
    for interface in interfaces:
        splitted = interface.split(":")
        physnet = splitted[0]
        if physnet in physnets:
            raise ValueError("Physnet %s specified multiple times" % physnet)
        physnets.add(physnet)
        intfs = splitted[1:]
        if not intfs:
            raise ValueError("Physnet %s must have at least one interface"
                             % physnet)
        for intf in intfs:
            if intf in ret:
                raise ValueError("Interface %s cannot appears in two physnets"
                                 % intf)
            ret[intf] = physnet
    return ret


@contextlib.contextmanager
def raw_sockets(interfaces):
    sockets = []
    for intf_name, physnet in six.iteritems(interfaces):
        s = RawSocket(intf_name, physnet)
        try:
            s.start()
        except Exception:
            for s in sockets:
                s.stop()
            raise
        sockets.append(s)
    try:
        yield sockets
    finally:
        for s in sockets:
            s.stop()


def get_lldp_info(sockets):
    socks = []
    physnets = {}
    for s in sockets:
        socks.append(s.socket)
        physnets[s.socket] = s.physnet
    socks = [s.socket for s in sockets]
    rlist, _, _ = select.select(socks, [], [], CONF.timeout)
    for s in rlist:
        physnet = physnets[s]
        lldp_info = _parse_switch_and_port(s.recv(2048))
        if lldp_info:
            six.print_(physnet, lldp_info[0], lldp_info[1],
                       flush=True)


def handle_signal(signum, frame):
    global killed
    killed = True


def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    CONF.register_cli_opts(lldp_opts)
    CONF()
    interfaces = parse_interfaces(CONF.interfaces)
    if not interfaces:
        CONF.print_help()
        sys.exit(1)
    log_error("lldp_catcher started with interfaces: {interfaces}",
              interfaces=",".join(interfaces))
    with raw_sockets(interfaces) as sockets:
        while (not killed):
            get_lldp_info(sockets)

main()
