"""
语义分析模块
"""



__all__ = [
    # 核心类
    'SemanticAnalyzer',
    'SemanticError',
    'TypeDesc',
    'ScopeInfo',
    'ScopeManager',

    # 常量
    'INT', 'STRING', 'BOOL', 'FLOAT', 'VOID', 'UNKNOWN',
    'DEFAULT_ENTITY_SCHEMA',

    # 工具函数
    'get_entity_schema',
    'print_ast',
    'ASTPrinter',
]

from analyzer import *
from entity_schema import *
from scope import ScopeInfo
from visitors import *
