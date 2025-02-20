import packet_common
import utils

DEST_TYPE_NODE = 1
DEST_TYPE_PREFIX = 2
DEST_TYPE_POS_DISAGG_PREFIX = 3

def make_node_dest(system_id, name, cost):
    return SPFDest(DEST_TYPE_NODE, system_id, name, None, set(), cost)

def make_prefix_dest(prefix, tags, cost, is_pos_disagg):
    if is_pos_disagg:
        return SPFDest(DEST_TYPE_POS_DISAGG_PREFIX, None, None, prefix, tags, cost)
    else:
        return SPFDest(DEST_TYPE_PREFIX, None, None, prefix, tags, cost)

class SPFDest:

    # Each possible destination in SPF calculation is represented by an SPFDest object. There are
    # two types of destinations: node destinations and prefix destinations.

    # TODO: Add support for Non-Equal Cost Multi-Path (NECMP)

    def __init__(self, dest_type, system_id, name, prefix, tags, cost):
        # Type of the SPFDest: DEST_TYPE_xxx
        self.dest_type = dest_type
        # System-id of the node for TYPE_NODE, None for TYPE_PREFIX/DEST_TYPE_POS_DISAGG_PREFIX
        self.system_id = system_id
        # Name of the node for TYPE_NODE, None for TYPE_PREFIX/DEST_TYPE_POS_DISAGG_PREFIX
        self.name = name
        # Destination prefix for TYPE_PREFIX/DEST_TYPE_POS_DISAGG_PREFIX, None for TYPE_NODE
        self.prefix = prefix
        # Prefix  tags for TYPE_PREFIX/DEST_TYPE_POS_DISAGG_PREFIX, None for TYPE_NODE
        self.tags = tags
        # Cost of best-known path to this destination (is always a single cost, even in the case of
        # ECMP)
        self.cost = cost
        # Has the best path to the destination been determined?
        self.best = False
        # System-ID of node before this destination (predecessor) on best known path (*)
        # (*) here and below means: contains more than one element in the case of ECMP
        self.predecessors = []
        # (if_name, addr) of direct next-hop from source node towards this destination (*)
        self.ipv4_next_hops = []
        self.ipv6_next_hops = []
        # This is a prefix that needs to be positively disaggregated
        self.positively_disaggregate = False

    def key(self):
        if self.dest_type == DEST_TYPE_NODE:
            return self.system_id
        else:
            assert self.dest_type in [DEST_TYPE_PREFIX, DEST_TYPE_POS_DISAGG_PREFIX]
            return self.prefix

    def __eq__(self, other):
        return (self.dest_type, self.key()) == (other.dest_type, other.key())

    def __lt__(self, other):
        return (self.dest_type, self.key()) < (other.dest_type, other.key())

    def is_node(self):
        return self.dest_type == DEST_TYPE_NODE

    def add_predecessor(self, predecessor_system_id):
        self.predecessors.append(predecessor_system_id)

    def add_ipv4_next_hop(self, next_hop):
        if (next_hop is not None) and (next_hop not in self.ipv4_next_hops):
            self.ipv4_next_hops.append(next_hop)

    def add_ipv6_next_hop(self, next_hop):
        if (next_hop is not None) and (next_hop not in self.ipv6_next_hops):
            self.ipv6_next_hops.append(next_hop)

    def inherit_next_hops(self, other_spf_destination):
        for next_hop in other_spf_destination.ipv4_next_hops:
            if next_hop not in self.ipv4_next_hops:
                self.ipv4_next_hops.append(next_hop)
        for next_hop in other_spf_destination.ipv6_next_hops:
            if next_hop not in self.ipv6_next_hops:
                self.ipv6_next_hops.append(next_hop)

    def inherit_tags(self, other_spf_destination):
        if (self.tags is None) and (other_spf_destination.tags is None):
            return
        if self.tags is None:
            self.tags = set()
        self.tags = self.tags.union(other_spf_destination.tags)

    @staticmethod
    def cli_summary_headers():
        return [
            "Destination",
            "Cost",
            ["Predecessor", "System IDs"],
            ["Tags"],
            "Disaggregate",
            "IPv4 Next-hops",
            "IPv6 Next-hops"
        ]

    def cli_summary_attributes(self):
        if self.dest_type == DEST_TYPE_NODE:
            destination_str = utils.system_id_str(self.system_id)
            if self.name:
                destination_str += " (" + self.name + ")"
        elif self.dest_type == DEST_TYPE_PREFIX:
            destination_str = packet_common.ip_prefix_str(self.prefix)
        elif self.dest_type == DEST_TYPE_POS_DISAGG_PREFIX:
            destination_str = packet_common.ip_prefix_str(self.prefix) + " (Disagg)"
        else:
            assert False
        if self.tags:
            tags_str = list(self.tags)
        else:
            tags_str = ""
        if self.positively_disaggregate:
            disaggregate_str = 'Positive'
        else:
            disaggregate_str = ''
        return [
            destination_str,
            self.cost,
            sorted(self.predecessors),
            tags_str,
            disaggregate_str,
            [str(next_hop) for next_hop in sorted(self.ipv4_next_hops)],
            [str(next_hop) for next_hop in sorted(self.ipv6_next_hops)]
        ]
