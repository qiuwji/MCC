from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class MCFunction:
    """代表一个.mcfunction文件"""
    name: str
    commands: List[str] = field(default_factory=list)
    is_tick: bool = False
    is_load: bool = False

    def add(self, cmd: str):
        if cmd.strip():
            self.commands.append(cmd)

    def extend(self, cmds: List[str]):
        self.commands.extend([c for c in cmds if c.strip()])


class CommandBuilder:
    """Minecraft命令构建器"""

    def __init__(self, namespace: str = "mcc"):
        self.namespace = namespace
        self.functions: Dict[str, MCFunction] = {}
        self.objectives = set()  # 需要创建的scoreboard objectives
        self._func_counter = 0
        self._temp_counter = 0

    def new_function(self, name: str, is_tick: bool = False, is_load: bool = False) -> MCFunction:
        """创建新函数"""
        if name in self.functions:
            name = f"{name}_{self._func_counter}"
            self._func_counter += 1

        func = MCFunction(name, is_tick=is_tick, is_load=is_load)
        self.functions[name] = func
        return func

    def get_temp_var(self) -> str:
        """获取临时变量名"""
        name = f"_t{self._temp_counter}"
        self._temp_counter += 1
        return name

    def add_objective(self, obj: str):
        """添加需要初始化的objective"""
        self.objectives.add(obj)

    # ========== 基础命令构造 ==========

    def set_score(self, player: str, objective: str, value: int):
        """scoreboard players set"""
        return f"scoreboard players set {player} {objective} {value}"

    def op_score(self, op: str, target: str, target_obj: str, source: str, source_obj: str):
        """scoreboard players operation"""
        return f"scoreboard players operation {target} {target_obj} {op} {source} {source_obj}"

    def copy_score(self, target: str, source: str, objective: str = "_tmp"):
        """复制分数"""
        return self.op_score("=", target, objective, source, objective)

    def add_score(self, target: str, value: int, objective: str = "_tmp"):
        """增加分数"""
        return f"scoreboard players add {target} {objective} {value}"

    def remove_score(self, target: str, value: int, objective: str = "_tmp"):
        """减少分数"""
        return f"scoreboard players remove {target} {objective} {value}"

    def execute_if_score(self, player: str, objective: str, operator: str, value: Any, cmd: str):
        """execute if score ... run ..."""
        return f"execute if score {player} {objective} {operator} {value} run {cmd}"

    def execute_unless_score(self, player: str, objective: str, operator: str, value: Any, cmd: str):
        """execute unless score ... run ..."""
        return f"execute unless score {player} {objective} {operator} {value} run {cmd}"

    def execute_if_score_matches(self, player: str, objective: str, range_str: str, cmd: str):
        """execute if score ... matches ..."""
        return f"execute if score {player} {objective} matches {range_str} run {cmd}"

    def execute_as(self, selector: str, cmd: str):
        """execute as ... run ..."""
        return f"execute as {selector} run {cmd}"

    def execute_at(self, selector: str, cmd: str):
        """execute at ... run ..."""
        return f"execute at {selector} run {cmd}"

    def function_call(self, func_name: str, macro_args: Optional[Dict[str, str]] = None) -> str:
        """调用函数，支持宏"""
        if macro_args:
            args_str = "{" + ",".join(f'{k}:"{v}"' for k, v in macro_args.items()) + "}"
            return f"function {self.namespace}:{func_name} {args_str}"
        return f"function {self.namespace}:{func_name}"

    # ========== 数据存储命令 ==========

    def data_set_storage(self, storage_path: str, value: Any, type_hint: str = "int"):
        """data modify storage set value"""
        if isinstance(value, str):
            return f'data modify storage {self.namespace}:data {storage_path} set value "{value}"'
        return f"data modify storage {self.namespace}:data {storage_path} set value {value}"

    def data_get_storage(self, storage_path: str, scale: float = 1.0):
        """data get storage"""
        return f"data get storage {self.namespace}:data {storage_path} {scale}"

    def data_remove_storage(self, storage_path: str):
        """data remove storage"""
        return f"data remove storage {self.namespace}:data {storage_path}"

    def data_copy_storage(self, target_path: str, source_path: str):
        """复制 storage 路径的值：data modify storage target set from storage source"""
        return f"data modify storage {self.namespace}:data {target_path} set from storage {self.namespace}:data {source_path}"

    def store_result_score(self, player: str, objective: str, cmd: str, scale: float = 1.0):
        """execute store result score ... run ..."""
        return f"execute store result score {player} {objective} {cmd}"

    def store_success_score(self, player: str, objective: str, cmd: str):
        """execute store success score ... run ..."""
        return f"execute store success score {player} {objective} {cmd}"

    # ========== 特殊结构 ==========

    def generate_branch_tree(self,
                             selector_var: str,
                             selector_obj: str,
                             prefix: str,
                             max_index: int,
                             cases: List[tuple]) -> List[str]:
        """
        生成分支树（用于动态数组索引）
        prefix: 变量前缀（如 func_arr）
        cases: [(index, value_player)...] 或操作回调
        """
        cmds = []
        for i in range(min(max_index, 50)):  # 最大50，防止过大
            if i < len(cases):
                idx, val = cases[i]
                cmd = self.copy_score(f"{prefix}_{i}", val)
                cmds.append(self.execute_if_score_matches(selector_var, selector_obj, str(i), cmd))
        return cmds

    def generate_init_commands(self) -> List[str]:
        """生成初始化命令（load函数用）"""
        cmds = [f"scoreboard objectives add {obj} dummy" for obj in self.objectives]
        # 默认添加 _tmp
        if "_tmp" not in self.objectives:
            cmds.insert(0, "scoreboard objectives add _tmp dummy")
        return cmds