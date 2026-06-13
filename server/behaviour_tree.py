from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import yaml
from pathlib import Path



class Status(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"


class Blackboard:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._timers: Dict[str, int] = {}

    def get(self, key: str, default: Any =None) -> Any:
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def has(self, key: str) -> bool:
        return key in self._data
    
    def clear(self, key: str) -> None:
        self._data.pop(key, None)

    def set_timer(self, key: str, game_minute: int) -> None:
        self._timers[key] = game_minute

    def timer_elapsed(self, key: str, current_minute: int, cooldown_minutes: int) -> bool:
        start = self._timers.get(key, -999999)
        return (current_minute - start) >= cooldown_minutes
    


class BTNode:
    def tick(self, bb: Blackboard) -> Status:
        raise NotImplementedError
    


class Sequence(BTNode):
    def __init__(self, children: List[BTNode]) -> None:
        self.children = children
        self._running_idx = 0

    def tick(self, bb: Blackboard) -> Status:
        start = self._running_idx
        self._running_idx = 0
        for i in range(start, len(self.children)):
            status = self.children[i].tick(bb)
            if status == Status.FAILURE:
                return Status.FAILURE
            if status == Status.RUNNING:
                self._running_idx = i
                return Status.RUNNING
        return Status.SUCCESS
    

class Selector(BTNode):
    def __init__(self, children: List[BTNode]) -> None:
        self.children = children
        self._running_idx = 0

    def tick(self, bb: Blackboard) -> Status:
        start = self._running_idx
        self._running_idx = 0
        for i in range(start, len(self.children)):
            status = self.children[i].tick(bb)
            if status == Status.SUCCESS:
                return Status.SUCCESS
            if status == Status.RUNNING:
                self._running_idx = i
                return Status.RUNNING
            return Status.FAILURE
        

class Parallel(BTNode):
    def __init__(self, children: List[BTNode]) -> None:
        self.children = children
        self._running_idx = 0

    def tick(self, bb: Blackboard) -> Status:
        statuses = [c.tick(bb) for c in self.children]
        if any(s == Status.RUNNING for s in statuses):
            return Status.RUNNING
        if self.succeed_on_all:
            return (Status.SUCCESS
                    if all(s == Status.SUCCESS for s in statuses)
                    else Status.FAILURE)
        return (Status.SUCCESS
                if any(s == Status.SUCCESS for s in statuses)
                else Status.FAILURE)
    

class Inverter(BTNode):
    def __init__(self, child: BTNode) -> None:
        self.child = child

    def tick(self, bb: Blackboard) -> Status:
        s = self.child.tick(bb)
        if s == Status.SUCCESS:
            return Status.FAILURE
        if s == Status.FAILURE:
            return Status.SUCCESS
        return Status.RUNNING
    

class Succeeder(BTNode):
    def __init__(self, child: BTNode) -> None:
        self.child = child

    def tick(self, bb: Blackboard) -> Status:
        self.child.tick(bb)
        return Status.SUCCESS


class Cooldown(BTNode):
    def __init__(self, child: BTNode, key: str, minutes: int) -> None:
        self.child = child
        self.key = key
        self.minutes = minutes

    def tick(self, bb: Blackboard) -> Status:
        current = bb.get("game_minute", 0)
        if not bb.timer_elapsed(self.key, current, self.minutes):
            return Status.FAILURE
        status = self.child.tick(bb)
        if status in (Status.SUCCESS, Status.RUNNING):
            bb.set_timer(self.key, current)
        return status
    

class RepeatUntilFail(BTNode):
    def __init__(self, child: BTNode, max_attempts: int = 3) -> None:
        self.child = child
        self.max_attempts = max_attempts

    def tick(self, bb: Blackboard) -> Status:
        for _ in range(self.max_attempts):
            if self.child.tick(bb) == Status.FAILURE:
                return Status.FAILURE
        return Status.SUCCESS
    

class Action(BTNode):
    def __init__(self, fn: Callable[[Blackboard], Status], name: str = "") -> None:
        self.fn = fn
        self.name = name or getattr(fn, "__name__", "action")
        
    def tick(self, bb: Blackboard) -> Status:
        return self.fn(bb)
    

class Condition(BTNode):
    def __init__(self, fn: Callable[[Blackboard], bool], name: str = "") -> None:
        self.fn = fn
        self.name = name or getattr(fn, "__name__", "condition")

    def tick(self, bb: Blackboard) -> Status:
        return Status.SUCCESS if self.fn(bb) else Status.FAILURE
    

class BehaviourTree:
    def __init__(self, root: BTNode, blackboard: Blackboard) -> None:
        self.root = root
        self.blackboard = blackboard
    
    def tick(self) -> Status:
        return self.root.tick(self.blackboard)
    


_DATA_DIR = Path("server/data")


def _load_tree_defs(path: str = "server/data/behaviour_trees.yaml") -> Dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("trees", {})


class TreeRegistry:
    def __init__(
        self,
        tree_defs: Dict[str, dict],
        action_bindings: Dict[str, Callable[[Blackboard], Status]],
        condition_bindings: Dict[str, Callable[[Blackboard], bool]],
    ) -> None:
        self._defs = tree_defs
        self._actions = action_bindings
        self._conditions = condition_bindings
        self._root_cache: Dict[str, BTNode] = {} # Cache in case of a performance issue due to requiring of BTNode regen where it might strain NEST resource

    @classmethod
    def from_yaml(
        cls,
        path: str = "server/data/behavior_trees.yaml",
        action_bindings: Optional[Dict[str, Callable]] = None,
        condition_bindings: Optional[Dict[str. Callable]] = None,
    ) -> "TreeRegistry":
        defs = _load_tree_defs(path)
        return cls(
            defs,
            action_bindings or {},
            condition_bindings or {},
        )
    
    def tree_for(self, npc_id: str, archetype: str) -> BehaviorTree:
        if archetype not in self._root_cache:
            self._root_cache[archetype] = self._build_root(archetype)
        bb = Blackboard()
        bb.set("npc_id", npc_id)
        return BehaviourTree(self._root_cache[archetype], bb)
    
    def _build_root(self, archetype: str) -> BTNode:
        defn = self._defs.get(archetype)
        if not defn or "root" not in defn:
            return Action(lambda bb: Status.SUCCESS, name="idle")
        return self._parse_node(defn["root"])
    

    def _parse_node(self, node_def: Any) -> BTNode:
        if not isinstance(node_def, dict):
            if isinstance(node_def, str):
                return self._make_action(node_def)
            return Action(lambda bb: Status.SUCCESS, name="noop")
        
        if "selector" in node_def:
            return Selector([self._parse_node(c) for c in node_def["selector"]])
        if "sequence" in node_def:
            return Sequence([self._parse_node(c) for c in node_def["sequence"]])
        if "parallel" in node_def:
            children = [self._parse_node(c) for c in node_def["parallel"]]
            return Parallel(children, succeed_on_all=node_def.get("succeed_on_all", True))

        if "inverter" in node_def:
            return Inverter(self._parse_node(node_def["inverter"]))
        if "succeeder" in node_def:
            return Succeeder(self._parse_node(node_def["succeeder"]))
        if "repeat_until_fail" in node_def:
            child = self._parse_node(node_def["repeat_until_fail"])
            return RepeatUntilFail(child, max_attempts=node_def.get("max_attempts", 3))
        if "cooldown" in node_def:
            cd = node_def["cooldown"]
            child = self._parse_node(cd.get("child", {"action": "idle"}))
            return Cooldown(
                child=child,
                key=cd.get("key", "default_cooldown"),
                minutes=cd.get("minutes", 30),
            )
        
        if "condition" in node_def:
            return self._make_condition(node_def["condition"])
        if "action" in node_def:
            return self._make_action(node_def["action"])
        
        return Action(lambda bb: Status.SUCCESS, name="noop")
        
    def _make_action(self, name: str) -> Action:
        fn = self._actions.get(name)
        if fn:
            return Action(fn, name=name)
        return Action(lambda bb: Status.FAILURE, name=f"missing_action:{name}")
    
    def _make_condition(self, name: str) -> Condition:
        fn = self._conditions.get(name)
        if fn:
            return Condition(fn, name=name)
        return Condition(lambda bb: False, name=f"missing_cond:{name}")