#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2013, James Martin <jmartin@basho.com>, Drew Kerrigan <dkerrigan@basho.com>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r"""
module: riak
short_description: This module handles some common Riak operations
description:
  - This module can be used to join nodes to a cluster, check the status of the cluster.
author:
  - "James Martin (@jsmartin)"
  - "Drew Kerrigan (@drewkerrigan)"
extends_documentation_fragment:
  - community.general.attributes
attributes:
  check_mode:
    support: none
  diff_mode:
    support: none
options:
  command:
    description:
      - The command you would like to perform against the cluster.
    choices: ['ping', 'kv_test', 'join', 'plan', 'commit']
    type: str
  config_dir:
    description:
      - The path to the riak configuration directory.
    default: /etc/riak
    type: path
  http_conn:
    description:
      - The IP address and port that is listening for Riak HTTP queries.
    default: 127.0.0.1:8098
    type: str
  target_node:
    description:
      - The target node for certain operations (join, ping).
    default: riak@127.0.0.1
    type: str
  wait_for_handoffs:
    description:
      - Number of seconds to wait for handoffs to complete.
    type: int
    default: 0
  wait_for_ring:
    description:
      - Number of seconds to wait for all nodes to agree on the ring.
    type: int
    default: 0
  wait_for_service:
    description:
      - Waits for a riak service to come online before continuing.
    choices: ['kv']
    type: str
  validate_certs:
    description:
      - If V(false), SSL certificates are not validated. This should only be used on personally controlled sites using self-signed
        certificates.
    type: bool
    default: true
"""

EXAMPLES = r"""
- name: "Join's a Riak node to another node"
  community.general.riak:
    command: join
    target_node: riak@10.1.1.1

- name: Wait for handoffs to finish. Use with async and poll.
  community.general.riak:
    wait_for_handoffs: true

- name: Wait for riak_kv service to startup
  community.general.riak:
    wait_for_service: kv
"""

import json
import time

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url


def ring_check(module, riak_admin_bin):
    cmd = riak_admin_bin + ['ringready']
    rc, out, err = module.run_command(cmd)
    if rc == 0 and 'TRUE All nodes agree on the ring' in out:
        return True
    else:
        return False


def main():

    module = AnsibleModule(
        argument_spec=dict(
            command=dict(choices=['ping', 'kv_test', 'join', 'plan', 'commit']),
            config_dir=dict(default='/etc/riak', type='path'),
            http_conn=dict(default='127.0.0.1:8098'),
            target_node=dict(default='riak@127.0.0.1'),
            wait_for_handoffs=dict(default=0, type='int'),
            wait_for_ring=dict(default=0, type='int'),
            wait_for_service=dict(choices=['kv']),
            validate_certs=dict(default=True, type='bool'))
    )

    command = module.params.get('command')
    http_conn = module.params.get('http_conn')
    target_node = module.params.get('target_node')
    wait_for_handoffs = module.params.get('wait_for_handoffs')
    wait_for_ring = module.params.get('wait_for_ring')
    wait_for_service = module.params.get('wait_for_service')

    # make sure riak commands are on the path
    riak_bin = module.get_bin_path('riak')
    riak_admin_bin = module.get_bin_path('riak-admin')
    riak_admin_bin = [riak_admin_bin] if riak_admin_bin is not None else [riak_bin, 'admin']

    timeout = time.time() + 120
    while True:
        if time.time() > timeout:
            module.fail_json(msg='Timeout, could not fetch Riak stats.')
        (response, info) = fetch_url(module, 'http://%s/stats' % (http_conn), force=True, timeout=5)
        if info['status'] == 200:
            stats_raw = response.read()
            break
        time.sleep(5)

    # here we attempt to load those stats,
    try:
        stats = json.loads(stats_raw)
    except Exception:
        module.fail_json(msg='Could not parse Riak stats.')

    node_name = stats['nodename']
    nodes = stats['ring_members']
    ring_size = stats['ring_creation_size']
    rc, out, err = module.run_command([riak_bin, 'version'])
    version = out.strip()

    result = dict(node_name=node_name,
                  nodes=nodes,
                  ring_size=ring_size,
                  version=version)

    if command == 'ping':
        cmd = '%s ping %s' % (riak_bin, target_node)
        rc, out, err = module.run_command(cmd)
        if rc == 0:
            result['ping'] = out
        else:
            module.fail_json(msg=out)

    elif command == 'kv_test':
        cmd = riak_admin_bin + ['test']
        rc, out, err = module.run_command(cmd)
        if rc == 0:
            result['kv_test'] = out
        else:
            module.fail_json(msg=out)

    elif command == 'join':
        if nodes.count(node_name) == 1 and len(nodes) > 1:
            result['join'] = 'Node is already in cluster or staged to be in cluster.'
        else:
            cmd = riak_admin_bin + ['cluster', 'join', target_node]
            rc, out, err = module.run_command(cmd)
            if rc == 0:
                result['join'] = out
                result['changed'] = True
            else:
                module.fail_json(msg=out)

    elif command == 'plan':
        cmd = riak_admin_bin + ['cluster', 'plan']
        rc, out, err = module.run_command(cmd)
        if rc == 0:
            result['plan'] = out
            if 'Staged Changes' in out:
                result['changed'] = True
        else:
            module.fail_json(msg=out)

    elif command == 'commit':
        cmd = riak_admin_bin + ['cluster', 'commit']
        rc, out, err = module.run_command(cmd)
        if rc == 0:
            result['commit'] = out
            result['changed'] = True
        else:
            module.fail_json(msg=out)

# this could take a while, recommend to run in async mode
    if wait_for_handoffs:
        timeout = time.time() + wait_for_handoffs
        while True:
            cmd = riak_admin_bin + ['transfers']
            rc, out, err = module.run_command(cmd)
            if 'No transfers active' in out:
                result['handoffs'] = 'No transfers active.'
                break
            time.sleep(10)
            if time.time() > timeout:
                module.fail_json(msg='Timeout waiting for handoffs.')

    if wait_for_service:
        cmd = riak_admin_bin + ['wait_for_service', 'riak_%s' % wait_for_service, node_name]
        rc, out, err = module.run_command(cmd)
        result['service'] = out

    if wait_for_ring:
        timeout = time.time() + wait_for_ring
        while True:
            if ring_check(module, riak_admin_bin):
                break
            time.sleep(10)
        if time.time() > timeout:
            module.fail_json(msg='Timeout waiting for nodes to agree on ring.')

    result['ring_ready'] = ring_check(module, riak_admin_bin)

    module.exit_json(**result)


if __name__ == '__main__':
    main()
