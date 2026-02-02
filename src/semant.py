import warnings

from my_types import *

warnings.warn(
    "直接导入 semant 已弃用，请改为 from semant import SemanticAnalyzer",
    DeprecationWarning,
    stacklevel=2
)

# 从新模块重新导出所有内容，保持 API 完全兼容
from scope import ScopeInfo, ScopeManager
from analyzer import SemanticAnalyzer, SemanticError
from entity_schema import DEFAULT_ENTITY_SCHEMA, get_entity_schema
from visitors import print_ast, ASTPrinter

__all__ = [
    'SemanticAnalyzer', 'SemanticError', 'TypeDesc',
    'INT', 'STRING', 'BOOL', 'FLOAT', 'VOID', 'UNKNOWN',
    'ScopeInfo', 'ScopeManager', 'DEFAULT_ENTITY_SCHEMA',
    'get_entity_schema', 'print_ast', 'ASTPrinter'
]
