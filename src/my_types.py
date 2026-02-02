from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TypeDesc:
    """
    类型描述符：
    - kind: 'prim', 'array', 'entity', 'struct', 'void', 'unknown'
    - name: 对于 'prim' 是 'int'/'string'/'bool'/'float'
    - elem: 对于 'array' 是元素类型
    - subtype: 对于 'entity' 是具体实体类型如 'player'
    - shape: 数组形状
    """
    kind: str
    name: Optional[str] = None
    elem: Optional['TypeDesc'] = None
    subtype: Optional[str] = None
    shape: Optional[List[int]] = None

    def __post_init__(self):
        if self.shape is None:
            self.shape = []

    def __repr__(self):
        if self.kind == 'prim':
            return self.name or 'unknown'
        if self.kind == 'array':
            if self.elem:
                return f"{self.elem}[]"
            return "array[]"
        if self.kind == 'entity':
            return f"entity({self.subtype})" if self.subtype else "entity"
        if self.kind == 'struct':
            return f"struct<{self.name}>"
        if self.kind == 'void':
            return "void"
        if self.kind == 'unknown':
            return "unknown"
        return f"{self.kind}"

    def is_numeric(self) -> bool:
        return self.kind == 'prim' and self.name in ('int', 'float')

    def is_reference_type(self) -> bool:
        return self.kind in ('array', 'struct', 'entity')

    def is_value_type(self) -> bool:
        return self.kind == 'prim'

    def equals(self, other: 'TypeDesc') -> bool:
        if other is None:
            return False
        if self.kind != other.kind:
            return False
        if self.kind == 'prim':
            return self.name == other.name
        if self.kind == 'array':
            if not self.elem or not other.elem:
                return True
            return self.elem.equals(other.elem) and self.shape == other.shape
        if self.kind == 'entity':
            if self.subtype is None or other.subtype is None:
                return True
            return self.subtype == other.subtype
        if self.kind == 'struct':
            return self.name == other.name
        if self.kind == 'void':
            return True
        if self.kind == 'unknown':
            return True
        return False

    def can_assign_from(self, src: 'TypeDesc') -> bool:
        """检查是否可以用 src 类型赋值给 self 类型"""
        if src is None:
            return False
        if self.kind == 'unknown' or src.kind == 'unknown':
            return True
        if self.equals(src):
            return True
        # 数组类型兼容性
        if self.kind == 'array' and src.kind == 'array':
            if src.elem.kind == 'unknown':
                return True
            if self.elem.kind == 'unknown':
                return True
            if self.elem.can_assign_from(src.elem):
                if not self.shape or all(d is None for d in self.shape):
                    return True
                if not src.shape:
                    return False
                for s_dim, t_dim in zip(src.shape, self.shape):
                    if t_dim is not None and s_dim != t_dim:
                        return False
                return True
            return False
        # int -> float
        if self.kind == 'prim' and self.name == 'float' and src.kind == 'prim' and src.name == 'int':
            return True
        # entity 子类型兼容
        if self.kind == 'entity' and src.kind == 'entity':
            if self.subtype is None or src.subtype is None or self.subtype == src.subtype:
                return True
        return False


# 基础类型常量
INT = TypeDesc('prim', 'int')
STRING = TypeDesc('prim', 'string')
BOOL = TypeDesc('prim', 'bool')
FLOAT = TypeDesc('prim', 'float')
VOID = TypeDesc('void')
UNKNOWN = TypeDesc('unknown')