from dataclasses import dataclass, field
from typing import List, Optional, Any, Tuple

@dataclass
class Program:
    stmts: List[Any]
    def __repr__(self): return f"Program({self.stmts})"

@dataclass
class LetStmt:
    name: str
    type_: Optional[Any]
    expr: Any
    def __repr__(self): return f"Let({self.name}, type={self.type_}, expr={self.expr})"

@dataclass
class AssignStmt:
    target: Any
    expr: Any
    def __repr__(self): return f"Assign({self.target} = {self.expr})"

@dataclass
class StructDecl:
    name: str
    fields: List[Any]
    def __repr__(self): return f"Struct({self.name}, fields={self.fields})"

@dataclass
class ForStmt:
    var: str
    iterable: Any
    block: List[Any]  # block 是语句列表
    is_range: bool = False
    range_end: Optional[Any] = None
    def __repr__(self):
        if self.is_range:
            return f"ForRange({self.var}, {self.iterable}..{self.range_end}, {self.block})"
        else:
            return f"ForEach({self.var} in {self.iterable}, {self.block})"

@dataclass
class WhileStmt:
    cond: Any
    block: List[Any]  # block 是语句列表
    def __repr__(self): return f"While({self.cond}, {self.block})"

@dataclass
class IfStmt:
    cond: Any
    then_block: List[Any]
    else_block: List[Any]
    def __repr__(self): return f"If({self.cond}, then={self.then_block}, else={self.else_block})"

@dataclass
class ExprStmt:
    expr: Any
    def __repr__(self): return f"ExprStmt({self.expr})"

@dataclass
class ReturnStmt:
    expr: Optional[Any]
    def __repr__(self): return f"Return({self.expr})"

@dataclass
class FuncDecl:
    name: str
    params: List[Tuple[str, Any]]
    ret_type: Optional[Any]
    body: List[Any]
    annotations: List[Any] = field(default_factory=list)
    def __repr__(self): return f"Func({self.name}, params={self.params}, ret={self.ret_type}, body={self.body})"

@dataclass
class CmdStmt:
    text: str
    def __repr__(self): return f"Cmd({self.text!r})"

# Expressions
@dataclass
class IntLiteral:
    value:int
    def __repr__(self): return f"Int({self.value})"

@dataclass
class FloatLiteral:
    value:float
    def __repr__(self): return f"Float({self.value})"

@dataclass
class BoolLiteral:
    value: bool
    def __repr__(self): return f"Bool({self.value})"

@dataclass
class StringLiteral:
    value:str
    def __repr__(self): return f"Str({self.value!r})"

@dataclass
class Ident:
    name:str
    def __repr__(self): return f"Ident({self.name})"

@dataclass
class ArrayLiteral:
    items:List[Any]
    def __repr__(self): return f"Array({self.items})"

@dataclass
class IndexExpr:
    base:Any
    index:Any
    def __repr__(self): return f"Index({self.base}[{self.index}])"

@dataclass
class ImportStmt:
    module: str  # 模块路径，如 "./math.mcc" 或 "std/math"
    names: Optional[List[str]]  # None表示导入全部，或指定名称列表如 ["sqrt", "abs"]
    alias: Optional[str] = None  # 命名空间别名（可选，用于 import * as math）

    def __repr__(self):
        if self.names:
            return f"Import({', '.join(self.names)} from '{self.module}')"
        return f"Import(* from '{self.module}')"

@dataclass
class SelectorExpr:
    raw:str
    def __repr__(self): return f"Selector({self.raw})"

@dataclass
class CallExpr:
    callee:Any
    args:List[Any]
    def __repr__(self): return f"Call({self.callee}({', '.join(map(str,self.args))}))"

@dataclass
class BinOp:
    op: str
    left: Any
    right: Any
    def __repr__(self): return f"BinOp({self.left} {self.op} {self.right})"

@dataclass
class TypeNode:
    base:str
    dims:List[Optional[int]] = None
    def __repr__(self):
        if not self.dims:
            return f"Type({self.base})"
        s = ''.join(f'[{("" if d is None else d)}]' for d in self.dims)
        return f"Type({self.base}{s})"

@dataclass
class StructLiteral:
    struct_name: str      # 如 "MobInfo"
    fields: List[Tuple[str, Any]]  # [(field_name, value_expr), ...]
    def __repr__(self):
        return f"StructLiteral({self.struct_name}, {self.fields})"

@dataclass
class ObjectLiteral:
    fields: List[Tuple[str, Any]]  # [(field_name, value_expr), ...]
    def __repr__(self):
        return f"ObjectLiteral({self.fields})"

@dataclass
class FieldAccess:
    base: Any       # 被访问的对象（可以是 Ident、FieldAccess、IndexExpr 等）
    field: str      # 字段名
    def __repr__(self):
        return f"FieldAccess({self.base}.{self.field})"

@dataclass
class UnaryOp:
    op: str           # '-' 或 '!'（以后可以支持逻辑非）
    operand: Any      # 操作数表达式
    def __repr__(self):
        return f"UnaryOp({self.op}{self.operand})"


@dataclass
class TagAnnot:
    """$tag("namespace:path")"""
    path: str

@dataclass
class TickAnnot:
    """$tick(interval)"""
    interval: int

@dataclass
class LootAnnot:
    """$loot("namespace:path")"""
    path: str

@dataclass
class EventAnnot:
    """$event("trigger", {conditions})"""
    trigger: str
    conditions: Any  # ObjectLiteral 或 None

@dataclass
class PredicateAnnot:
    """$predicate("namespace:path")"""
    path: str

# ========== 新增：静态标签声明 ==========
@dataclass
class StaticTagDecl:
    """$tag function("path") { "entries" }"""
    tag_type: str      # "function", "block", "item", "entity"
    path: str
    entries: List[str]
    replace: bool = False

# ========== 新增：Predicate 条件语句 ==========
@dataclass
class ConditionStmt:
    """condition { ... }"""
    clauses: List[Any]

@dataclass
class EntityCondition:
    """entity @s { nbt... }"""
    selector: Any      # SelectorExpr, Ident 或 StringLiteral
    nbt: Any           # ObjectLiteral

@dataclass
class LootConfigStmt:
    """loot "json_string" 语句（用于 $loot 函数体内）"""
    json_content: str
