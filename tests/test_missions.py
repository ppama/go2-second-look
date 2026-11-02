import pytest

from scout.config import load_config
from scout.mission_lang import Interpreter, Rejected, validate
from scout.mission_world import TruthVision, World, home_error
from scout.mission_writer import parse_reply
from scout.sim_robot import SimRobot

STATIONS = {"A", "B", "C"}
GOOD = """
for s in ["B", "C"]:
    go_to(s)
    r = inspect()
    if r.changed and not r.hazard:
        r = look_again()
    elif r.hazard:
        r = look_again()
    report(s, r)
return_home()
"""
ATTACKS = {
    "import": 'import os\nreturn_home()',
    "from import": 'from os import system\nreturn_home()',
    "open file": 'open("x")\nreturn_home()',
    "exec": 'exec("1")\nreturn_home()',
    "eval": 'r = eval("1")\nreturn_home()',
    "dunder": 'r = inspect()\nif r.__class__:\n    pass\nreturn_home()',
    "attribute call": 'robot.command(9, 0, 0)\nreturn_home()',
    "while": 'while True:\n    go_to("A")\nreturn_home()',
    "lambda": 'r = lambda: 1\nreturn_home()',
    "def": 'def f():\n    pass\nreturn_home()',
    "class": 'class A:\n    pass\nreturn_home()',
    "try": 'try:\n    go_to("A")\nfinally:\n    pass\nreturn_home()',
    "unknown station": 'go_to("D")\nreturn_home()',
    "coordinates": 'go_to(9, 9)\nreturn_home()',
    "loop over range": 'for i in range(9):\n    go_to("A")\nreturn_home()',
    "big list": 'for s in ["A","A","A","A","A","A","A"]:\n    go_to(s)\nreturn_home()',
    "no return": 'go_to("A")',
    "two returns": 'return_home()\nreturn_home()',
    "return in branch": 'r = inspect()\nif r.changed:\n    return_home()\nreturn_home()',
    "rebinding action": 'go_to = inspect()\nreturn_home()',
    "keyword": 'go_to(station="A")\nreturn_home()',
    "f string": 'report(f"{1}", 1)\nreturn_home()',
    "constant test": 'if True:\n    go_to("A")\nreturn_home()',
}


@pytest.mark.parametrize("name", ATTACKS)
def test_attacks_are_rejected(name):
    with pytest.raises(Rejected):
        validate(ATTACKS[name], STATIONS)


def test_loop_budget_stops_nested_loops():
    src = 'for a in ["A","B","A","B","A","B"]:\n    for b in ["A","B","A","B","A","B"]:\n        for c in ["A","B","A","B","A","B"]:\n            go_to(c)\nreturn_home()'
    tree = validate(src, STATIONS)

    class Stub:
        station = "A"

        def go_to(self, s):
            pass

    with pytest.raises(Rejected):
        Interpreter(Stub()).run(tree)


@pytest.mark.parametrize("truth,looks", [({}, []), ({"C": "removed"}, ["C"]), ({"B": "fallen", "C": "removed"}, ["B", "C"])])
def test_program_branches_on_scene(truth, looks):
    cfg = load_config()
    robot = SimRobot(cfg)
    trace = Interpreter(World(robot, cfg, TruthVision(truth))).run(validate(GOOD, STATIONS))
    assert trace.visits == ["B", "C"] and trace.looks == looks and set(trace.reports) == {"B", "C"}
    assert home_error(robot) < cfg["control"]["pos_tol"]
    robot.close()


def test_writer_reply_must_be_json():
    assert parse_reply('```json\n{"feasible": true, "program": "return_home()"}\n```')["feasible"]
    with pytest.raises(ValueError):
        parse_reply("sure, here is the code")
