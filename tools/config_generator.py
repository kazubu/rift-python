#!/usr/bin/env python3

import argparse
import pprint

import cerberus
import yaml

NEXT_SYSTEM_ID = 1
NEXT_INTERFACE_NR = 1
NODES = {}
INTERFACES = {}

class Node:

    def __init__(self, name, system_id, level):
        self.name = name
        self.system_id = system_id
        self.level = level
        self.rx_lie_mcast_address = generate_ipv4_address_str(224, 0, 1, 0, system_id)
        self.interfaces = []

    def create_interface(self, local_if_nr, remote_if_nr):
        # pylint:disable=global-statement
        global INTERFACES
        rx_lie_port = 20000 + local_if_nr
        tx_lie_port = 20000 + remote_if_nr
        rx_tie_port = 10000 + local_if_nr
        node_if_nr = len(self.interfaces) + 1
        if_name = "if" + str(node_if_nr)
        full_if_name = self.name + ":" + if_name
        interface = Interface(if_name, full_if_name, remote_if_nr, rx_lie_port, tx_lie_port,
                              rx_tie_port)
        self.interfaces.append(interface)
        INTERFACES[local_if_nr] = interface

class Interface:

    def __init__(self, name, full_name, remote_if_nr, rx_lie_port, tx_lie_port, rx_tie_port):
        self.name = name
        self.full_name = full_name
        self.remote_if_nr = remote_if_nr
        self.rx_lie_port = rx_lie_port
        self.tx_lie_port = tx_lie_port
        self.rx_tie_port = rx_tie_port

def create_node(name, level):
    # pylint:disable=global-statement
    global NEXT_SYSTEM_ID
    global NODES
    node = Node(name, NEXT_SYSTEM_ID, level)
    NEXT_SYSTEM_ID += 1
    NODES[node.system_id] = node
    return node

def create_link_between_nodes(node1, node2):
    # pylint:disable=global-statement
    global NEXT_INTERFACE_NR
    global INTERFACES
    if_1_nr = NEXT_INTERFACE_NR
    NEXT_INTERFACE_NR += 1
    if_2_nr = NEXT_INTERFACE_NR
    NEXT_INTERFACE_NR += 1
    node1.create_interface(if_1_nr, if_2_nr)
    node2.create_interface(if_2_nr, if_1_nr)

def write_nodes_configuration():
    # pylint:disable=global-statement
    global NODES
    global INTERFACES
    print("shards:")
    print("  - id: 0")
    print("    nodes:")
    for node in NODES.values():
        print("      - name: " + node.name)
        print("        level: " + str(node.level))
        print("        systemid: " + str(node.system_id))
        print("        rx_lie_mcast_address: " + node.rx_lie_mcast_address)
        print("        interfaces:")
        for interface in node.interfaces:
            remote_interface = INTERFACES[interface.remote_if_nr]
            description = "{} -> {}".format(interface.full_name, remote_interface.full_name)
            print("          - name: " + interface.name)
            print("            # " + description)
            print("            rx_lie_port: " + str(interface.rx_lie_port))
            print("            tx_lie_port: " + str(interface.tx_lie_port))
            print("            rx_tie_port: " + str(interface.rx_tie_port))

def generate_ipv4_address_str(byte1, byte2, byte3, byte4, offset):
    assert offset <= 65535
    byte4 += offset
    byte3 += offset // 256
    byte4 %= 256
    byte2 += offset // 256
    byte3 %= 256
    byte1 += offset // 256
    byte2 %= 256
    ip_address_str = "{}.{}.{}.{}".format(byte1, byte2, byte3, byte4)
    return ip_address_str

SCHEMA = {
    'nr-leaf-nodes': {'required': True, 'type': 'integer', 'min': 0},
    'nr-spine-nodes': {'required': True, 'type': 'integer', 'min': 0},
}

def parse_meta_configuration(filename):
    with open(filename, 'r') as stream:
        try:
            config = yaml.load(stream)
        except yaml.YAMLError as exception:
            raise exception
    validator = cerberus.Validator()
    if not validator.validate(config, SCHEMA):
        pretty_printer = pprint.PrettyPrinter()
        pretty_printer.pprint(validator.errors)
        exit(1)

    return config

def parse_command_line_arguments():
    parser = argparse.ArgumentParser(description='RIFT configuration generator')
    parser.add_argument('configfile', help='Meta-configuration filename')
    args = parser.parse_args()
    return args

def generate_configuration(meta_config):
    nr_leaf_nodes = meta_config['nr-leaf-nodes']
    nr_spine_nodes = meta_config['nr-spine-nodes']
    leaf_nodes = []
    for index in range(1, nr_leaf_nodes+1):
        name = "leaf" + str(index)
        leaf_node = create_node(name, level=0)
        leaf_nodes.append(leaf_node)
    spine_nodes = []
    for index in range(1, nr_spine_nodes+1):
        name = "spine" + str(index)
        spine_node = create_node(name, level=1)
        spine_nodes.append(spine_node)
    for leaf_node in leaf_nodes:
        for spine_node in spine_nodes:
            create_link_between_nodes(leaf_node, spine_node)
    write_nodes_configuration()

def main():
    args = parse_command_line_arguments()
    meta_config = parse_meta_configuration(args.configfile)
    generate_configuration(meta_config)

if __name__ == "__main__":
    main()
