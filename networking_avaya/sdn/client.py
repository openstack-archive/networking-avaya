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

import requests
from six.moves.urllib.parse import urljoin

from oslo_log import log as logging


BASE_ENDPOINT = "network/v1.0/"


ENDPOINTS = {"register": "register",
             "register_ports": "register/{openstack_id}/switch/{switch_ip}",
             "network": "{openstack_id}",
             "transaction": "transaction/{openstack_id}/{tx_ids}"}


LOG = logging.getLogger(__name__)


SDN_TIMEOUT = 10


class AvayaSDNClient(object):
    def __init__(self, url, user, password, ca_path):
        ca_path = ca_path if ca_path != '' else False
        self._url = urljoin(url, BASE_ENDPOINT)
        self._session = requests.Session()
        self._session.auth = requests.auth.HTTPBasicAuth(user, password)
        self._session.verify = ca_path
        self.openstack_id = None

    def _get_url(self, kind='network', **kwargs):
        if self.openstack_id and 'openstack_id' not in kwargs:
            kwargs['openstack_id'] = self.openstack_id
        res = urljoin(self._url, ENDPOINTS[kind].format(**kwargs))
        return res

    def _format_network_from_mapping(self, mapping):
        network = []
        for switch, port in mapping['switch_ports']:
            network.append({"switch_ip": switch,
                            "port": port,
                            "bindings": [{"vlan": mapping['vlan'],
                                          "isid": mapping['isid']}]})
        req = {'switch_port_bindings': network}
        try:
            req['compute_host_ip'] = mapping['management_ip']
            req['ovs_bridge'] = mapping['bridge_name']
        except KeyError:
            pass
        return req

    def _parse_tx_id_from_response(self, response):
        tx = response.headers.get('Location')
        if not tx:
            return ""
        return tx.split("/")[-1]

    def _try_request(self, method, expected_status, log_location=False,
                     **kwargs):
        ret = method(timeout=SDN_TIMEOUT, **kwargs)
        location = ""
        if log_location:
            location = " ,location={}".format(ret.headers.get('Location'))
        LOG.debug("%s: url=%s, request_headers=%s, code=%s, req_body=%s,"
                  "resp_body=%s%s", method.func_name, ret.request.url,
                  ret.request.headers, ret.status_code, ret.request.body,
                  ret.text, location)
        ret.raise_for_status()
        if expected_status and ret.status_code != expected_status:
            raise Exception("Unexpected HTTP status code %s on %s" %
                            (ret.status_code, method.func_name))
        return ret

    def get_openstack_id(self):
        endpoint = self._get_url('register')
        ret = self._try_request(self._session.post, requests.codes.OK,
                                url=endpoint)
        try:
            openstack_id = ret.json()['openstack_id']
            LOG.debug("Got openstack_id from SDN: %s", openstack_id)
        except Exception:
            # TODO(Yar): Delete when dummy controller will return any ID
            openstack_id = "fake-openstack-id"
        self.openstack_id = openstack_id
        return openstack_id

    def create_network(self, mapping):
        endpoint = self._get_url()
        network = self._format_network_from_mapping(mapping)
        ret = self._try_request(self._session.post, requests.codes.ACCEPTED,
                                log_location=True, url=endpoint, json=network)
        return self._parse_tx_id_from_response(ret)

    def delete_network(self, mapping):
        endpoint = self._get_url()
        network = self._format_network_from_mapping(mapping)
        ret = self._try_request(self._session.delete, requests.codes.ACCEPTED,
                                log_location=True, url=endpoint, json=network)
        return self._parse_tx_id_from_response(ret)

    def get_transactions_status(self, tx_ids):
        if not tx_ids:
            return
        endpoint = self._get_url('transaction', tx_ids=','.join(tx_ids))
        ret = self._try_request(self._session.get, requests.codes.OK,
                                url=endpoint)
        res = set()
        for i in ret.json():
                if i['status'] == 'Completed':
                    res.add(i['transaction_id'])
        return res
