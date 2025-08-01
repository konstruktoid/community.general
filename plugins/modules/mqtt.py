#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2013, 2014, Jan-Piet Mens <jpmens () gmail.com>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r"""
module: mqtt
short_description: Publish a message on an MQTT topic for the IoT
description:
  - Publish a message on an MQTT topic.
extends_documentation_fragment:
  - community.general.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: none
options:
  server:
    type: str
    description:
      - MQTT broker address/name.
    default: localhost
  port:
    type: int
    description:
      - MQTT broker port number.
    default: 1883
  username:
    type: str
    description:
      - Username to authenticate against the broker.
  password:
    type: str
    description:
      - Password for O(username) to authenticate against the broker.
  client_id:
    type: str
    description:
      - MQTT client identifier.
      - If not specified, it uses a value C(hostname + pid).
  topic:
    type: str
    description:
      - MQTT topic name.
    required: true
  payload:
    type: str
    description:
      - Payload. The special string V("None") may be used to send a NULL (that is, empty) payload which is useful to simply
        notify with the O(topic) or to clear previously retained messages.
    required: true
  qos:
    type: str
    description:
      - QoS (Quality of Service).
    default: "0"
    choices: ["0", "1", "2"]
  retain:
    description:
      - Setting this flag causes the broker to retain (in other words keep) the message so that applications that subsequently
        subscribe to the topic can received the last retained message immediately.
    type: bool
    default: false
  ca_cert:
    type: path
    description:
      - The path to the Certificate Authority certificate files that are to be treated as trusted by this client. If this
        is the only option given then the client operates in a similar manner to a web browser. That is to say it requires
        the broker to have a certificate signed by the Certificate Authorities in ca_certs and communicates using TLS v1,
        but does not attempt any form of authentication. This provides basic network encryption but may not be sufficient
        depending on how the broker is configured.
    aliases: [ca_certs]
  client_cert:
    type: path
    description:
      - The path pointing to the PEM encoded client certificate. If this is set it is used as client information for TLS based
        authentication. Support for this feature is broker dependent.
    aliases: [certfile]
  client_key:
    type: path
    description:
      - The path pointing to the PEM encoded client private key. If this is set it is used as client information for TLS based
        authentication. Support for this feature is broker dependent.
    aliases: [keyfile]
  tls_version:
    description:
      - Specifies the version of the SSL/TLS protocol to be used.
      - By default (if the python version supports it) the highest TLS version is detected. If unavailable, TLS v1 is used.
    type: str
    choices:
      - tlsv1.1
      - tlsv1.2
requirements: [mosquitto]
notes:
  - This module requires a connection to an MQTT broker such as Mosquitto U(http://mosquitto.org) and the I(Paho) C(mqtt)
    Python client (U(https://pypi.org/project/paho-mqtt/)).
author: "Jan-Piet Mens (@jpmens)"
"""

EXAMPLES = r"""
- name: Publish a message on an MQTT topic
  community.general.mqtt:
    topic: 'service/ansible/{{ ansible_hostname }}'
    payload: 'Hello at {{ ansible_date_time.iso8601 }}'
    qos: 0
    retain: false
    client_id: ans001
  delegate_to: localhost
"""

# ===========================================
# MQTT module support methods.
#

import os
import ssl
import traceback
import platform

from ansible_collections.community.general.plugins.module_utils.version import LooseVersion

HAS_PAHOMQTT = True
PAHOMQTT_IMP_ERR = None
try:
    import socket
    import paho.mqtt.publish as mqtt
except ImportError:
    PAHOMQTT_IMP_ERR = traceback.format_exc()
    HAS_PAHOMQTT = False

from ansible.module_utils.basic import AnsibleModule, missing_required_lib
from ansible.module_utils.common.text.converters import to_native


# ===========================================
# Main
#

def main():
    tls_map = {}

    try:
        tls_map['tlsv1.2'] = ssl.PROTOCOL_TLSv1_2
    except AttributeError:
        pass

    try:
        tls_map['tlsv1.1'] = ssl.PROTOCOL_TLSv1_1
    except AttributeError:
        pass

    module = AnsibleModule(
        argument_spec=dict(
            server=dict(default='localhost'),
            port=dict(default=1883, type='int'),
            topic=dict(required=True),
            payload=dict(required=True),
            client_id=dict(),
            qos=dict(default="0", choices=["0", "1", "2"]),
            retain=dict(default=False, type='bool'),
            username=dict(),
            password=dict(no_log=True),
            ca_cert=dict(type='path', aliases=['ca_certs']),
            client_cert=dict(type='path', aliases=['certfile']),
            client_key=dict(type='path', aliases=['keyfile']),
            tls_version=dict(choices=['tlsv1.1', 'tlsv1.2'])
        ),
        supports_check_mode=True
    )

    if not HAS_PAHOMQTT:
        module.fail_json(msg=missing_required_lib('paho-mqtt'), exception=PAHOMQTT_IMP_ERR)

    server = module.params.get("server", 'localhost')
    port = module.params.get("port", 1883)
    topic = module.params.get("topic")
    payload = module.params.get("payload")
    client_id = module.params.get("client_id", '')
    qos = int(module.params.get("qos", 0))
    retain = module.params.get("retain")
    username = module.params.get("username", None)
    password = module.params.get("password", None)
    ca_certs = module.params.get("ca_cert", None)
    certfile = module.params.get("client_cert", None)
    keyfile = module.params.get("client_key", None)
    tls_version = module.params.get("tls_version", None)

    if client_id is None:
        client_id = "%s_%s" % (socket.getfqdn(), os.getpid())

    if payload and payload == 'None':
        payload = None

    auth = None
    if username is not None:
        auth = {'username': username, 'password': password}

    tls = None
    if ca_certs is not None:
        if tls_version:
            tls_version = tls_map.get(tls_version, ssl.PROTOCOL_SSLv23)
        else:
            if LooseVersion(platform.python_version()) <= LooseVersion("3.5.2"):
                # Specifying `None` on later versions of python seems sufficient to
                # instruct python to autonegotiate the SSL/TLS connection. On versions
                # 3.5.2 and lower though we need to specify the version.
                #
                # Note that this is an alias for PROTOCOL_TLS, but PROTOCOL_TLS was
                # not available until 3.5.3.
                tls_version = ssl.PROTOCOL_SSLv23

        tls = {
            'ca_certs': ca_certs,
            'certfile': certfile,
            'keyfile': keyfile,
            'tls_version': tls_version,
        }

    try:
        mqtt.single(
            topic,
            payload,
            qos=qos,
            retain=retain,
            client_id=client_id,
            hostname=server,
            port=port,
            auth=auth,
            tls=tls
        )
    except Exception as e:
        module.fail_json(
            msg="unable to publish to MQTT broker %s" % to_native(e),
            exception=traceback.format_exc()
        )

    module.exit_json(changed=False, topic=topic)


if __name__ == '__main__':
    main()
