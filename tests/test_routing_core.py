"""Small unit tests of the actual Dijkstra core without ArcGIS Pro.

These tests extract selected definitions from the published Script 29 AST, rather
than rewriting the routing algorithm. They do not validate geodata processing,
road snapping, damage matching, or field execution of ArcPy workflows.
"""

from __future__ import annotations

import ast
import heapq
from collections import defaultdict
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "29_emergency_service_accessibility_analysis.py"
TARGET_DEFINITIONS = {
    "node_key",
    "Graph",
    "edge_cost",
    "dijkstra",
    "reconstruct_edges",
}


def load_routing_core() -> dict:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    chosen = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and node.name in TARGET_DEFINITIONS
    ]
    assert {node.name for node in chosen} == TARGET_DEFINITIONS
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] + chosen,
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {
        "__name__": "gpem_routing_core_test",
        "heapq": heapq,
        "defaultdict": defaultdict,
        "NODE_ROUNDING_M": 1.0,
        "MULT_CLASS1": 1.5,
        "MULT_CLASS2": 5.0,
        "MULT_CLASS3_DEGRADED": 100.0,
        "MULT_VALIDATION": 2.0,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


core = load_routing_core()
Graph = core["Graph"]
edge_cost = core["edge_cost"]
dijkstra = core["dijkstra"]
reconstruct_edges = core["reconstruct_edges"]


def edge(length: float, severity: int = 0, validation: bool = False, usable: int = 1) -> dict:
    return {
        "base_len": length,
        "max_conf_class": severity,
        "touched_validation": validation,
        "eu": usable,
    }


class RoutingCoreTests(unittest.TestCase):
    def test_cost_multipliers_and_conservative_block(self):
        self.assertEqual(edge_cost(edge(10), allow_class3=False, degraded=False), 10.0)
        self.assertEqual(edge_cost(edge(10, validation=True), False, False), 20.0)
        self.assertEqual(edge_cost(edge(10, severity=1), False, False), 15.0)
        self.assertEqual(edge_cost(edge(10, severity=2), False, False), 50.0)
        self.assertIsNone(edge_cost(edge(10, severity=3), False, False))
        self.assertEqual(edge_cost(edge(10, severity=3), True, True), 1000.0)

    def test_confirmed_damage_takes_precedence_over_validation(self):
        self.assertEqual(edge_cost(edge(10, severity=1, validation=True), False, False), 15.0)

    def test_shortest_usable_detour_avoids_blocked_link(self):
        graph = Graph()
        a, b, c = [graph.get_node(x, y) for x, y in [(0, 0), (2, 0), (1, 1)]]
        graph.add_edge(a, b, edge(1, severity=3))
        graph.add_edge(a, c, edge(2))
        graph.add_edge(c, b, edge(2))
        dist, pred_node, pred_edge = dijkstra(graph, a, False, False, False)
        self.assertEqual(dist[b], 4.0)
        self.assertEqual(set(reconstruct_edges(a, b, pred_node, pred_edge)), {1, 2})

    def test_degraded_scenario_includes_high_penalty_link_if_necessary(self):
        graph = Graph()
        a, b = graph.get_node(0, 0), graph.get_node(1, 0)
        graph.add_edge(a, b, edge(3, severity=3))
        dist_conservative, *_ = dijkstra(graph, a, False, False, False)
        self.assertNotIn(b, dist_conservative)
        dist_degraded, *_ = dijkstra(graph, a, False, True, True)
        self.assertEqual(dist_degraded[b], 300.0)

    def test_emergency_use_flag_controls_eligibility(self):
        graph = Graph()
        a, b = graph.get_node(0, 0), graph.get_node(1, 0)
        graph.add_edge(a, b, edge(2, usable=0))
        self.assertNotIn(b, dijkstra(graph, a, False, False, False)[0])
        self.assertEqual(dijkstra(graph, a, True, False, False)[0][b], 2.0)

    def test_width_does_not_modify_numerical_edge_cost(self):
        narrow = edge(12, severity=2)
        wide = edge(12, severity=2)
        narrow["AvailableWidth_m"] = 1.0
        wide["AvailableWidth_m"] = 8.0
        self.assertEqual(edge_cost(narrow, False, False), edge_cost(wide, False, False))


if __name__ == "__main__":
    unittest.main()