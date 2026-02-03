import re
from typing import Dict

from ast_nodes import *
from my_types import *
from scope import ScopeManager

_selector_type_re = re.compile(r'type\s*=\s*([A-Za-z_]\w*)')


class SemanticError(Exception):
    pass


class ExpressionAnalyzer:
    """表达式分析 - 被 SemanticAnalyzer 组合使用"""

    def __init__(self, scope: ScopeManager, structs: Dict, entity_schema: Dict, funcs: Dict = None):
        self.scope = scope
        self.structs = structs
        self.entity_schema = entity_schema
        self.funcs = funcs if funcs is not None else {}

    def analyze(self, expr, is_assign_target: bool = False) -> TypeDesc:
        """表达式分析主入口"""
        method_name = f'_analyze_{expr.__class__.__name__}'
        method = getattr(self, method_name, self._analyze_generic)
        result = method(expr, is_assign_target)
        expr._type = result  # 保存类型到节点
        return result

    def _analyze_generic(self, expr, is_assign_target: bool) -> TypeDesc:
        raise SemanticError(f"未知的表达式类型: {type(expr)}")

    def _analyze_IntLiteral(self, expr: IntLiteral, _) -> TypeDesc:
        return INT

    def _analyze_FloatLiteral(self, expr: FloatLiteral, _) -> TypeDesc:
        return FLOAT

    def _analyze_struct_constructor(self, struct_name: str, obj_lit: ObjectLiteral, expr: CallExpr) -> TypeDesc:
        """分析结构体构造函数 MobInfo({...})"""
        struct_fields = self.structs[struct_name]
        provided = {fname: fexpr for fname, fexpr in obj_lit.fields}

        # 检查必需字段
        for fname, ftype in struct_fields.items():
            if fname not in provided:
                raise SemanticError(f"结构体 {struct_name} 缺少字段 '{fname}' 的初始化")

            fexpr = provided[fname]
            actual_type = self.analyze(fexpr)

            if not ftype.can_assign_from(actual_type):
                raise SemanticError(
                    f"结构体 {struct_name} 字段 '{fname}' 类型错误: 期望 {ftype}, 得到 {actual_type}"
                )

        # 检查多余字段
        for fname in provided:
            if fname not in struct_fields:
                raise SemanticError(f"结构体 {struct_name} 没有字段 '{fname}'")

        # 标记为结构体构造
        result_type = TypeDesc('struct', name=struct_name)
        expr._is_struct_constructor = True
        expr._struct_name = struct_name
        return result_type

    def _analyze_BoolLiteral(self, expr: BoolLiteral, _) -> TypeDesc:
        return BOOL

    def _analyze_StringLiteral(self, expr: StringLiteral, _) -> TypeDesc:
        return STRING

    def _analyze_Ident(self, expr: Ident, _) -> TypeDesc:
        t = self.scope.lookup(expr.name)
        if t is None:
            raise SemanticError(f"未定义的变量: {expr.name}")
        expr._storage_name = self.scope.get_storage_name(expr.name)
        return t

    def _analyze_UnaryOp(self, expr: UnaryOp, _) -> TypeDesc:
        operand_type = self.analyze(expr.operand)

        if expr.op == '-':
            if not operand_type.is_numeric():
                raise SemanticError(f"一元负号要求数字类型，得到 {operand_type}")
            return operand_type
        elif expr.op == '!':
            if operand_type != BOOL:
                raise SemanticError(f"逻辑非要求 bool 类型，得到 {operand_type}")
            return BOOL
        raise SemanticError(f"未知的一元操作符: {expr.op}")

    def _analyze_BinOp(self, expr: BinOp, _) -> TypeDesc:
        left_type = self.analyze(expr.left)
        right_type = self.analyze(expr.right)

        if expr.op in ('+', '-', '*', '/'):
            if not (left_type.is_numeric() and right_type.is_numeric()):
                raise SemanticError(f"算术运算需要数字类型")
            return FLOAT if (left_type == FLOAT or right_type == FLOAT) else INT

        elif expr.op in ('<', '>', '<=', '>=', '==', '!='):
            if not (left_type.is_numeric() and right_type.is_numeric()):
                raise SemanticError(f"比较运算需要数字类型")
            return BOOL

        raise SemanticError(f"未知运算符: {expr.op}")

    def _analyze_FieldAccess(self, expr: FieldAccess, _) -> TypeDesc:
        """分析点号访问 - 支持 struct.field 和 entity.field"""
        base_type = self.analyze(expr.base)

        # 数组长度语法糖
        if base_type.kind == 'array' and expr.field == 'length':
            expr._is_array_length = True
            return INT

        # 结构体字段
        if base_type.kind == 'struct':
            return self._analyze_struct_field(expr, base_type)

        # 实体属性
        if base_type.kind == 'entity':
            return self._analyze_entity_field(expr, base_type)

        raise SemanticError(f"类型 {base_type} 不支持字段访问 '.'")

    def _analyze_struct_field(self, expr: FieldAccess, struct_type: TypeDesc) -> TypeDesc:
        if struct_type.name not in self.structs:
            raise SemanticError(f"未知结构体类型: {struct_type.name}")

        fields = self.structs[struct_type.name]
        if expr.field not in fields:
            raise SemanticError(f"结构体 {struct_type.name} 没有字段 '{expr.field}'")

        result = fields[expr.field]
        expr._is_struct_field = True
        expr._field_name = expr.field
        return result

    def _analyze_entity_field(self, expr: FieldAccess, entity_type: TypeDesc) -> TypeDesc:
        subtype = entity_type.subtype or 'player'
        schema = self.entity_schema.get(subtype, {})

        if expr.field in schema:
            result = schema[expr.field]
        else:
            # 默认推断策略
            result = FLOAT if expr.field in ['Health'] else \
                STRING if expr.field in ['Name'] else \
                    BOOL if expr.field in ['OnGround'] else INT

        expr._is_entity_attr = True
        expr._entity_type = subtype
        expr._nbt_path = expr.field
        return result

    def _analyze_IndexExpr(self, expr: IndexExpr, is_assign_target: bool) -> TypeDesc:
        base_type = self.analyze(expr.base)
        index_type = self.analyze(expr.index)

        if base_type.kind == 'array':
            if index_type != INT:
                raise SemanticError(f"数组索引必须是整数类型")
            return base_type.elem or UNKNOWN

        if base_type.kind == 'entity':
            if index_type != STRING:
                raise SemanticError(f"实体属性索引必须是字符串")
            return INT  # 默认

        if base_type.kind == 'struct':
            if index_type != STRING:
                raise SemanticError(f"结构体字段索引必须是字符串")
            return UNKNOWN

        raise SemanticError(f"不能对类型 '{base_type}' 进行索引操作")

    def _analyze_SelectorExpr(self, expr: SelectorExpr, _) -> TypeDesc:
        """分析实体选择器 - 关键修复：limit=1 时视为单个实体"""
        match = _selector_type_re.search(expr.raw)
        if match:
            entity_type = match.group(1)
            t = TypeDesc('entity', subtype=entity_type) if entity_type in self.entity_schema else TypeDesc('entity')
        else:
            t = TypeDesc('entity')

        if 'limit=1' in expr.raw:
            expr._is_single_entity = True
            return t

        if expr.raw.startswith('@e') or expr.raw.startswith('@a'):
            t = TypeDesc('array', elem=t)

        expr._is_selector = True
        return t

    def _analyze_ArrayLiteral(self, expr: ArrayLiteral, _) -> TypeDesc:
        if not expr.items:
            return TypeDesc('array', elem=UNKNOWN)

        elem_types = [self.analyze(item) for item in expr.items]
        first_type = elem_types[0]

        for et in elem_types[1:]:
            if not first_type.equals(et):
                raise SemanticError(f"数组元素类型不一致")

        return TypeDesc('array', elem=first_type, shape=[len(expr.items)])

    def _analyze_ObjectLiteral(self, expr: ObjectLiteral, _) -> TypeDesc:
        for fname, fval in expr.fields:
            self.analyze(fval)
        return UNKNOWN

    def _analyze_CallExpr(self, expr: CallExpr, _) -> TypeDesc:
        """函数调用分析 - 修复循环导入"""
        if not isinstance(expr.callee, Ident):
            raise SemanticError("复杂的函数调用暂不支持")

        func_name = expr.callee.name

        # 1. 检查是否是结构体构造函数: StructName({...})
        if func_name in self.structs and len(expr.args) == 1 and isinstance(expr.args[0], ObjectLiteral):
            return self._analyze_struct_constructor(func_name, expr.args[0], expr)

        # 2. 检查是否是内置/普通函数
        if func_name not in self.funcs:
            raise SemanticError(f"未定义的函数: {func_name}")

        params, ret_type, _ = self.funcs[func_name]

        # 检查参数数量
        if len(expr.args) != len(params):
            raise SemanticError(
                f"函数 {func_name} 期望 {len(params)} 个参数，得到 {len(expr.args)}"
            )

        # 检查参数类型
        for i, (arg, (pname, ptype)) in enumerate(zip(expr.args, params)):
            arg_type = self.analyze(arg)
            if not ptype.can_assign_from(arg_type):
                raise SemanticError(
                    f"函数 {func_name} 第{i}个参数类型错误: 期望 {ptype}，得到 {arg_type}"
                )

        # 标记 AST 节点
        expr._func_name = func_name
        expr._ret_type = ret_type

        return ret_type if ret_type else VOID


class SemanticAnalyzer:
    """
    语义分析器主类
    对外API完全兼容旧版本
    """

    def __init__(self, entity_schema: Dict[str, Dict[str, TypeDesc]] = None):
        from entity_schema import DEFAULT_ENTITY_SCHEMA
        self.entity_schema = entity_schema or DEFAULT_ENTITY_SCHEMA
        self.scope = ScopeManager()
        self.structs: Dict[str, Dict[str, TypeDesc]] = {}
        self.funcs: Dict[str, Tuple[List[Tuple[str, TypeDesc]], Optional[TypeDesc], Any]] = {}

        self.current_function_ret: Optional[TypeDesc] = None
        self.current_function_name: Optional[str] = None

        # 关键修复：传入 self.funcs 作为第4个参数
        self.expr_analyzer = ExpressionAnalyzer(self.scope, self.structs, self.entity_schema, self.funcs)

        self._init_builtins()  # 这里添加的 len 才能被 expr_analyzer 识别

    def _init_builtins(self):
        arr_param = TypeDesc('array', elem=TypeDesc('unknown'))
        self.funcs['len'] = ([('arr', arr_param)], INT, None)

    def analyze(self, program: Program) -> Program:
        """
        主分析入口 - 对外API保持不变
        返回标注了类型的AST
        """
        self.scope.push('global')

        # 第一遍：收集结构体和函数签名
        self._collect_declarations(program)

        # 第二遍：完整分析
        for stmt in program.stmts:
            self._analyze_stmt(stmt)

        return program

    def _collect_declarations(self, program: Program):
        """收集所有声明"""
        for s in program.stmts:
            if isinstance(s, StructDecl):
                self._collect_struct(s)
            elif isinstance(s, FuncDecl):
                self._collect_func_signature(s)

    def _collect_struct(self, node: StructDecl):
        """收集结构体定义"""
        if node.name in self.structs:
            raise SemanticError(f"结构体 {node.name} 已定义")

        fields = {}
        for fname, ftype_node in node.fields:
            fields[fname] = self._type_from_typenode(ftype_node)
        self.structs[node.name] = fields

    def _collect_func_signature(self, node: FuncDecl):
        """收集函数签名"""
        if node.name in self.funcs:
            raise SemanticError(f"函数 {node.name} 已定义")

        param_list = []
        for pname, ptype_node in node.params:
            ptype = self._type_from_typenode(ptype_node)
            param_list.append((pname, ptype))

        ret = self._type_from_typenode(node.ret_type) if node.ret_type else None
        self.funcs[node.name] = (param_list, ret, node)

    def _type_from_typenode(self, tn) -> TypeDesc:
        """从 AST TypeNode 转换为 TypeDesc"""
        if tn is None:
            return VOID

        base = tn.base
        dims = tn.dims or []

        # 基础类型映射
        type_map = {
            'int': INT, 'string': STRING, 'bool': BOOL,
            'float': FLOAT, 'entity': TypeDesc('entity')
        }

        if base in type_map:
            base_t = type_map[base]
        else:
            base_t = TypeDesc('struct', name=base)

        if not dims:
            return base_t

        # 处理数组
        t = base_t
        for _ in dims:
            t = TypeDesc('array', elem=t)
        return t

    def _analyze_stmt(self, stmt):
        """语句分析分发"""
        method_name = f'_analyze_{stmt.__class__.__name__}'
        method = getattr(self, method_name, lambda x: None)
        method(stmt)

    def _analyze_LetStmt(self, node: LetStmt):
        """变量声明分析"""
        expr_type = self.expr_analyzer.analyze(node.expr)

        if node.type_:
            declared_type = self._type_from_typenode(node.type_)
            if not declared_type.can_assign_from(expr_type):
                raise SemanticError(f"类型错误: 不能用 {expr_type} 初始化 {declared_type}")
            final_type = declared_type
        else:
            final_type = expr_type

        # 数组长度变量特殊处理
        if final_type.kind == 'array':
            self.scope.declare(f"{node.name}_len", INT, is_reference=False)

        is_ref = final_type.is_reference_type()
        self.scope.declare(node.name, final_type, is_reference=is_ref)
        node._type = final_type

    def _analyze_AssignStmt(self, node: AssignStmt):
        """赋值语句分析"""
        target_type = self.expr_analyzer.analyze(node.target, is_assign_target=True)
        expr_type = self.expr_analyzer.analyze(node.expr)

        if not target_type.can_assign_from(expr_type):
            raise SemanticError(f"类型错误: 不能将 {expr_type} 赋值给 {target_type}")

    def _analyze_FuncDecl(self, node: FuncDecl):
        """函数定义分析"""
        self.current_function_name = node.name
        sig = self.funcs[node.name]
        params, ret_type, _ = sig
        self.current_function_ret = ret_type

        self.scope.push('func', parent_name=node.name)

        # 声明参数
        for pname, ptype in params:
            is_ref = ptype.is_reference_type()
            self.scope.declare(pname, ptype, is_param=True, is_reference=is_ref)

        # 分析函数体
        for s in node.body:
            self._analyze_stmt(s)

        self.scope.pop()
        self.current_function_name = None
        self.current_function_ret = None

    def _analyze_ReturnStmt(self, node: ReturnStmt):
        """Return 语句分析"""
        if node.expr:
            expr_type = self.expr_analyzer.analyze(node.expr)
            if self.current_function_ret:
                if not self.current_function_ret.can_assign_from(expr_type):
                    raise SemanticError(f"返回类型错误")

    def _analyze_ExprStmt(self, node: ExprStmt):
        """表达式语句分析"""
        self.expr_analyzer.analyze(node.expr)

    def _analyze_CmdStmt(self, node: CmdStmt):
        """Cmd 语句 - 无需类型检查"""
        pass

    def _analyze_ForStmt(self, node: ForStmt):
        """For 循环分析"""
        self.scope.push('block')

        if node.is_range:
            start_type = self.expr_analyzer.analyze(node.iterable)
            end_type = self.expr_analyzer.analyze(node.range_end)

            if not (start_type.is_numeric() and end_type.is_numeric()):
                raise SemanticError("Range 边界必须是数字类型")

            self.scope.declare(node.var, INT)
        else:
            iterable_type = self.expr_analyzer.analyze(node.iterable)
            if iterable_type.kind != 'array':
                raise SemanticError(f"For-in 需要数组类型")
            elem_type = iterable_type.elem or UNKNOWN
            self.scope.declare(node.var, elem_type)

        for s in node.block:
            self._analyze_stmt(s)

        self.scope.pop()

    def _analyze_WhileStmt(self, node: WhileStmt):
        """While 循环分析"""
        cond_type = self.expr_analyzer.analyze(node.cond)
        if cond_type != BOOL and not cond_type.is_numeric():
            raise SemanticError(f"While 条件必须是 bool 或 numeric")

        self.scope.push('block')
        for s in node.block:
            self._analyze_stmt(s)
        self.scope.pop()

    def _analyze_IfStmt(self, node: IfStmt):
        """If 语句分析"""
        cond_type = self.expr_analyzer.analyze(node.cond)
        if cond_type != BOOL and not cond_type.is_numeric():
            raise SemanticError(f"If 条件必须是 bool")

        self.scope.push('block')
        for s in node.then_block:
            self._analyze_stmt(s)
        self.scope.pop()

        if node.else_block:
            self.scope.push('block')
            for s in node.else_block:
                self._analyze_stmt(s)
            self.scope.pop()