#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2016, Hugh Ma <Hugh.Ma@flextronics.com>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
module: stacki_host
short_description: Add or remove host to stacki front-end
description:
  - Use this module to add or remove hosts to a stacki front-end using API.
  - Information on stacki can be found at U(https://github.com/StackIQ/stacki).
extends_documentation_fragment:
  - community.general.attributes
attributes:
  check_mode:
    support: none
  diff_mode:
    support: none
options:
  name:
    description:
      - Name of the host to be added to Stacki.
    required: true
    type: str
  stacki_user:
    description:
      - Username for authenticating with Stacki API, but if not specified, the environment variable E(stacki_user) is used
        instead.
    required: true
    type: str
  stacki_password:
    description:
      - Password for authenticating with Stacki API, but if not specified, the environment variable E(stacki_password) is
        used instead.
    required: true
    type: str
  stacki_endpoint:
    description:
      - URL for the Stacki API Endpoint.
    required: true
    type: str
  prim_intf_mac:
    description:
      - MAC Address for the primary PXE boot network interface.
      - Currently not used by the module.
    type: str
  prim_intf_ip:
    description:
      - IP Address for the primary network interface.
      - Currently not used by the module.
    type: str
  prim_intf:
    description:
      - Name of the primary network interface.
      - Currently not used by the module.
    type: str
  force_install:
    description:
      - Set value to V(true) to force node into install state if it already exists in stacki.
    type: bool
    default: false
  state:
    description:
      - Set value to the desired state for the specified host.
    type: str
    choices: [absent, present]
    default: present
  appliance:
    description:
      - Appliance to be used in host creation.
      - Required if O(state=present) and host does not yet exist.
    type: str
    default: backend
  rack:
    description:
      - Rack to be used in host creation.
      - Required if O(state=present) and host does not yet exist.
    type: int
    default: 0
  rank:
    description:
      - Rank to be used in host creation.
      - In Stacki terminology, the rank is the position of the machine in a rack.
      - Required if O(state=present) and host does not yet exist.
    type: int
    default: 0
  network:
    description:
      - Network to be configured in the host.
      - Currently not used by the module.
    type: str
    default: private
author:
  - Hugh Ma (@bbyhuy) <Hugh.Ma@flextronics.com>
"""

EXAMPLES = r"""
- name: Add a host named test-1
  community.general.stacki_host:
    name: test-1
    stacki_user: usr
    stacki_password: pwd
    stacki_endpoint: url
    prim_intf_mac: mac_addr
    prim_intf_ip: x.x.x.x
    prim_intf: eth0

- name: Remove a host named test-1
  community.general.stacki_host:
    name: test-1
    stacki_user: usr
    stacki_password: pwd
    stacki_endpoint: url
    state: absent
"""


import json

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible.module_utils.six.moves.urllib.parse import urlencode
from ansible.module_utils.urls import fetch_url


class StackiHost(object):

    def __init__(self, module):
        self.module = module
        self.hostname = module.params['name']
        self.rack = module.params['rack']
        self.rank = module.params['rank']
        self.appliance = module.params['appliance']
        self.prim_intf = module.params['prim_intf']
        self.prim_intf_ip = module.params['prim_intf_ip']
        self.network = module.params['network']
        self.prim_intf_mac = module.params['prim_intf_mac']
        self.endpoint = module.params['stacki_endpoint']

        auth_creds = {'USERNAME': module.params['stacki_user'],
                      'PASSWORD': module.params['stacki_password']}

        # Get Initial CSRF
        cred_a = self.do_request(self.endpoint, method="GET")
        cookie_a = cred_a.headers.get('Set-Cookie').split(';')
        init_csrftoken = None
        for c in cookie_a:
            if "csrftoken" in c:
                init_csrftoken = c.replace("csrftoken=", "")
                init_csrftoken = init_csrftoken.rstrip("\r\n")
                break

        # Make Header Dictionary with initial CSRF
        header = {'csrftoken': init_csrftoken, 'X-CSRFToken': init_csrftoken,
                  'Content-type': 'application/x-www-form-urlencoded', 'Cookie': cred_a.headers.get('Set-Cookie')}

        # Endpoint to get final authentication header
        login_endpoint = self.endpoint + "/login"

        # Get Final CSRF and Session ID
        login_req = self.do_request(login_endpoint, headers=header, payload=urlencode(auth_creds), method='POST')

        cookie_f = login_req.headers.get('Set-Cookie').split(';')
        csrftoken = None
        for f in cookie_f:
            if "csrftoken" in f:
                csrftoken = f.replace("csrftoken=", "")
            if "sessionid" in f:
                sessionid = c.split("sessionid=", 1)[-1]
                sessionid = sessionid.rstrip("\r\n")

        self.header = {'csrftoken': csrftoken,
                       'X-CSRFToken': csrftoken,
                       'sessionid': sessionid,
                       'Content-type': 'application/json',
                       'Cookie': login_req.headers.get('Set-Cookie')}

    def do_request(self, url, payload=None, headers=None, method=None):
        res, info = fetch_url(self.module, url, data=payload, headers=headers, method=method)

        if info['status'] != 200:
            self.module.fail_json(changed=False, msg=info['msg'])

        return res

    def stack_check_host(self):
        res = self.do_request(self.endpoint, payload=json.dumps({"cmd": "list host"}), headers=self.header, method="POST")
        return self.hostname in res.read()

    def stack_sync(self):
        self.do_request(self.endpoint, payload=json.dumps({"cmd": "sync config"}), headers=self.header, method="POST")
        self.do_request(self.endpoint, payload=json.dumps({"cmd": "sync host config"}), headers=self.header, method="POST")

    def stack_force_install(self, result):
        data = {'cmd': "set host boot {0} action=install".format(self.hostname)}
        self.do_request(self.endpoint, payload=json.dumps(data), headers=self.header, method="POST")
        changed = True

        self.stack_sync()

        result['changed'] = changed
        result['stdout'] = "api call successful".rstrip("\r\n")

    def stack_add(self, result):
        data = dict()
        changed = False

        data['cmd'] = "add host {0} rack={1} rank={2} appliance={3}"\
            .format(self.hostname, self.rack, self.rank, self.appliance)
        self.do_request(self.endpoint, payload=json.dumps(data), headers=self.header, method="POST")

        self.stack_sync()

        result['changed'] = changed
        result['stdout'] = "api call successful".rstrip("\r\n")

    def stack_remove(self, result):
        data = dict()

        data['cmd'] = "remove host {0}"\
            .format(self.hostname)
        self.do_request(self.endpoint, payload=json.dumps(data), headers=self.header, method="POST")

        self.stack_sync()

        result['changed'] = True
        result['stdout'] = "api call successful".rstrip("\r\n")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['absent', 'present']),
            name=dict(type='str', required=True),
            rack=dict(type='int', default=0),
            rank=dict(type='int', default=0),
            appliance=dict(type='str', default='backend'),
            prim_intf=dict(type='str'),
            prim_intf_ip=dict(type='str'),
            network=dict(type='str', default='private'),
            prim_intf_mac=dict(type='str'),
            stacki_user=dict(type='str', required=True, fallback=(env_fallback, ['stacki_user'])),
            stacki_password=dict(type='str', required=True, fallback=(env_fallback, ['stacki_password']), no_log=True),
            stacki_endpoint=dict(type='str', required=True, fallback=(env_fallback, ['stacki_endpoint'])),
            force_install=dict(type='bool', default=False),
        ),
        supports_check_mode=False,
    )

    result = {'changed': False}
    missing_params = list()

    stacki = StackiHost(module)
    host_exists = stacki.stack_check_host()

    # If state is present, but host exists, need force_install flag to put host back into install state
    if module.params['state'] == 'present' and host_exists and module.params['force_install']:
        stacki.stack_force_install(result)
    # If state is present, but host exists, and force_install and false, do nothing
    elif module.params['state'] == 'present' and host_exists and not module.params['force_install']:
        result['stdout'] = "{0} already exists. Set 'force_install' to true to bootstrap"\
            .format(module.params['name'])
    # Otherwise, state is present, but host doesn't exists, require more params to add host
    elif module.params['state'] == 'present' and not host_exists:
        for param in ['appliance', 'rack', 'rank', 'prim_intf', 'prim_intf_ip', 'network', 'prim_intf_mac']:
            if not module.params[param]:
                missing_params.append(param)
        if len(missing_params) > 0:   # @FIXME replace with required_if
            module.fail_json(msg="missing required arguments: {0}".format(missing_params))

        stacki.stack_add(result)
    # If state is absent, and host exists, lets remove it.
    elif module.params['state'] == 'absent' and host_exists:
        stacki.stack_remove(result)

    module.exit_json(**result)


if __name__ == '__main__':
    main()
