from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional, Set, List

from my_types import TypeDesc


@dataclass
class ScopeInfo:
    """作用域信息，用于生成命名"""
    scope_type: str  # 'global', 'func', 'block'
    parent_name: str = ""
    block_id: Optional[int] = None
    declared_vars: Set[str] = field(default_factory=set)

    def get_full_prefix(self) -> str:
        """生成变量名前缀"""
        if self.scope_type == 'global':
            return ""
        elif self.scope_type == 'func':
            return f"{self.parent_name}_"
        elif self.scope_type == 'block':
            if self.block_id == 0:
                return f"{self.parent_name}_"
            else:
                return f"{self.parent_name}_blk{self.block_id}_"
        return ""


class ScopeManager:
    """作用域管理器 - 管理变量声明和查找"""

    def __init__(self):
        self.scopes: List[Dict[str, Tuple[TypeDesc, Dict]]] = []
        self.scope_infos: List[ScopeInfo] = []
        self.block_counter = 0
        self.current_function_name: Optional[str] = None

    def push(self, scope_type: str = 'block', parent_name: str = ""):
        """进入新作用域"""
        block_id = None
        if scope_type == 'block':
            block_id = self.block_counter
            self.block_counter += 1
        elif scope_type == 'func':
            parent_name = self.current_function_name or parent_name
            self.current_function_name = parent_name

        scope_info = ScopeInfo(scope_type, parent_name, block_id)
        self.scope_infos.append(scope_info)
        self.scopes.append({})

    def pop(self) -> ScopeInfo:
        """退出作用域"""
        self.scopes.pop()
        info = self.scope_infos.pop()
        if info.scope_type == 'func':
            self.current_function_name = None
        return info

    def declare(self, name: str, t: TypeDesc, is_param: bool = False, is_reference: bool = False):
        """声明变量"""
        if not self.scopes:
            self.push('global')

        meta = {
            'is_param': is_param,
            'is_reference': is_reference or t.is_reference_type(),
            'scope_info': self.scope_infos[-1],
        }
        self.scopes[-1][name] = (t, meta)
        self.scope_infos[-1].declared_vars.add(name)

    def lookup(self, name: str) -> Optional[TypeDesc]:
        """查找变量类型"""
        for scope in reversed(self.scopes):
            if name in scope:
                t, _ = scope[name]
                return t
        return None

    def lookup_with_meta(self, name: str) -> Optional[Tuple[TypeDesc, Dict]]:
        """查找变量类型和元数据"""
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def get_storage_name(self, name: str) -> str:
        """根据作用域规则生成变量存储名"""
        for i, scope in enumerate(reversed(self.scopes)):
            if name in scope:
                scope_idx = len(self.scopes) - 1 - i
                scope_info = self.scope_infos[scope_idx]
                return f"{scope_info.get_full_prefix()}{name}"
        return name

    def is_global(self) -> bool:
        """检查当前是否在全局作用域"""
        return len(self.scopes) <= 1