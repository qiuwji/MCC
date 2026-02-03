from typing import Dict, List, Optional, Any, Tuple

from my_types import UNKNOWN, TypeDesc


class GeneratorContext:
    """管理所有生成状态"""

    def __init__(self, namespace: str, structs: Dict):
        self.namespace = namespace
        self.structs = structs

        self.current_function: Optional[str] = None
        self.block_stack: List[int] = []
        self.block_counter = 0
        self.block_vars: Dict[int, List[str]] = {}

        self.var_map: Dict[str, Tuple[str, TypeDesc]] = {}
        self.funcs: Dict[str, Any] = {}
        self.array_lengths: Dict[str, int] = {}

        self.param_substitutions: Dict[str, str] = {}
        self.struct_params: Dict[str, str] = {}

        self.current_macro_args: Dict[str, str] = {}

        self.global_inits: List[str] = []
        self.tick_function: Optional[Any] = None
        self.current_mcfunc: Optional[Any] = None

        self.entity_tags: Dict[str, str] = {}
        self.entity_counter = 0

    def push_block(self) -> int:
        self.block_counter += 1
        self.block_stack.append(self.block_counter)
        self.block_vars[self.block_counter] = []
        return self.block_counter

    def get_storage_name(self, var_name: str, is_param: bool = False) -> str:
        if self.current_function is None:
            return var_name
        if is_param:
            return f"{self.current_function}_{var_name}"
        if self.block_stack:
            block_id = self.block_stack[-1]
            if block_id == 0:
                return f"{self.current_function}_{var_name}"
            return f"{self.current_function}_blk{block_id}_{var_name}"
        return f"{self.current_function}_{var_name}"

    def resolve_storage(self, storage: str) -> str:
        if self.current_function and self.struct_params:
            func_prefix = f"{self.current_function}_"
            for param_name, macro_name in self.struct_params.items():
                param_full_name = f"{func_prefix}{param_name}"
                if storage == param_full_name:
                    return macro_name
                if storage.startswith(param_full_name + "_"):
                    suffix = storage[len(param_full_name + "_"):]
                    return f"{macro_name}_{suffix}"
                for block_id in self.block_stack:
                    block_prefix = f"{func_prefix}blk{block_id}_{param_name}"
                    if storage == block_prefix:
                        return macro_name
                    if storage.startswith(block_prefix + "_"):
                        suffix = storage[len(block_prefix + "_"):]
                        return f"{macro_name}_{suffix}"
        if storage in self.param_substitutions:
            return self.param_substitutions[storage]
        for param_base, arg_base in self.param_substitutions.items():
            if storage.startswith(param_base + "_"):
                return arg_base + storage[len(param_base):]
        return storage

    def add_var(self, name: str, storage: str, type_: TypeDesc):
        self.var_map[name] = (storage, type_)
        if self.block_stack:
            current_block = self.block_stack[-1]
            if current_block not in self.block_vars:
                self.block_vars[current_block] = []
            self.block_vars[current_block].append(name)

    def get_var(self, name: str) -> Tuple[str, TypeDesc]:
        return self.var_map.get(name, (name, UNKNOWN))

    def allocate_entity_tag(self, var_name: str) -> str:
        """为实体变量分配唯一tag"""
        self.entity_counter += 1
        tag = f"__mcc_ent_{self.entity_counter}_{var_name}"
        self.entity_tags[var_name] = tag
        return tag

    def get_entity_tag(self, var_name: str) -> Optional[str]:
        """获取变量对应的实体tag"""
        return self.entity_tags.get(var_name)

    def pop_block(self) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """返回 (普通变量清理列表, 实体标签清理列表)"""
        if not self.block_stack:
            return [], []

        block_id = self.block_stack.pop()
        block_prefix = f"_blk{block_id}_"

        # 1. 普通变量清理（原有逻辑）
        vars_to_clean = []
        for var_name, (storage, var_type) in list(self.var_map.items()):
            if (block_prefix in storage and
                    var_type.kind not in ('array', 'struct', 'entity')):
                vars_to_clean.append((var_name, storage))

        # 2. 实体标签清理（关键修正）
        entities_to_clean = []
        # 检查当前块声明的变量中是否有实体
        if block_id in self.block_vars:
            for var_name in self.block_vars[block_id]:
                if var_name in self.entity_tags:  # 如果是实体变量
                    tag_name = self.entity_tags[var_name]
                    entities_to_clean.append((var_name, tag_name))
                    # 从全局跟踪中移除（避免重复清理）
                    del self.entity_tags[var_name]

            del self.block_vars[block_id]

        return vars_to_clean, entities_to_clean