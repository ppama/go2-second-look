"""A small mission language for AI-written programs.

Programs are parsed and interpreted here. They are never passed to exec or eval, so only the
statements below can run, and every action goes through the normal limits.

    for s in ["B", "C"]:
        go_to(s)
        r = inspect()
        if r.changed:
            r = look_again()
        report(s, r)
    return_home()
"""
import ast
from dataclasses import dataclass, field

ACTIONS = {"go_to", "inspect", "look_again", "report", "return_home"}
RETURNS_RESULT = {"inspect", "look_again"}
FIELDS = {"changed", "hazard"}
MAX_NODES = 300
MAX_LIST = 6
MAX_DEPTH = 3
MAX_ACTIONS = 40


class Rejected(ValueError):
    pass


def validate(source, stations):
    """Parse a program and return its syntax tree, or raise Rejected with the reason."""
    if len(source) > 4000:
        raise Rejected("program too long")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise Rejected(f"syntax error: {e.msg}") from e
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise Rejected("program too large")
    if not tree.body or not _is_call(tree.body[-1], "return_home"):
        raise Rejected("the last statement must be return_home()")
    if sum(_is_call(n, "return_home") for n in ast.walk(tree) if isinstance(n, ast.Expr)) != 1:
        raise Rejected("return_home() must appear exactly once")
    _block(tree.body, set(), set(), set(stations), 0)
    return tree


def _is_call(node, name):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == name


def _block(body, loop_vars, results, stations, depth):
    if depth > MAX_DEPTH:
        raise Rejected("nesting too deep")
    for node in body:
        if isinstance(node, ast.Expr):
            _call(node.value, loop_vars, results, stations)
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise Rejected("only simple assignment is allowed")
            if not isinstance(node.value, ast.Call) or getattr(node.value.func, "id", "") not in RETURNS_RESULT:
                raise Rejected("only inspect() or look_again() can be assigned")
            _call(node.value, loop_vars, results, stations)
            if node.targets[0].id in loop_vars or node.targets[0].id in ACTIONS:
                raise Rejected("invalid variable name")
            results.add(node.targets[0].id)
        elif isinstance(node, ast.For):
            if node.orelse or not isinstance(node.target, ast.Name):
                raise Rejected("only plain for loops are allowed")
            items = node.iter
            if not isinstance(items, ast.List) or len(items.elts) > MAX_LIST:
                raise Rejected("a loop needs a short list of station names")
            for item in items.elts:
                if not isinstance(item, ast.Constant) or item.value not in stations:
                    raise Rejected("a loop may only list known stations")
            if node.target.id in results or node.target.id in ACTIONS:
                raise Rejected("invalid loop variable")
            _block(node.body, loop_vars | {node.target.id}, results, stations, depth + 1)
        elif isinstance(node, ast.If):
            _test(node.test, results)
            _block(node.body, loop_vars, results, stations, depth + 1)
            _block(node.orelse, loop_vars, results, stations, depth + 1)
        else:
            raise Rejected(f"statement not allowed: {type(node).__name__}")


def _call(node, loop_vars, results, stations):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id not in ACTIONS:
        raise Rejected("only mission actions can be called")
    if node.keywords:
        raise Rejected("keyword arguments are not allowed")
    name, args = node.func.id, node.args
    if name == "go_to":
        if len(args) != 1:
            raise Rejected("go_to takes one station")
        _station(args[0], loop_vars, stations)
    elif name == "report":
        if len(args) != 2 or not isinstance(args[1], ast.Name) or args[1].id not in results:
            raise Rejected("report takes a station and an inspected result")
        _station(args[0], loop_vars, stations)
    elif args:
        raise Rejected(f"{name} takes no arguments")


def _station(node, loop_vars, stations):
    if isinstance(node, ast.Name) and node.id in loop_vars:
        return
    if isinstance(node, ast.Constant) and node.value in stations:
        return
    raise Rejected("unknown station")


def _test(node, results):
    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id not in results or node.attr not in FIELDS:
            raise Rejected("a test may only read .changed or .hazard of a result")
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        _test(node.operand, results)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            _test(value, results)
    else:
        raise Rejected("test not allowed")


@dataclass
class Result:
    changed: bool
    hazard: bool
    summary: str = ""


@dataclass
class Trace:
    visits: list = field(default_factory=list)
    looks: list = field(default_factory=list)
    reports: dict = field(default_factory=dict)


class Interpreter:
    """Runs a validated program by walking its tree. Each action is counted against a budget."""

    def __init__(self, world):
        self.world, self.vars, self.loop = world, {}, {}
        self.trace, self.actions = Trace(), 0

    def run(self, tree):
        self._block(tree.body)
        return self.trace

    def _block(self, body):
        for node in body:
            if isinstance(node, ast.Expr):
                self._call(node.value)
            elif isinstance(node, ast.Assign):
                self.vars[node.targets[0].id] = self._call(node.value)
            elif isinstance(node, ast.For):
                for item in node.iter.elts:
                    self.loop[node.target.id] = item.value
                    self._block(node.body)
            elif isinstance(node, ast.If):
                self._block(node.body if self._test(node.test) else node.orelse)

    def _test(self, node):
        if isinstance(node, ast.Attribute):
            return getattr(self.vars[node.value.id], node.attr)
        if isinstance(node, ast.UnaryOp):
            return not self._test(node.operand)
        results = [self._test(v) for v in node.values]
        return all(results) if isinstance(node.op, ast.And) else any(results)

    def _station(self, node):
        return node.value if isinstance(node, ast.Constant) else self.loop[node.id]

    def _call(self, node):
        self.actions += 1
        if self.actions > MAX_ACTIONS:
            raise Rejected("action budget exceeded")
        name = node.func.id
        if name == "go_to":
            station = self._station(node.args[0])
            self.world.go_to(station)
            self.trace.visits.append(station)
        elif name == "inspect":
            return self.world.inspect()
        elif name == "look_again":
            self.trace.looks.append(self.world.station)
            return self.world.look_again()
        elif name == "report":
            self.trace.reports[self._station(node.args[0])] = self.vars[node.args[1].id]
        elif name == "return_home":
            self.world.return_home()
