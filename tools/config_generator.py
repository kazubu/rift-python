#!/usr/bin/env python3

# pylint:disable=too-many-lines

import argparse
import os
import pprint
import random
import stat
import sys
import traceback

import cerberus
import pexpect
import yaml

sys.path.append("rift")

# pylint:disable=wrong-import-position
import constants
import table

META_CONFIG = None
ARGS = None

DEFAULT_NR_IPV4_LOOPBACKS = 1
DEFAULT_CHAOS_NR_LINK_EVENTS = 20
DEFAULT_CHAOS_NR_NODE_EVENTS = 5
DEFAULT_CHAOS_EVENT_INTERVAL = 3.0  # seconds
DEFAULT_CHAOS_MAX_CONCURRENT_EVENTS = 5

SEPARATOR = '-'
NETNS_PREFIX = 'netns' + SEPARATOR

DEFAULT = '\033[0m'
RED = '\u001b[31m'
GREEN = '\u001b[32m'

NODE_SCHEMA = {
    'type': 'dict',
    'schema': {
        'nr-ipv4-loopbacks': {'type': 'integer', 'min': 0, 'default': DEFAULT_NR_IPV4_LOOPBACKS}
    }
}

SCHEMA = {
    'nr-leaf-nodes-per-pod': {'required': True, 'type': 'integer', 'min': 1},
    'nr-pods': {'required': False, 'type': 'integer', 'min': 1, 'default': 1},
    'nr-spine-nodes-per-pod': {'required': True, 'type': 'integer', 'min': 1},
    'nr-superspine-nodes': {'required': False, 'type': 'integer', 'min': 1},
    'leafs': NODE_SCHEMA,
    'spines': NODE_SCHEMA,
    'chaos': {
        'type': 'dict',
        'schema': {
            'nr-link-events': {'type': 'integer', 'min': 0,
                               'default': DEFAULT_CHAOS_NR_LINK_EVENTS},
            'nr-node-events': {'type': 'integer', 'min': 0,
                               'default': DEFAULT_CHAOS_NR_NODE_EVENTS},
            'event-interval': {'type': 'float', 'min': 0.0,
                               'default': DEFAULT_CHAOS_EVENT_INTERVAL},
            'max-concurrent-events': {'type': 'integer', 'min': 1,
                                      'default': DEFAULT_CHAOS_MAX_CONCURRENT_EVENTS},
        }
    }
}

SOUTH = 1
NORTH = 2

LEAF_LEVEL = 0
SPINE_LEVEL = 1
SUPERSPINE_LEVEL = 2

GLOBAL_X_OFFSET = 10
GLOBAL_Y_OFFSET = 10
SUPERSPINE_TO_POD_Y_INTERVAL = 140
GROUP_X_INTERVAL = 30
GROUP_X_SPACER = 24
GROUP_Y_SPACER = 24
GROUP_X_TEXT_OFFSET = 8
GROUP_Y_TEXT_OFFSET = 16
GROUP_LINE_COLOR = "black"
GROUP_FILL_COLOR = "#F0F0F0"
NODE_X_SIZE = 100
NODE_Y_SIZE = 50
NODE_X_INTERVAL = 20
NODE_Y_INTERVAL = 100
NODE_LINE_COLOR = "black"
NODE_FILL_COLOR = "silver"
LINK_COLOR = "black"
LINK_WIDTH = "1"
LINK_HIGHLIGHT_WIDTH = "3"
INTF_COLOR = "black"
INTF_RADIUS = "3"
INTF_HIGHLIGHT_RADIUS = "5"
HIGHLIGHT_COLOR = "red"

LOOPBACKS_ADDRESS_BYTE = 88    # 88.level.index.lb
LIE_MCAST_ADDRESS_BYTE = 88    # 224.88.level.index  ff02::88:level:index

END_OF_SVG = """
<script type="text/javascript"><![CDATA[

function CreateNodeHighlightFunc(node) {
    return function() {
        rect = node.getElementsByClassName('node-rect')[0]
        rect.setAttribute("fill", "HIGHLIGHT_COLOR")
    }
}

function CreateNodeNormalFunc(node) {
    return function() {
        rect = node.getElementsByClassName('node-rect')[0]
        rect.setAttribute("fill", "NODE_FILL_COLOR")
    }
}

var nodes = document.getElementsByClassName('node');
for (var i = 0; i < nodes.length; i++) {
    node = nodes[i]
    node.addEventListener('mouseover', CreateNodeHighlightFunc(node));
    node.addEventListener('mouseout', CreateNodeNormalFunc(node));
}

function CreateLinkHighlightFunc(link) {
    return function() {
        line = link.getElementsByClassName('link-line')[0]
        line.setAttribute("style", "stroke:HIGHLIGHT_COLOR;stroke-width:LINK_HIGHLIGHT_WIDTH")
        for (var i = 0; i < 2; i++) {
            intf = link.getElementsByClassName('intf')[i]
            intf.setAttribute("style", "stroke:HIGHLIGHT_COLOR")
            intf.setAttribute("fill", "HIGHLIGHT_COLOR")
            intf.setAttribute("r", "INTF_HIGHLIGHT_RADIUS")
        }
    }
}

function CreateLinkNormalFunc(link) {
    return function() {
        line = link.getElementsByClassName('link-line')[0]
        line.setAttribute("style", "stroke:LINK_COLOR;stroke-width:LINK_WIDTH")
        for (var i = 0; i < 2; i++) {
            intf = link.getElementsByClassName('intf')[i]
            intf.setAttribute("style", "stroke:INTF_COLOR")
            intf.setAttribute("fill", "INTF_COLOR")
            intf.setAttribute("r", "INTF_RADIUS")
        }
    }
}

var links = document.getElementsByClassName('link');
for (var i = 0; i < links.length; i++) {
    link = links[i]
    link.addEventListener('mouseover', CreateLinkHighlightFunc(link));
    link.addEventListener('mouseout', CreateLinkNormalFunc(link));
}

]]></script>

</svg>
"""

END_OF_SVG = END_OF_SVG.replace("NODE_LINE_COLOR", NODE_LINE_COLOR)
END_OF_SVG = END_OF_SVG.replace("NODE_FILL_COLOR", NODE_FILL_COLOR)
END_OF_SVG = END_OF_SVG.replace("LINK_COLOR", LINK_COLOR)
END_OF_SVG = END_OF_SVG.replace("LINK_WIDTH", LINK_WIDTH)
END_OF_SVG = END_OF_SVG.replace("LINK_HIGHLIGHT_WIDTH", LINK_HIGHLIGHT_WIDTH)
END_OF_SVG = END_OF_SVG.replace("INTF_COLOR", INTF_COLOR)
END_OF_SVG = END_OF_SVG.replace("INTF_RADIUS", INTF_RADIUS)
END_OF_SVG = END_OF_SVG.replace("INTF_HIGHLIGHT_RADIUS", INTF_HIGHLIGHT_RADIUS)
END_OF_SVG = END_OF_SVG.replace("HIGHLIGHT_COLOR", HIGHLIGHT_COLOR)

class Group:

    def __init__(self, fabric, name, class_group_id, only_instance, y_pos, y_size):
        # class_group_id: group ID, uniquely identifies the group within the scope of the subclass
        #                 (pods have IDs 1,2,3... and planes have IDs 1, 2, 3...)
        self.fabric = fabric
        self.name = name
        self.class_group_id = class_group_id
        self.only_instance = only_instance
        self.given_y_pos = y_pos
        self.given_y_size = y_size
        self.x_center_shift = 0
        self.nodes = []
        self.nodes_by_level = {}
        # Links within the group. Spine to super-spine links are owned by the plane group, not the
        # pod group.
        self.links = []

    def create_node(self, name, level, top_of_fabric, group_level_node_id, y_pos):
        node = Node(self, name, level, top_of_fabric, group_level_node_id, y_pos)
        # TODO: Move adding of loopbacks to here
        self.nodes.append(node)
        if level not in self.nodes_by_level:
            self.nodes_by_level[level] = []
        self.nodes_by_level[level].append(node)
        return node

    def create_link(self, from_node, to_node):
        link = Link(from_node, to_node)
        self.links.append(link)
        return link

    def node_name(self, base_name, group_level_node_id):
        if self.only_instance:
            return base_name + "-" + str(group_level_node_id)
        else:
            return base_name + "-" + str(self.class_group_id) + "-" + str(group_level_node_id)

    def write_config_to_file(self, file, netns):
        for node in self.nodes:
            node.write_config_to_file(file, netns)

    def write_netns_configs_and_scripts(self):
        for node in self.nodes:
            node.write_netns_configs_and_scripts()

    def write_netns_start_scr_to_file_1(self, file):
        # Start phase 1: Create all namespaces and interfaces
        for link in self.links:
            link.write_netns_start_scr_to_file(file)
        for node in self.nodes:
            node.write_netns_start_scr_to_file_1(file)

    def write_netns_start_scr_to_file_2(self, file):
        # Start phase 2: Start all nodes
        # Allow interfaces to come up (particularly IPv6 interfaces take a bit of time)
        print("sleep 1", file=file)
        for node in self.nodes:
            node.write_netns_start_scr_to_file_2(file)

    def write_netns_stop_scr_to_file_1(self, file):
        # Stop phase 1: Delete all namespaces and interfaces
        for node in self.nodes:
            node.write_netns_stop_scr_to_file_1(file)

    def write_netns_stop_scr_to_file_2(self, file):
        # Stop phase 2: Stop all nodes
        for node in self.nodes:
            node.write_netns_stop_scr_to_file_2(file)

    def write_graphics_to_file(self, file):
        x_pos = self.x_pos()
        y_pos = self.y_pos()
        x_size = self.x_size()
        y_size = self.y_size()
        file.write('<rect '
                   'x="{}" '
                   'y="{}" '
                   'width="{}" '
                   'height="{}" '
                   'fill="{}" '
                   'style="stroke:{}" '
                   '></rect>'
                   .format(x_pos, y_pos, x_size, y_size, GROUP_FILL_COLOR, GROUP_LINE_COLOR))
        if not self.only_instance:
            x_pos += GROUP_X_TEXT_OFFSET
            y_pos += GROUP_Y_TEXT_OFFSET
            file.write('<text '
                       'x="{}" '
                       'y="{}" '
                       'style="font-family:monospace;stroke:{}">'
                       '{}'
                       '</text>\n'
                       .format(x_pos, y_pos, GROUP_LINE_COLOR, self.name))
        for node in self.nodes:
            node.write_graphics_to_file(file)
        for link in self.links:
            link.write_graphics_to_file(file)

    def x_pos(self):
        # X position of top-left corner of rectangle representing the group
        x_pos = GLOBAL_X_OFFSET
        x_pos += (self.class_group_id - 1) * (self.x_size() + GROUP_X_INTERVAL)
        x_pos += self.x_center_shift
        return x_pos

    def y_pos(self):
        return self.given_y_pos

    def nr_nodes_in_widest_level(self):
        result = 0
        for nodes_in_level_list in self.nodes_by_level.values():
            nr_nodes_in_level = len(nodes_in_level_list)
            result = max(result, nr_nodes_in_level)
        return result

    def x_size(self):
        width_nodes = self.nr_nodes_in_widest_level()
        width = width_nodes * NODE_X_SIZE
        width += (width_nodes - 1) * NODE_X_INTERVAL
        width += 2 * GROUP_X_SPACER   # TODO: Change to GROUP_X_SPACER
        return width

    def y_size(self):
        return self.given_y_size

    def first_node_x_pos(self, level):
        width_nodes = self.nr_nodes_in_widest_level()
        missing_nodes = width_nodes - len(self.nodes_by_level[level])
        padding_width = missing_nodes * (NODE_X_SIZE + NODE_X_INTERVAL) // 2
        return self.x_pos() + padding_width + GROUP_X_SPACER

    def nr_levels(self):
        return len(self.nodes_by_level)

class Pod(Group):

    def __init__(self, fabric, pod_name, global_pod_id, only_pod, y_pos):
        y_size = 2 * NODE_Y_SIZE + NODE_Y_INTERVAL + 2 * GROUP_Y_SPACER
        Group.__init__(self, fabric, pod_name, global_pod_id, only_pod, y_pos, y_size)
        self.leaf_nodes = []
        self.spine_nodes = []
        self.nr_leaf_nodes = META_CONFIG['nr-leaf-nodes-per-pod']
        # TODO: Make nr-ipv4-loopbacks a global knob
        if 'leafs' in META_CONFIG:
            self.leaf_nr_ipv4_loopbacks = META_CONFIG['leafs']['nr-ipv4-loopbacks']
        else:
            self.leaf_nr_ipv4_loopbacks = DEFAULT_NR_IPV4_LOOPBACKS
        self.nr_spine_nodes = META_CONFIG['nr-spine-nodes-per-pod']
        if 'spines' in META_CONFIG:
            self.spine_nr_ipv4_loopbacks = META_CONFIG['spines']['nr-ipv4-loopbacks']
        else:
            self.spine_nr_ipv4_loopbacks = DEFAULT_NR_IPV4_LOOPBACKS
        self.nr_superspine_nodes = 0
        self.create_leaf_nodes()
        self.create_spine_nodes()
        self.create_leaf_spine_links()

    def create_leaf_nodes(self):
        y_pos = self.y_pos() + GROUP_Y_SPACER + NODE_Y_SIZE + NODE_Y_INTERVAL
        for index in range(0, self.nr_leaf_nodes):
            group_level_node_id = index + 1
            node_name = self.node_name("leaf", group_level_node_id)
            node = self.create_node(node_name, LEAF_LEVEL, False, group_level_node_id, y_pos)
            node.add_ipv4_loopbacks(self.leaf_nr_ipv4_loopbacks)
            self.leaf_nodes.append(node)

    def create_spine_nodes(self):
        # If this is the only PoD, then the spines are the top-of-fabric. If there are multiple PoDs
        # then there are superspines which are the top-of-fabric.
        top_of_fabric = self.only_instance
        y_pos = self.y_pos() + GROUP_Y_SPACER
        for index in range(0, self.nr_spine_nodes):
            group_level_node_id = index + 1
            node_name = self.node_name("spine", group_level_node_id)
            node = self.create_node(node_name, SPINE_LEVEL, top_of_fabric, group_level_node_id,
                                    y_pos)
            node.add_ipv4_loopbacks(self.spine_nr_ipv4_loopbacks)
            self.spine_nodes.append(node)

    def create_leaf_spine_links(self):
        for leaf_node in self.leaf_nodes:
            for spine_node in self.spine_nodes:
                _link = self.create_link(leaf_node, spine_node)

class Plane(Group):

    def __init__(self, fabric, plane_name, global_plane_id, only_plane, y_pos):
        y_size = NODE_Y_SIZE + 2 * GROUP_Y_SPACER
        Group.__init__(self, fabric, plane_name, global_plane_id, only_plane, y_pos, y_size)
        self.superspine_nodes = []
        self.superspine_spine_links = []
        self.nr_leaf_nodes = 0
        self.nr_spine_nodes = 0
        self.nr_superspine_nodes = META_CONFIG['nr-superspine-nodes']
        # TODO: Make nr-ipv4-loopbacks a global knob
        self.superspine_nr_ipv4_loopbacks = 1
        self.create_superspine_nodes()

    def create_superspine_nodes(self):
        top_of_fabric = True
        y_pos = self.y_pos() + GROUP_Y_SPACER
        for index in range(0, self.nr_superspine_nodes):
            group_level_node_id = index + 1
            node_name = self.node_name("super", group_level_node_id)
            node = self.create_node(node_name, SUPERSPINE_LEVEL, top_of_fabric, group_level_node_id,
                                    y_pos)
            node.add_ipv4_loopbacks(self.superspine_nr_ipv4_loopbacks)
            self.superspine_nodes.append(node)

class Node:

    next_level_node_id = {}

    def __init__(self, group, name, level, top_of_fabric, group_level_node_id, y_pos):
        # For now, we support max 3 levels, and they must be level 0, 1, and 2
        assert level <= 2
        self.group = group
        self.name = name
        self.allocate_node_ids(level)
        self.ns_name = NETNS_PREFIX + str(self.global_node_id)
        self.level = level
        self.top_of_fabric = top_of_fabric
        self.group_level_node_id = group_level_node_id
        self.given_y_pos = y_pos
        self.rx_lie_ipv4_mcast_addr = self.generate_ipv4_address_str(
            224, LIE_MCAST_ADDRESS_BYTE, self.level, self.level_node_id)
        self.rx_lie_ipv6_mcast_addr = self.generate_ipv6_address_str(
            "ff02", LIE_MCAST_ADDRESS_BYTE, self.level, self.level_node_id)
        self.interfaces = []
        self.ipv4_prefixes = []
        self.lo_addresses = []
        self.config_file_name = None
        self.port_file = "/tmp/rift-python-telnet-port-" + self.name
        self.telnet_session = None

    def allocate_node_ids(self, level):
        # level_node_id: a node ID unique only within the level (each level has IDs 1, 2, 3...)
        # global_node_id: a node ID which is globally unque (1001, 1002, 1003... for leaf nodes,
        #                 101, 102, 103... for spine nodes, and 1, 2, 3... for super-spine nodes)
        if level in Node.next_level_node_id:
            self.level_node_id = Node.next_level_node_id[level]
            Node.next_level_node_id[level] += 1
        else:
            self.level_node_id = 1
            Node.next_level_node_id[level] = 2
        # We use the index as a byte in IP addresses, so we support max 254 nodes per level
        assert self.level_node_id <= 254
        if level == LEAF_LEVEL:
            base_global_node_id_for_level = 1000
        elif level == SPINE_LEVEL:
            base_global_node_id_for_level = 100
        elif level == SUPERSPINE_LEVEL:
            base_global_node_id_for_level = 0
        else:
            assert False
        self.global_node_id = base_global_node_id_for_level + self.level_node_id

    def generate_ipv4_address_str(self, byte1, byte2, byte3, byte4):
        assert 0 <= byte1 <= 255
        assert 0 <= byte2 <= 255
        assert 0 <= byte3 <= 255
        assert 1 <= byte4 <= 254
        ip_address_str = "{}.{}.{}.{}".format(byte1, byte2, byte3, byte4)
        return ip_address_str

    def generate_ipv6_address_str(self, prefix, byte1, byte2, byte3):
        assert 0 <= byte1 <= 255
        assert 0 <= byte2 <= 255
        assert 1 <= byte3 <= 254
        return "{}::{}:{}:{}".format(prefix, byte1, byte2, byte3)

    def add_ipv4_loopbacks(self, count):
        for node_loopback_id in range(1, count+1):
            address = self.generate_ipv4_address_str(
                LOOPBACKS_ADDRESS_BYTE, self.level, self.level_node_id, node_loopback_id)
            mask = "32"
            metric = "1"
            prefix = (address, mask, metric)
            self.ipv4_prefixes.append(prefix)
            self.lo_addresses.append(address)

    def create_interface(self):
        node_intf_id = len(self.interfaces) + 1
        interface = Interface(self, node_intf_id)
        self.interfaces.append(interface)
        return interface

    def interface_dir_index(self, interface):
        # Of all the interfaces on the node in the same direction as the given interface, what
        # is the index of the interface? Is it the 0th, the 1st, the 2nd, etc. interface in that
        # particular direction? Note that the index is zero-based.
        index = 0
        for check_interface in self.interfaces:
            if check_interface == interface:
                return index
            if check_interface.direction == interface.direction:
                index += 1
        return None

    def interface_dir_count(self, direction):
        # How many interfaces in the given direction does this node have?
        count = 0
        for interface in self.interfaces:
            if interface.direction == direction:
                count += 1
        return count

    def write_config_to_file(self, file, netns):
        if netns:
            print("shards:", file=file)
            print("  - id: 0", file=file)
            print("    nodes:", file=file)
        print("      - name: " + self.name, file=file)
        print("        level: " + str(self.level), file=file)
        print("        systemid: " + str(self.global_node_id), file=file)
        if not netns:
            print("        rx_lie_mcast_address: " + self.rx_lie_ipv4_mcast_addr, file=file)
            print("        rx_lie_v6_mcast_address: " + self.rx_lie_ipv6_mcast_addr, file=file)
        print("        interfaces:", file=file)
        for intf in self.interfaces:
            description = "{} -> {}".format(intf.fq_name(), intf.peer_intf.fq_name())
            if netns:
                print("          - name: " + intf.veth_name(), file=file)
            else:
                print("          - name: " + intf.name(), file=file)
            print("            # " + description, file=file)
            if not netns:
                print("            rx_lie_port: " + str(intf.rx_lie_port), file=file)
                print("            tx_lie_port: " + str(intf.tx_lie_port), file=file)
                print("            rx_tie_port: " + str(intf.rx_flood_port), file=file)
        print("        v4prefixes:", file=file)
        for prefix in self.ipv4_prefixes:
            (address, mask, metric) = prefix
            print("          - address: " + address, file=file)
            print("            mask: " + mask, file=file)
            print("            metric: " + metric, file=file)

    def write_netns_configs_and_scripts(self):
        self.write_netns_config()
        self.write_netns_connect_script()

    def write_netns_config(self):
        dir_name = getattr(ARGS, 'output-file-or-dir')
        file_name = dir_name + '/' + self.name + ".yaml"
        self.config_file_name = os.path.realpath(file_name)
        try:
            with open(file_name, 'w') as file:
                self.write_config_to_file(file, netns=True)
        except IOError:
            fatal_error('Could not open output node configuration file "{}"'.format(file_name))

    def write_netns_connect_script(self):
        dir_name = getattr(ARGS, 'output-file-or-dir')
        file_name = "{}/connect-{}.sh".format(dir_name, self.name)
        try:
            with open(file_name, 'w') as file:
                print("ip netns exec {} telnet localhost $(cat {})"
                      .format(self.ns_name, self.port_file), file=file)
        except IOError:
            fatal_error('Could not open start script file "{}"'.format(file_name))
        try:
            existing_stat = os.stat(file_name)
            os.chmod(file_name, existing_stat.st_mode | stat.S_IXUSR)
        except IOError:
            fatal_error('Could name make "{}" executable'.format(file_name))

    def write_netns_start_scr_to_file_1(self, file):
        progress = ("Create network namespace {} for node {}".format(self.ns_name, self.name))
        print("echo '{0}'\n"
              "ip netns add {1}\n"
              "if [[ $(ip netns exec {1} sysctl -n net.ipv4.conf.all.forwarding) == 0 ]]; then\n"
              "  ip netns exec {1} sysctl -q -w net.ipv4.conf.all.forwarding=1\n"
              "fi\n"
              "if [[ $(ip netns exec {1} sysctl -n net.ipv6.conf.all.forwarding) == 0 ]]; then\n"
              "  ip netns exec {1} sysctl -q -w net.ipv6.conf.all.forwarding=1\n"
              "fi\n"
              "ip netns exec {1} ip link set dev lo up"
              .format(progress, self.ns_name),
              file=file)
        for addr in self.lo_addresses:
            print("ip netns exec {} ip addr add {} dev lo".format(self.ns_name, addr), file=file)
        for intf in self.interfaces:
            veth = intf.veth_name()
            addr = intf.addr
            print("ip link set {} netns {}".format(veth, self.ns_name), file=file)
            print("ip netns exec {} ip link set dev {} up".format(self.ns_name, veth), file=file)
            print("ip netns exec {} ip addr add {} dev {}".format(self.ns_name, addr, veth),
                  file=file)

    def write_netns_start_scr_to_file_2(self, file, progress_msg=None):
        if not progress_msg:
            progress_msg = "Start RIFT-Python engine for node {}"
        progress_msg = progress_msg.format(self.name)
        print('echo "{}"'.format(progress_msg), file=file)
        ns_name = NETNS_PREFIX + str(self.global_node_id)
        port_file = "/tmp/rift-python-telnet-port-" + self.name
        print("ip netns exec {} env/bin/python3 rift "
              "--ipv4-multicast-loopback-disable "
              "--ipv6-multicast-loopback-disable "
              "--telnet-port-file {} {} >/dev/null 2>&1 &"
              .format(ns_name, port_file, self.config_file_name), file=file)

    def write_netns_stop_scr_to_file_1(self, file):
        progress = ("Stop RIFT-Python engine for node {}".format(self.name))
        print('echo "{}"'.format(progress), file=file)
        # We use a big hammer: we kill -9 all processes in the the namespace
        self.write_kill_rift_to_file(file)
        # Also clean up the port file
        port_file = "/tmp/rift-python-telnet-port-" + self.name
        print("rm -f {}".format(port_file), file=file)
        # Delete all interfaces for the node
        ns_name = NETNS_PREFIX + str(self.global_node_id)
        for intf in self.interfaces:
            veth = intf.veth_name()
            progress = ("Delete interface {} for node {}".format(veth, self.name))
            print('echo "{}"'.format(progress), file=file)
            print("ip netns exec {} ip link del dev {} >/dev/null 2>&1".format(ns_name, veth),
                  file=file)

    def write_kill_rift_to_file(self, file):
        ns_name = NETNS_PREFIX + str(self.global_node_id)
        print("RIFT_PIDS=$(ip netns pids {})".format(ns_name), file=file)
        print("kill -9 $RIFT_PIDS >/dev/null 2>&1", file=file)
        print("wait $RIFT_PIDS >/dev/null 2>&1", file=file)

    def write_netns_stop_scr_to_file_2(self, file):
        ns_name = NETNS_PREFIX + str(self.global_node_id)
        progress = ("Delete network namespace {} for node {}".format(ns_name, self.name))
        print('echo "{}"'.format(progress), file=file)
        print("ip netns del {} >/dev/null 2>&1".format(ns_name), file=file)

    def write_graphics_to_file(self, file):
        x_pos = self.x_pos()
        y_pos = self.y_pos()
        file.write('<g class="node">\n')
        file.write('<rect '
                   'x="{}" '
                   'y="{}" '
                   'width="{}" '
                   'height="{}" '
                   'fill="{}" '
                   'style="stroke:{}" '
                   'class="node-rect" '
                   '></rect>'
                   .format(x_pos, y_pos, NODE_X_SIZE, NODE_Y_SIZE, NODE_FILL_COLOR,
                           NODE_LINE_COLOR))
        y_pos += NODE_Y_SIZE // 2
        x_pos += NODE_X_SIZE // 10
        file.write('<text '
                   'x="{}" '
                   'y="{}" '
                   'style="font-family:monospace; dominant-baseline:central; stroke:{}">'
                   '{}'
                   '</text>\n'
                   .format(x_pos, y_pos, NODE_LINE_COLOR, self.name))
        file.write('</g>\n')

    def add_allocations_to_table(self, tab):
        interface_names = []
        neighbor_nodes = []
        interface_addresses = []
        neighbor_addresses = []
        for intf in self.interfaces:
            interface_names.append(intf.name())
            interface_addresses.append(intf.addr)
            if intf.peer_intf is None:
                neighbor_nodes.append("-")
                neighbor_addresses.append("-")
            else:
                neighbor_nodes.append(intf.peer_intf.node.name)
                neighbor_addresses.append(intf.peer_intf.addr)

        tab.add_row([
            self.name,
            self.lo_addresses,
            self.global_node_id,
            self.ns_name,
            interface_names,
            interface_addresses,
            neighbor_nodes,
            neighbor_addresses
        ])

    def check(self):
        print("**** Check node {}".format(self.name))
        if not self.connect_telnet():
            return False
        self.check_engine()
        self.check_interfaces_3way()
        if not self.top_of_fabric:
            self.check_rib_north_default_route()
        self.check_rib_south_specific_routes()
        self.check_rib_fib_consistency()
        self.check_fib_kernel_consistency()
        return True

    def check_engine(self):
        step = "RIFT engine is responsive"
        self.telnet_session.send_line("show engine")
        if not self.telnet_session.table_expect("Stand-alone | True"):
            error = 'Show engine reported unexpected result for stand-alone'
            self.report_check_result(step, False, error)
            return
        self.report_check_result(step)

    def check_interfaces_3way(self):
        step = "Adjacencies are 3-way"
        okay = True
        parsed_intfs = self.telnet_session.parse_show_output("show interfaces")
        for parsed_intf in parsed_intfs[0]['rows'][1:]:
            intf_name = parsed_intf[0][0]
            intf_state = parsed_intf[3][0]
            if intf_state != "THREE_WAY":
                error = "Interface {} in state {}".format(intf_name, intf_state)
                self.report_check_result(step, False, error)
                okay = False
        self.report_check_result(step, okay)

    def check_rib_north_default_route(self):
        step = "North-bound default routes are present"
        okay = True
        direction = constants.DIR_NORTH
        ipv4_nexthops = self.gather_nexthops(direction, True)
        parsed_rib_ipv4_routes = self.telnet_session.parse_show_output("show routes family ipv4")
        okay = self.check_route_in_rib("0.0.0.0/0", direction, ipv4_nexthops,
                                       parsed_rib_ipv4_routes) and okay
        ipv6_nexthops = self.gather_nexthops(direction, False)
        parsed_rib_ipv6_routes = self.telnet_session.parse_show_output("show routes family ipv6")
        okay = self.check_route_in_rib("::/0", direction, ipv6_nexthops,
                                       parsed_rib_ipv6_routes) and okay
        self.report_check_result(step, okay)

    def check_rib_south_specific_routes(self):
        # TODO: Once we add support for IPv6 loopbacks, also check those
        step = "South-bound specific routes are present"
        okay = True
        direction = constants.DIR_SOUTH
        ipv4_lo_addresses = self.gather_southern_loopbacks()
        parsed_rib_ipv4_routes = self.telnet_session.parse_show_output("show routes family ipv4")
        for ipv4_lo_address in ipv4_lo_addresses:
            ipv4_nexthops = self.southern_loopback_nexthops(ipv4_lo_address, True)
            ipv4_prefix = ipv4_lo_address + "/32"
            okay = self.check_route_in_rib(ipv4_prefix, direction, ipv4_nexthops,
                                           parsed_rib_ipv4_routes) and okay
        self.report_check_result(step, okay)

    def gather_southern_loopbacks(self, include_own_loopbacks=False):
        # Recursively walk all nodes south of this node and collect their loopback prefixes.
        if include_own_loopbacks:
            ipv4_loopback_prefixes = self.lo_addresses
        else:
            ipv4_loopback_prefixes = []
        for intf in self.interfaces:
            if self.interface_direction(intf) == constants.DIR_SOUTH:
                south_node = intf.peer_intf.node
                ipv4_loopback_prefixes += south_node.lo_addresses
                ipv4_loopback_prefixes += south_node.gather_southern_loopbacks()
        ipv4_loopback_prefixes = list(set(ipv4_loopback_prefixes))   # Remove duplicates
        return ipv4_loopback_prefixes

    def southern_loopback_nexthops(self, loopback_address, include_ipv4_address):
        nexthops = []
        for intf in self.interfaces:
            if self.interface_direction(intf) == constants.DIR_SOUTH:
                south_node = intf.peer_intf.node
                intf_southern_loopbacks = south_node.gather_southern_loopbacks(True)
                if loopback_address in intf_southern_loopbacks:
                    nexthops.append(self.interface_nexthop(intf, include_ipv4_address))
        return nexthops

    def interface_direction(self, interface):
        if self.level > interface.peer_intf.node.level:
            return constants.DIR_SOUTH
        elif self.level < interface.peer_intf.node.level:
            return constants.DIR_NORTH
        else:
            return constants.DIR_EAST_WEST

    def gather_nexthops(self, direction, include_ipv4_address):
        nexthops = []
        for intf in self.interfaces:
            if self.interface_direction(intf) == direction:
                nexthops.append(self.interface_nexthop(intf, include_ipv4_address))
        nexthops = list(set(nexthops))   # Remove duplicates
        return nexthops

    def interface_nexthop(self, intf, include_ipv4_address):
        nexthop_intf = intf.veth_name()
        if include_ipv4_address:
            nexthop_ipv4_address = intf.peer_intf.addr.split('/')[0] # Strip off /prefix-len
            nexthop = "{} {}".format(nexthop_intf, nexthop_ipv4_address)
        else:
            nexthop = "{}".format(nexthop_intf)
        return nexthop

    def check_route_in_rib(self, prefix, direction, nexthops, parsed_rib_routes):
        if direction == constants.DIR_SOUTH:
            owner = "South SPF"
        else:
            assert direction == constants.DIR_NORTH
            owner = "North SPF"
        substep = "Route prefix {} owner {} nexthops {} in RIB".format(prefix, owner, nexthops)
        sorted_nexthops = sorted(nexthops)
        for rib_route in parsed_rib_routes[0]['rows'][1:]:
            rib_prefix = rib_route[0][0]
            rib_owner = rib_route[1][0]
            if prefix == rib_prefix and owner == rib_owner:
                rib_nexthops = rib_route[2]
                if ':' in prefix:
                    # For IPv6 routes, we only check the nexthop interface and not the link-local
                    # nexthop address
                    rib_nexthops = [nh.split(' ')[0] for nh in rib_nexthops]
                sorted_rib_nexthops = sorted(rib_nexthops)
                if sorted_nexthops == sorted_rib_nexthops:
                    return True
                else:
                    error = ("Nexthops mismatch; expected {} but RIB has {}"
                             .format(sorted_nexthops, sorted_rib_nexthops))
                    self.report_check_result(substep, False, error)
                    return False
        self.report_check_result(substep, False, "Route missing")
        return False

    def check_rib_fib_consistency(self):
        # None of our tests involve a scenario where we have both a North-SPF route and also a
        # South-SPF route for the same prefix. So, we can simply check that the forwarding table
        # (FIB) is identical to the route table (RIB).
        step = "RIB and FIB are consistent"
        try:
            parsed_rib = self.telnet_session.parse_show_output("show routes")
            parsed_fib = self.telnet_session.parse_show_output("show forwarding")
            if parsed_rib == parsed_fib:
                self.report_check_result(step)
            else:
                self.report_check_result(step, False, "FIB is different than RIB")
        except RuntimeError as err:
            self.report_check_result(step, False, str(err))

    def check_fib_kernel_consistency(self):
        step = "FIB and Kernel are consistent"
        parsed_fib_routes = self.telnet_session.parse_show_output("show forwarding")
        parsed_kernel_routes = \
            self.telnet_session.parse_show_output("show kernel routes table main")
        all_ok = True
        for fib_fam in parsed_fib_routes:
            for fib_route in fib_fam['rows'][1:]:
                fib_prefix = fib_route[0][0]
                fib_nexthops = fib_route[2]
                if not self.check_route_in_kernel(step, fib_prefix, fib_nexthops,
                                                  parsed_kernel_routes):
                    all_ok = False
        if all_ok:
            self.report_check_result(step)

    def check_route_in_kernel(self, step, prefix, nexthops, parsed_kernel_routes):
        # In the FIB, and ECMP route is one row with multiple nexthops. In the kernel, an ECMP route
        # may be one row with multuple nexthops or may be multiple rows with the same prefix (the
        # former appears to be the case for IPv4 and the latter appears to be the case for IPv6)
        partial_match = False
        remaining_fib_nexthops = nexthops
        for kernel_route in parsed_kernel_routes[0]['rows'][1:]:
            kernel_prefix = kernel_route[2][0]
            kernel_nexthop_intfs = kernel_route[5]
            kernel_nexthop_addrs = kernel_route[6]
            kernel_nexthops = [intf + ' ' + addr for (intf, addr) in zip(kernel_nexthop_intfs,
                                                                         kernel_nexthop_addrs)]
            if kernel_prefix == prefix:
                sorted_kernel_nexthops = sorted(kernel_nexthops)
                sorted_fib_nexthops = sorted(nexthops)
                if len(kernel_nexthops) == 1:
                    # If the kernel has a single nexthop, look for a partial match
                    kernel_nexthop = kernel_nexthops[0]
                    if kernel_nexthop in remaining_fib_nexthops:
                        remaining_fib_nexthops.remove(kernel_nexthop)
                        if remaining_fib_nexthops == []:
                            return True
                        else:
                            partial_match = True
                    else:
                        err = ("Route {} has nexthop {} in kernel but not in FIB"
                               .format(prefix, kernel_nexthop))
                        self.report_check_result(step, False, err)
                        return False
                elif sorted_kernel_nexthops == sorted_fib_nexthops:
                    # If the kernel has a multiple nexthops, look for an exact match
                    return True
                else:
                    err = ("Route {} has nexthops {} in kernel but {} in FIB"
                           .format(prefix, kernel_nexthops, nexthops))
                    self.report_check_result(step, False, err)
                    return False
        if partial_match:
            err = ("Route {} in FIB has extra nexthops {} which are missing in kernel"
                   .format(prefix, remaining_fib_nexthops))
        else:
            err = "Route {} is in FIB but not in kernel".format(prefix)
        self.report_check_result(step, False, err)
        return False

    def report_check_result(self, step, okay=True, error=None):
        if okay:
            print(GREEN + "OK" + DEFAULT + "    {}".format(step))
        elif error:
            print(RED + "FAIL" + DEFAULT + "  {}: {}".format(step, error))
        else:
            print(RED + "FAIL" + DEFAULT + "  {}".format(step))

    def connect_telnet(self):
        step = "Can Telnet to RIFT process"
        try:
            with open(self.port_file, 'r') as file:
                telnet_port = int(file.read())
        except (IOError, OSError):
            error = 'Could not open telnet port file "{}"'.format(self.port_file)
            self.report_check_result(step, False, error)
            return False
        self.telnet_session = TelnetSession(self.ns_name, telnet_port)
        if not self.telnet_session.connected:
            error = 'Could not Telnet to {}:{}'.format(self.ns_name, telnet_port)
            self.report_check_result(step, False, error)
            return False
        if not self.telnet_session.wait_prompt():
            error = 'Did not get prompt on Telnet session'
            self.report_check_result(step, False, error)
            return False
        self.report_check_result(step)
        return True

    def x_pos(self):
        # X position of top-left corner of rectangle representing the node
        x_delta = (self.group_level_node_id - 1) * (NODE_X_SIZE + NODE_X_INTERVAL)
        return self.group.first_node_x_pos(self.level) + x_delta

    def y_pos(self):
        # Y position of top-left corner of rectangle representing the node
        return self.given_y_pos

class Interface:

    next_global_intf_id = 1

    def __init__(self, node, node_intf_id):
        self.node = node
        self.global_intf_id = Interface.next_global_intf_id       # Globally unique ID for interface
        Interface.next_global_intf_id += 1
        self.node_intf_id = node_intf_id   # ID for interface, only unique within scope of interface
        self.peer_intf = None
        self.direction = None
        self.rx_lie_port = None
        self.tx_lie_port = None
        self.rx_flood_port = None
        self.addr = None

    def set_peer_intf(self, peer_intf):
        self.peer_intf = peer_intf
        peer_node = peer_intf.node
        if peer_node.level < self.node.level:
            self.direction = SOUTH
        else:
            self.direction = NORTH
        self.rx_lie_port = 20000 + self.global_intf_id
        self.tx_lie_port = 20000 + self.peer_intf.global_intf_id
        self.rx_flood_port = 10000 + self.global_intf_id
        lower = min(self.global_intf_id, self.peer_intf.global_intf_id)
        upper = max(self.global_intf_id, self.peer_intf.global_intf_id)
        self.addr = "99.{}.{}.{}/24".format(lower, upper, self.global_intf_id)

    def node_intf_id_letter(self):
        return chr(ord('a') + self.node_intf_id - 1)

    def name(self):
        return "if" + SEPARATOR + str(self.node.global_node_id) + self.node_intf_id_letter()

    def fq_name(self):
        return self.node.name + ":" + self.name()

    def veth_name(self):
        return ("veth" + SEPARATOR +
                str(self.node.global_node_id) + self.node_intf_id_letter() + SEPARATOR +
                str(self.peer_intf.node.global_node_id) + self.peer_intf.node_intf_id_letter())

    def write_graphics_to_file(self, file):
        x_pos = self.x_pos()
        y_pos = self.y_pos()
        file.write('<circle '
                   'cx="{}" '
                   'cy="{}" '
                   'r="{}" '
                   'style="stroke:{};fill:{}" '
                   'class="intf">'
                   '</circle>\n'
                   .format(x_pos, y_pos, INTF_RADIUS, INTF_COLOR, INTF_COLOR))

    def x_pos(self):
        # X position of center of circle representing interface
        node_intf_dir_count = self.node.interface_dir_count(self.direction)
        intf_dir_index = self.node.interface_dir_index(self)
        intf_x_dist = NODE_X_SIZE / (node_intf_dir_count + 1)
        return self.node.x_pos() + intf_x_dist * (intf_dir_index + 1)

    def y_pos(self):
        # Y position of center of circle representing interface
        if self.direction == NORTH:
            return self.node.y_pos()
        else:
            return self.node.y_pos() + NODE_Y_SIZE

class Link:

    def __init__(self, node1, node2):
        self.intf1 = node1.create_interface()
        self.intf2 = node2.create_interface()
        self.intf1.set_peer_intf(self.intf2)
        self.intf2.set_peer_intf(self.intf1)

    def description(self):
        return self.intf1.name() + "-" + self.intf2.name()

    def write_netns_start_scr_to_file(self, file):
        veth1_name = self.intf1.veth_name()
        veth2_name = self.intf2.veth_name()
        progress = ("Create veth pair {} and {} for link from {} to {}"
                    .format(veth1_name, veth2_name, self.intf1.fq_name(), self.intf2.fq_name()))
        print('echo "{}"'.format(progress), file=file)
        print("ip link add dev {} type veth peer name {}".format(veth1_name, veth2_name), file=file)

    def write_graphics_to_file(self, file):
        x_pos1 = self.intf1.x_pos()
        y_pos1 = self.intf1.y_pos()
        x_pos2 = self.intf2.x_pos()
        y_pos2 = self.intf2.y_pos()
        file.write('<g class="link">\n')
        file.write('<line '
                   'x1="{}" '
                   'y1="{}" '
                   'x2="{}" '
                   'y2="{}" '
                   'style="stroke:{};" '
                   'class="link-line">'
                   '</line>\n'
                   .format(x_pos1, y_pos1, x_pos2, y_pos2, LINK_COLOR))
        self.intf1.write_graphics_to_file(file)
        self.intf2.write_graphics_to_file(file)
        file.write('</g>\n')

class LinkDownEvent:

    def __init__(self, link):
        self.link = link

    def write_break_script(self, file):
        description = (
            RED + "Break  " + DEFAULT + "Link  " +
            "{} (bi-directional failure)".format(self.link.description()))
        print("#" * 80, file=file)
        print("# {}".format(description), file=file)
        print("#" * 80, file=file)
        print(file=file)
        print("echo '{}'".format(description), file=file)
        # Transmit loss 100% on one side
        script = ("ip netns exec {} tc qdisc add dev {} root netem loss 100%"
                  .format(self.link.intf1.node.ns_name, self.link.intf1.veth_name()))
        print("{}".format(script), file=file)
        # Transmit loss 100% on the other side
        script = ("ip netns exec {} tc qdisc add dev {} root netem loss 100%"
                  .format(self.link.intf2.node.ns_name, self.link.intf2.veth_name()))
        print("{}".format(script), file=file)
        print(file=file)

    def write_fix_script(self, file):
        description = GREEN + "Fix    " + DEFAULT + "Link  " + self.link.description()
        print("#" * 80, file=file)
        print("# {}".format(description), file=file)
        print("#" * 80, file=file)
        print(file=file)
        print("echo '{}'".format(description), file=file)
        # Undo transmit loss 100% on one side
        script = ("ip netns exec {} tc qdisc del dev {} root netem"
                  .format(self.link.intf1.node.ns_name, self.link.intf1.veth_name()))
        print("{}".format(script), file=file)
        # Unto transmit loss 100% on the other side
        script = ("ip netns exec {} tc qdisc del dev {} root netem"
                  .format(self.link.intf2.node.ns_name, self.link.intf2.veth_name()))
        print("{}".format(script), file=file)
        print(file=file)

class NodeDownEvent:

    def __init__(self, node):
        self.node = node

    def write_break_script(self, file):
        description = RED + "Break  " + DEFAULT + "Node  " + self.node.name
        print("#" * 80, file=file)
        print("# {}".format(description), file=file)
        print("#" * 80, file=file)
        print(file=file)
        print("echo '{}'".format(description), file=file)
        self.node.write_kill_rift_to_file(file)
        print(file=file)

    def write_fix_script(self, file):
        description = GREEN + "Fix    " + DEFAULT + "Node  {}"
        print("#" * 80, file=file)
        print("# {}".format(description.format(self.node.name)), file=file)
        print("#" * 80, file=file)
        print(file=file)
        self.node.write_netns_start_scr_to_file_2(file, description)
        print(file=file)

class Fabric:

    def __init__(self):
        self.nr_pods = META_CONFIG['nr-pods']
        self.pods = []
        self.planes = []
        pods_y_pos = GLOBAL_Y_OFFSET
        # Only generate superspine nodes and planes if there is more than one pod
        if self.nr_pods > 1:
            nr_planes = 1   # TODO: Implement multi-plane
            only_plane = (nr_planes == 1)
            planes_y_pos = GLOBAL_Y_OFFSET
            pods_y_pos += NODE_Y_SIZE + SUPERSPINE_TO_POD_Y_INTERVAL
            for index in range(0, nr_planes):
                global_plane_id = index + 1
                plane_name = "plane-" + str(global_plane_id)
                pod = Plane(self, plane_name, global_plane_id, only_plane, planes_y_pos)
                self.planes.append(pod)
        # Generate the pods with leaf and spine nodes within them
        only_pod = (self.nr_pods == 1)
        for index in range(0, self.nr_pods):
            global_pod_id = index + 1
            pod_name = "pod-" + str(global_pod_id)
            pod = Pod(self, pod_name, global_pod_id, only_pod, pods_y_pos)
            self.pods.append(pod)
        # Center the pods and planes
        pod_x_center_shift = (self.x_size() - self.pods_total_x_size()) // 2
        for pod in self.pods:
            pod.x_center_shift = pod_x_center_shift
        plane_x_center_shift = (self.x_size() - self.planes_total_x_size()) // 2
        for plane in self.planes:
            plane.x_center_shift = plane_x_center_shift
        # Generate the links between the superspine nodes and the spine nodes
        if self.planes:
            # TODO: Add support for multi-plane
            self.create_links_single_plane()

    def create_links_single_plane(self):
        # Superspine to spine links (single plane)
        assert len(self.planes) == 1
        plane = self.planes[0]
        for superspine_node in plane.nodes:
            for pod in self.pods:
                for spine_node in pod.nodes_by_level[SPINE_LEVEL]:
                    _link = plane.create_link(superspine_node, spine_node)

    def write_config(self):
        file_name = getattr(ARGS, 'output-file-or-dir')
        if file_name is None:
            self.write_config_to_file(sys.stdout, netns=False)
        else:
            try:
                with open(file_name, 'w') as file:
                    self.write_config_to_file(file, netns=False)
            except IOError:
                fatal_error('Could not open output configuration file "{}"'.format(file_name))

    def write_config_to_file(self, file, netns):
        print("shards:", file=file)
        print("  - id: 0", file=file)
        print("    nodes:", file=file)
        for pod in self.pods:
            pod.write_config_to_file(file, netns)
        for plane in self.planes:
            plane.write_config_to_file(file, netns)

    def write_netns_configs_and_scripts(self):
        dir_name = getattr(ARGS, 'output-file-or-dir')
        if dir_name is None:
            fatal_error("Output directory name is missing (mandatory for --netns)")
        try:
            os.mkdir(dir_name)
        except FileExistsError:
            fatal_error("Output directory '{}' already exists".format(dir_name))
        except IOError:
            fatal_error("Could not create output directory '{}'".format(dir_name))
        for pod in self.pods:
            pod.write_netns_configs_and_scripts()
        for plane in self.planes:
            plane.write_netns_configs_and_scripts()
        self.write_netns_start_script()
        self.write_netns_stop_script()
        self.write_netns_check_script()
        self.write_netns_chaos_script()

    def write_netns_any_script(self, script_file_name, write_script_function):
        dir_name = getattr(ARGS, 'output-file-or-dir')
        file_name = dir_name + '/' + script_file_name
        try:
            with open(file_name, 'w') as file:
                print("#!/bin/bash", file=file)
                write_script_function(file)
        except IOError:
            fatal_error('Could not open script file "{}"'.format(file_name))
        try:
            existing_stat = os.stat(file_name)
            os.chmod(file_name, existing_stat.st_mode | stat.S_IXUSR)
        except IOError:
            fatal_error('Could not make script file "{}" executable'.format(file_name))

    def write_netns_start_script(self):
        self.write_netns_any_script("start.sh", self.write_netns_start_scr_to_file)

    def write_netns_stop_script(self):
        self.write_netns_any_script("stop.sh", self.write_netns_stop_scr_to_file)

    def write_netns_check_script(self):
        self.write_netns_any_script("check.sh", self.write_netns_check_scr_to_file)

    def write_netns_chaos_script(self):
        self.write_netns_any_script("chaos.sh", self.write_netns_chaos_scr_to_file)

    def write_progress_msg(self, file, message):
        print('echo "{}"'.format(message), file=file)

    def write_netns_start_scr_to_file(self, file):
        # Note: Plane has to go first, because superspine to spine links are owned by the space
        # group, not the pod group.
        for plane in self.planes:
            plane.write_netns_start_scr_to_file_1(file)
        for pod in self.pods:
            pod.write_netns_start_scr_to_file_1(file)
        for plane in self.planes:
            plane.write_netns_start_scr_to_file_2(file)
        for pod in self.pods:
            pod.write_netns_start_scr_to_file_2(file)

    def write_netns_stop_scr_to_file(self, file):
        for plane in self.planes:
            plane.write_netns_stop_scr_to_file_1(file)
        for pod in self.pods:
            pod.write_netns_stop_scr_to_file_1(file)
        for plane in self.planes:
            plane.write_netns_stop_scr_to_file_2(file)
        for pod in self.pods:
            pod.write_netns_stop_scr_to_file_2(file)

    def write_netns_check_scr_to_file(self, file):
        print("FAILURE_COUNT=0", file=file)
        all_leaf_nodes = []
        for pod in self.pods:
            for leaf_node in pod.nodes_by_level[LEAF_LEVEL]:
                all_leaf_nodes.append(leaf_node)
        self.write_netns_ping_all_pairs(file, all_leaf_nodes)
        print("echo", file=file)
        print("echo Number of failures: $FAILURE_COUNT", file=file)
        print("if [ $FAILURE_COUNT -ne 0 ]; then\n"
              "    echo\n"
              "    echo '*** THERE WERE FAILURES ***'\n"
              "fi", file=file)
        print("exit $FAILURE_COUNT", file=file)

    def write_netns_ping_all_pairs(self, file, nodes):
        print("echo '\n*** ping ***'", file=file)
        for from_node in nodes:
            for to_node in nodes:
                if from_node != to_node:
                    for from_address in from_node.lo_addresses:
                        for to_address in to_node.lo_addresses:
                            print("echo", file=file)
                            self.write_netns_ping_to_file(file, from_node, from_address, to_node,
                                                          to_address)

    def write_netns_ping_to_file(self, file, from_node, from_address, to_node, to_address):
        description = ("ping {} {} -> {} {}"
                       .format(from_node.name, from_address, to_node.name, to_address))
        command = ("ip netns exec {} ping -f -c5 -w1 -I {} {}"
                   .format(from_node.ns_name, from_address, to_address))
        self.write_netns_chk_command_to_file(file, description, command)

    def write_netns_trace_to_file(self, file, from_node, from_address, to_node, to_address):
        description = ("trace-route {} {} -> {} {}"
                       .format(from_node.name, from_address, to_node.name, to_address))
        command = ("ip netns exec {} traceroute -n -m 5 -s {} {}"
                   .format(from_node.ns_name, from_address, to_address))
        self.write_netns_out_command_to_file(file, description, command)

    def write_netns_chk_command_to_file(self, file, description, command):
        wrap_command = "OUTPUT=$({} 2>&1)".format(command)
        print(wrap_command, file=file)
        check_result = ("if [ $? -eq 0 ]; then\n"
                        "    echo OK: '{0}'\n"
                        "else\n"
                        "    echo FAIL: '{0}'\n"
                        "    FAILURE_COUNT=$((FAILURE_COUNT+1))\n"
                        "fi".format(description))
        print(check_result, file=file)

    def write_netns_out_command_to_file(self, file, description, command):
        print("echo '{}'".format(description), file=file)
        print(command, file=file)

    def write_netns_chaos_scr_to_file(self, file):
        # pylint:disable=too-many-statements
        # Keep track of the links and the nodes which are currently 'clean' i.e. not affected by any
        # failure event.
        clean_links = []
        clean_nodes = []
        for pod in self.pods:
            clean_links.extend(pod.links)
            clean_nodes.extend(pod.nodes)
        for plane in self.planes:
            clean_links.extend(plane.links)
            clean_nodes.extend(plane.nodes)
        # Prepare a script for failure events and repair events.
        more_link_events = self.get_chaos_config('nr-link-events', DEFAULT_CHAOS_NR_LINK_EVENTS)
        more_node_events = self.get_chaos_config('nr-node-events', DEFAULT_CHAOS_NR_NODE_EVENTS)
        event_interval = self.get_chaos_config('event-interval', DEFAULT_CHAOS_EVENT_INTERVAL)
        max_concurrent_events = self.get_chaos_config('max-concurrent-events',
                                                      DEFAULT_CHAOS_MAX_CONCURRENT_EVENTS)
        current_events = []
        while more_link_events > 0 or more_node_events > 0:
            # Choose whether to break something or fix something (depends on the number of things
            # currently broken)
            if random.randint(0, max_concurrent_events - 1) < len(current_events):
                # Fix something. Randomly pick a current event, and fix it.
                event = random.choice(current_events)
                current_events.remove(event)
                event.write_fix_script(file)
                if isinstance(event, LinkDownEvent):
                    clean_links.append(event.link)
                elif isinstance(event, NodeDownEvent):
                    clean_nodes.append(event.node)
                else:
                    assert False
            else:
                # Break something. What are we going to break, a link or a node?
                if random.randint(0, more_link_events + more_node_events - 1) < more_link_events:
                    # Break a link (if there is a clean link remaining)
                    if not clean_links:
                        continue
                    link = random.choice(clean_links)
                    event = LinkDownEvent(link)
                    event.write_break_script(file)
                    clean_links.remove(link)
                    current_events.append(event)
                    more_link_events -= 1
                else:
                    # Break a node
                    if not clean_nodes:
                        continue
                    node = random.choice(clean_nodes)
                    event = NodeDownEvent(node)
                    event.write_break_script(file)
                    clean_nodes.remove(node)
                    current_events.append(event)
                    more_node_events -= 1
            # Delay between events
            print("sleep {}".format(event_interval), file=file)
            print(file=file)
        # Fix everything that is still broken, without delays in between
        while current_events:
            event = current_events.pop()
            event.write_fix_script(file)
        # One final delay to let everything reconverge
        print("sleep {}".format(event_interval), file=file)
        print(file=file)

    def choose_break_or_fix_node(self, clean_nodes, affected_nodes):
        # Returns True for break, False for fix
        nr_clean_nodes = len(clean_nodes)
        nr_affected_nodes = len(affected_nodes)
        nr_nodes = nr_clean_nodes + nr_affected_nodes
        assert nr_nodes > 1
        # pylint: disable=simplifiable-if-statement
        if random.randint(1, nr_nodes) <= nr_clean_nodes:
            # Break something
            return True
        else:
            # Fix something
            return False

    @staticmethod
    def get_chaos_config(attribute, default_value):
        if 'chaos' in META_CONFIG and attribute in META_CONFIG['chaos']:
            return META_CONFIG['chaos'][attribute]
        else:
            return default_value

    def write_graphics(self):
        file_name = ARGS.graphics_file
        assert file_name is not None
        try:
            with open(file_name, 'w') as file:
                self.write_graphics_to_file(file)
        except IOError:
            fatal_error('Could not open graphics file "{}"'.format(file_name))

    def write_graphics_to_file(self, file):
        self.svg_start(file)
        for pod in self.pods:
            pod.write_graphics_to_file(file)
        for plane in self.planes:
            plane.write_graphics_to_file(file)
        self.svg_end(file)

    def svg_start(self, file):
        file.write('<svg '
                   'xmlns="http://www.w3.org/2000/svg '
                   'xmlns:xlink="http://www.w3.org/1999/xlink" '
                   'width=1000000 '
                   'height=1000000 '
                   'id="tooltip-svg">\n')

    def svg_end(self, file):
        file.write(END_OF_SVG)

    def write_allocations(self):
        dir_name = getattr(ARGS, 'output-file-or-dir')
        file_name = "{}/allocations.txt".format(dir_name)
        try:
            with open(file_name, 'w') as file:
                self.write_allocations_to_file(file)
        except IOError:
            fatal_error('Could not open allocations file "{}"'.format(file_name))

    def write_allocations_to_file(self, file):
        tab = table.Table()
        tab.add_row([
            ["Node", "Name"],
            ["Loopback", "Address"],
            ["System", "ID"],
            ["Network", "Namespace"],
            ["Interface", "Name"],
            ["Interface", "Address"],
            ["Neighbor", "Node"],
            ["Neighbor", "Address"]
        ])
        for pod in self.pods:
            for node in pod.nodes:
                node.add_allocations_to_table(tab)
        for plane in self.planes:
            for node in plane.nodes:
                node.add_allocations_to_table(tab)
        print(tab.to_string(), file=file)

    def check(self):
        okay = True
        for pod in self.pods:
            for node in pod.nodes:
                okay = node.check() and okay
        for plane in self.planes:
            for node in plane.nodes:
                okay = node.check() and okay
        return okay

    def pods_total_x_size(self):
        total_x_size = 0
        for pod in self.pods:
            total_x_size += pod.x_size() + GROUP_X_INTERVAL
        if total_x_size > 0:
            total_x_size -= GROUP_X_INTERVAL
        return total_x_size

    def planes_total_x_size(self):
        total_x_size = 0
        for plane in self.planes:
            total_x_size += plane.x_size() + GROUP_X_INTERVAL

        if total_x_size > 0:
            total_x_size -= GROUP_X_INTERVAL

        return total_x_size

    def x_size(self):
        return max(self.pods_total_x_size(), self.planes_total_x_size())

    # walk the fabric and check @ every node whether the correct host routes are present
    # the host routes are basically loopbacks of all the nodes lower in hierarchy
    def check_host_routes(self):
        okay = True

        return okay

class TelnetSession:

    def __init__(self, netns, port):
        self._netns = netns
        self._port = port
        log_file_name = "config_generator_check.log"
        if "RIFT_TEST_RESULTS_DIR" in os.environ:
            log_file_name = os.environ["RIFT_TEST_RESULTS_DIR"] + '/' + log_file_name
        self._log_file = open(log_file_name, 'ab')
        cmd = "ip netns exec {} telnet localhost {}".format(netns, port)
        self._expect_session = pexpect.spawn(cmd, logfile=self._log_file)
        self.connected = self.expect("Connected")

    def write_result(self, msg):
        self._log_file.write(msg.encode())
        self._log_file.flush()

    def stop(self):
        # Attempt graceful exit
        self._expect_session.send_line("exit")
        # Terminate it forcefully, in case the graceful exit did not work for some reason
        self._expect_session.terminate(force=True)
        self.write_result("\n\n*** End session to {}:{}\n\n".format(self._netns, self._port))

    def send_line(self, line):
        self._expect_session.sendline(line)

    def read_line(self):
        line = self._expect_session.readline()
        return line.decode('utf-8').strip()

    def log_expect_failure(self):
        self.write_result("\n\n*** Did not find expected pattern\n\n")
        # Generate a call stack in the log file for easier debugging
        for line in traceback.format_stack():
            self.write_result(line.strip())
            self.write_result("\n")

    def expect(self, pattern, timeout=1.0):
        self.write_result("\n\n*** Expect: {}\n\n".format(pattern))
        # Report the failures outside of this block, otherwise pytest reports a huge callstack
        try:
            self._expect_session.expect(pattern, timeout)
        except (pexpect.TIMEOUT, pexpect.exceptions.EOF, OSError, IOError):
            failed = True
        else:
            failed = False
        if failed:
            self.log_expect_failure()
            return False
        else:
            return True

    def table_expect(self, pattern, timeout=1.0):
        # Allow multiple spaces at end of each cell, even if only one was asked for
        pattern = pattern.replace(" |", " +|")
        # The | character is a literal end-of-cell, not a regexp OR
        pattern = pattern.replace("|", "[|]")
        # Since we confiscated | to mean end-of-cell, we use /// for regexp OR
        pattern = pattern.replace("///", "|")
        result = self.expect(pattern, timeout)
        return result

    def wait_prompt(self, timeout=1.0):
        return self.expect(".*> ", timeout)

    def parse_show_output(self, show_command):
        # Send a marker (which will cause a command syntax error) and look for the echo. This is to
        # avoid accidentally parsing output from some previous show command.
        marker = "show PARSE_SHOW_OUTPUT_MARKER"
        self.send_line(marker)
        while True:
            line = self.read_line()
            if marker in line:
                break
        # Send the command whose output we want to collect
        self.send_line(show_command)
        # Send a blank line to make sure we have a prompt followed by a newline at the end
        self.send_line('')
        # Look for echo of show command in output
        while True:
            line = self.read_line()
            if show_command in line:
                break
        parsed_tables = []
        table_title = None
        while True:
            line = self.read_line()
            if line == '':
                # Skip blank lines
                continue
            elif '+' in line:
                # Table contents starts
                parsed_table = self.parse_table(table_title)
                table_title = None
                parsed_tables.append(parsed_table)
            elif ':' in line:
                # Table title (there should only be one line of table title)
                if table_title is not None:
                    raise RuntimeError("Table title is more than one line")
                table_title = line.strip(':')
            elif '>' in line:
                # Reached prompt for next command; we are done
                return parsed_tables
            else:
                raise RuntimeError("Unrecognized format of show command output")

    def parse_table(self, table_title):
        parsed_table = {}
        parsed_table['title'] = table_title
        parsed_table['rows'] = []
        row = None
        while True:
            line = self.read_line()
            if line == '':
                # Every table is followed by a blank line, so we have reached the end of the table
                return parsed_table
            elif '+-' in line:
                # Row seperator
                if row:
                    parsed_table['rows'].append(row)
                    row = None
            elif '|' in line:
                # Row contents
                add_to_row = line.split('|')
                add_to_row = add_to_row[1:-1]
                add_to_row = [[cell.strip()] for cell in add_to_row]
                if row:
                    row = [cell + new_cell for (cell, new_cell) in zip(row, add_to_row)]
                else:
                    row = add_to_row
            else:
                raise RuntimeError("Unrecognized format of table")

def parse_meta_configuration(file_name):
    try:
        with open(file_name, 'r') as stream:
            try:
                config = yaml.safe_load(stream)
            except yaml.YAMLError as exception:
                raise exception
    except IOError:
        fatal_error('Could not open input meta-configuration file "{}"'.format(file_name))
    validator = cerberus.Validator()
    if not validator.validate(config, SCHEMA):
        pretty_printer = pprint.PrettyPrinter()
        pretty_printer.pprint(validator.errors)
        exit(1)
    return validator.normalized(config)

def validate_meta_configuration():
    nr_pods = META_CONFIG['nr-pods']
    if 'nr-superspine-nodes' in META_CONFIG:
        nr_superspine_nodes = META_CONFIG['nr-superspine-nodes']
    else:
        nr_superspine_nodes = None
    if (nr_pods > 1) and (nr_superspine_nodes is None):
        fatal_error("nr-superspine-nodes must be configured if number of PODs > 1")
    if (nr_pods == 1) and (nr_superspine_nodes is not None):
        fatal_error("nr-superspine-nodes must not be configured if there is only one POD")

def parse_command_line_arguments():
    parser = argparse.ArgumentParser(description='RIFT configuration generator')
    parser.add_argument(
        'input-meta-config-file',
        help='Input meta-configuration file name')
    parser.add_argument(
        'output-file-or-dir',
        nargs='?',
        help='Output file or directory name')
    parser.add_argument(
        '-n', '--netns-per-node',
        action="store_true",
        help='Use network namespace per node')
    parser.add_argument(
        '-g', '--graphics-file',
        help='Output file name for graphical representation')
    parser.add_argument(
        '-c', '--check',
        action="store_true",
        help='Check running configuration')
    args = parser.parse_args()
    return args

def fatal_error(error_msg):
    print(error_msg, file=sys.stderr)
    sys.exit(1)

def main():
    # pylint:disable=global-statement
    global ARGS
    global META_CONFIG
    ARGS = parse_command_line_arguments()
    input_file_name = getattr(ARGS, 'input-meta-config-file')
    META_CONFIG = parse_meta_configuration(input_file_name)
    validate_meta_configuration()
    fabric = Fabric()
    if ARGS.check:
        if not ARGS.netns_per_node:
            fatal_error('Check command-line option only supported in netns-per-node mode')
        if fabric.check():
            sys.exit(0)
        else:
            sys.exit(1)
    if ARGS.netns_per_node:
        fabric.write_netns_configs_and_scripts()
        fabric.write_allocations()
    else:
        fabric.write_config()
    if ARGS.graphics_file is not None:
        fabric.write_graphics()

if __name__ == "__main__":
    main()
