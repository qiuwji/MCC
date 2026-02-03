from ast_nodes import *
from command_builder import CommandBuilder
from context import GeneratorContext
from my_types import *


class ExprGenerator:
    def __init__(self, ctx: GeneratorContext, builder: CommandBuilder, stmt_gen=None):
        self.ctx = ctx
        self.builder = builder
        self.stmt_gen = stmt_gen
        # 延迟导入避免循环依赖
        from struct_generator import StructGenerator
        from entity_generator import EntityGenerator
        self.struct_gen = StructGenerator(ctx, builder)
        self.entity_gen = EntityGenerator(ctx, builder)
        self.max_array_index = 50

    def gen_expr_to(self, expr: Any, target_var: str, target_type: TypeDesc = None) -> List[str]:
        """生成表达式计算命令，结果存入 target_var"""

        # 获取表达式实际类型（如果未提供目标类型）
        expr_type = getattr(expr, '_type', None)

        if isinstance(expr, IntLiteral):
            # 如果目标类型是 float，直接存储 ×100 的值
            if target_type and target_type.name == 'float':
                return [self.builder.set_score(target_var, "_tmp", expr.value * 100)]
            return [self.builder.set_score(target_var, "_tmp", expr.value)]

        elif isinstance(expr, FloatLiteral):
            return [self.builder.set_score(target_var, "_tmp", int(expr.value * 100))]

        elif isinstance(expr, BoolLiteral):
            return [self.builder.set_score(target_var, "_tmp", 1 if expr.value else 0)]

        elif isinstance(expr, StringLiteral):
            return [self.builder.data_set_storage(target_var, expr.value)]

        elif isinstance(expr, UnaryOp):
            return self._gen_unary(expr, target_var, target_type)

        elif isinstance(expr, Ident):
            return self._gen_ident(expr, target_var, target_type)

        elif isinstance(expr, BinOp):
            return self._gen_binop(expr, target_var)

        elif isinstance(expr, CallExpr):
            return self._gen_call(expr, target_var)

        elif isinstance(expr, IndexExpr):
            return self._gen_index(expr, target_var)

        elif isinstance(expr, SelectorExpr):
            return []

        elif isinstance(expr, FieldAccess):
            return self._gen_field_access(expr, target_var, target_type)

        elif isinstance(expr, ArrayLiteral):
            return [self.builder.set_score(target_var, "_tmp", len(expr.items))]

        elif isinstance(expr, (StructLiteral, ObjectLiteral)):
            struct_type = getattr(expr, '_type', None)
            if struct_type and struct_type.kind == 'struct':
                return self.struct_gen.gen_struct_init(expr, target_var, struct_type.name)
            return []

        return []

    def _gen_ident(self, expr: Ident, target_var: str, target_type: TypeDesc = None) -> List[str]:
        storage, var_type = self.ctx.get_var(expr.name)
        resolved = self.ctx.resolve_storage(storage)

        cmds = []

        if var_type.kind == 'struct':
            return self.struct_gen.gen_struct_copy(target_var, resolved, var_type.name)
        elif var_type.kind == 'prim' and var_type.name == 'string':
            return [self.builder.data_copy_storage(target_var, resolved)]
        else:
            # 数值类型：scoreboard 复制
            cmds.append(self.builder.copy_score(target_var, resolved))

            if (target_type and target_type.kind == 'prim' and
                    target_type.name == 'float' and var_type.kind == 'prim' and
                    var_type.name == 'int'):
                cmds.append(f"scoreboard players operation {target_var} _tmp *= _const100 _tmp")

            return cmds

    def _gen_unary(self, expr: UnaryOp, target_var: str, target_type: TypeDesc = None) -> List[str]:
        """生成一元操作符代码"""
        cmds = []

        # 先计算操作数到临时变量
        operand_temp = self.builder.get_temp_var()
        cmds.extend(self.gen_expr_to(expr.operand, operand_temp, target_type))

        if expr.op == '-':
            # 实现：0 - operand
            # 先设目标为 0
            cmds.append(self.builder.set_score(target_var, "_tmp", 0))
            # 然后减去操作数：target = 0 - operand
            cmds.append(
                f"scoreboard players operation {target_var} _tmp -= {operand_temp} _tmp"
            )

        elif expr.op == '!':
            # 逻辑非：如果 operand 是 0 则结果为 1，否则为 0
            # 实现：result = 1; if operand != 0 then result = 0
            cmds.append(self.builder.set_score(target_var, "_tmp", 1))
            cmds.append(
                f"execute if score {operand_temp} _tmp matches 1.. run "
                f"scoreboard players set {target_var} _tmp 0"
            )
            cmds.append(
                f"execute if score {operand_temp} _tmp matches ..-1 run "
                f"scoreboard players set {target_var} _tmp 0"
            )

        return cmds

    def _gen_binop(self, expr: BinOp, target_var: str) -> List[str]:
        """生成二元运算代码 - 支持 AND、==、!=、比较和算术运算"""

        # 处理逻辑与运算 AND（短路求值）
        if expr.op == 'and':
            return self._gen_and_op(expr, target_var)

        # 处理相等和不等（支持 bool 和数字类型）
        if expr.op in ('==', '!='):
            return self._gen_equality_op(expr, target_var)

        # 处理其他运算（原有逻辑）
        cmds = []
        left = self.builder.get_temp_var()
        right = self.builder.get_temp_var()

        # 推断操作数类型
        from semant import INT, FLOAT, BOOL
        left_type = self._infer_expr_type(expr.left)
        right_type = self._infer_expr_type(expr.right)

        # 如果一边是 float，另一边 int 需要转为 float（自动×100）
        left_target = FLOAT if (left_type == INT and right_type == FLOAT) else left_type
        right_target = FLOAT if (right_type == INT and left_type == FLOAT) else right_type

        cmds.extend(self.gen_expr_to(expr.left, left, left_target))
        cmds.extend(self.gen_expr_to(expr.right, right, right_target))

        cmds.append(self.builder.copy_score(target_var, left))

        if expr.op in ('<', '>', '<=', '>='):
            op_map = {'<': '<', '>': '>', '<=': '<=', '>=': '>='}
            op = op_map[expr.op]
            cmds.append(f"execute if score {left} _tmp {op} {right} _tmp run "
                        f"scoreboard players set {target_var} _tmp 1")
            cmds.append(f"execute unless score {left} _tmp {op} {right} _tmp run "
                        f"scoreboard players set {target_var} _tmp 0")
        else:
            op_map = {'+': '+=', '-': '-=', '*': '*=', '/': '/=', '%': '%='}
            if expr.op == '*':
                cmds.append(f"scoreboard players operation {target_var} _tmp *= {right} _tmp")
                if left_type == FLOAT or right_type == FLOAT:
                    cmds.append(f"scoreboard players operation {target_var} _tmp /= _const100 _tmp")
            elif expr.op == '/':
                if left_type == FLOAT or right_type == FLOAT:
                    cmds.append(f"scoreboard players operation {target_var} _tmp *= _const100 _tmp")
                cmds.append(f"scoreboard players operation {target_var} _tmp /= {right} _tmp")
            elif expr.op == '%':
                cmds.append(f"scoreboard players operation {target_var} _tmp %= {right} _tmp")
            else:
                # + 和 - 不需要特殊处理
                cmds.append(self.builder.op_score(op_map[expr.op], target_var, "_tmp", right, "_tmp"))

        return cmds

    def _gen_and_op(self, expr: BinOp, target_var: str) -> List[str]:
        """生成逻辑与 AND 运算（短路求值）"""
        cmds = []
        left_temp = self.builder.get_temp_var()

        # 生成左操作数
        cmds.extend(self.gen_expr_to(expr.left, left_temp))

        # 默认结果为 0（假）
        cmds.append(self.builder.set_score(target_var, "_tmp", 0))

        # 计算右操作数（只有在左为真时才会执行结果赋值）
        right_temp = self.builder.get_temp_var()
        right_cmds = self.gen_expr_to(expr.right, right_temp)

        # 将右操作数计算包装在 execute if score left matches 1.. run 中
        for cmd in right_cmds:
            wrapped_cmd = f"execute if score {left_temp} _tmp matches 1.. run {cmd}"
            cmds.append(wrapped_cmd)

        # 如果左边为真，将右边结果复制到目标
        copy_cmd = self.builder.copy_score(target_var, right_temp)
        wrapped_copy = f"execute if score {left_temp} _tmp matches 1.. run {copy_cmd}"
        cmds.append(wrapped_copy)

        return cmds

    def _gen_equality_op(self, expr: BinOp, target_var: str) -> List[str]:
        """生成相等 == 和不等 != 运算（支持 bool 和数字）"""
        cmds = []
        left = self.builder.get_temp_var()
        right = self.builder.get_temp_var()

        # 生成两边操作数（bool 也是用 0/1 存储的 scoreboard）
        cmds.extend(self.gen_expr_to(expr.left, left))
        cmds.extend(self.gen_expr_to(expr.right, right))

        if expr.op == '==':
            # 相等：先设为0，如果相等设为1
            cmds.append(self.builder.set_score(target_var, "_tmp", 0))
            cmds.append(f"execute if score {left} _tmp = {right} _tmp run "
                        f"scoreboard players set {target_var} _tmp 1")
        else:  # '!='
            # 不等：先设为1，如果相等设为0
            cmds.append(self.builder.set_score(target_var, "_tmp", 1))
            cmds.append(f"execute if score {left} _tmp = {right} _tmp run "
                        f"scoreboard players set {target_var} _tmp 0")

        return cmds

    def _infer_expr_type(self, expr) -> 'TypeDesc':
        """简单类型推断，用于 binop"""
        from semant import INT, FLOAT, BOOL, STRING, UNKNOWN
        if isinstance(expr, IntLiteral):
            return INT
        elif isinstance(expr, FloatLiteral):
            return FLOAT
        elif isinstance(expr, BoolLiteral):
            return BOOL
        elif isinstance(expr, StringLiteral):
            return STRING
        elif isinstance(expr, Ident):
            _, t = self.ctx.get_var(expr.name)
            return t
        elif isinstance(expr, BinOp):
            left = self._infer_expr_type(expr.left)
            right = self._infer_expr_type(expr.right)
            if left == FLOAT or right == FLOAT:
                return FLOAT
            return left
        return UNKNOWN

    def _gen_call(self, expr: CallExpr, target_var: Optional[str]) -> List[str]:
        func_name = getattr(expr, '_func_name',
                            expr.callee.name if isinstance(expr.callee, Ident) else 'unknown')

        if getattr(expr, '_is_struct_constructor', False):
            struct_name = getattr(expr, '_struct_name')
            return self.struct_gen.gen_struct_init(expr.args[0], target_var, struct_name)

        if func_name == 'len':
            return self._gen_len(expr, target_var)

        return self._gen_func_call(expr, target_var)

    def _gen_func_call(self, expr: CallExpr, target_var: Optional[str]) -> List[str]:
        func_info = self.ctx.funcs.get(expr.callee.name)
        if not func_info:
            return []

        params, ret_type, _ = func_info
        cmds = []
        macro_args = {}
        entity_selector = None
        func_name = expr.callee.name  # 被调用的函数名

        for (pname, ptype), arg in zip(params, expr.args):
            if ptype.kind == 'entity':
                selector = self._extract_selector(arg)
                if selector:
                    entity_selector = selector
                continue

            if ptype.kind == 'prim' and ptype.name == 'string':
                # 字符串参数：通过宏传递 storage 路径
                if isinstance(arg, Ident):
                    arg_storage, _ = self.ctx.get_var(arg.name)
                    resolved = self.ctx.resolve_storage(arg_storage)
                    macro_args[pname] = resolved
                elif isinstance(arg, StringLiteral):
                    # 字面量：存入临时路径后传递
                    temp_path = f"__str_arg_{self.builder.get_temp_var()}"
                    cmds.append(self.builder.data_set_storage(temp_path, arg.value))
                    macro_args[pname] = temp_path
                else:
                    # 复杂表达式：求值到临时路径
                    temp_path = f"__str_arg_{self.builder.get_temp_var()}"
                    cmds.extend(self.gen_expr_to(arg, temp_path))
                    macro_args[pname] = temp_path

            elif ptype.kind == 'struct':
                if isinstance(arg, Ident):
                    arg_storage, _ = self.ctx.get_var(arg.name)
                    resolved = self.ctx.resolve_storage(arg_storage)
                    macro_args[pname] = resolved

            elif ptype.kind == 'array':
                if isinstance(arg, Ident):
                    arg_storage, _ = self.ctx.get_var(arg.name)
                    resolved = self.ctx.resolve_storage(arg_storage)
                    macro_args[pname] = resolved
                elif isinstance(arg, ArrayLiteral):
                    # 字面量数组：需要初始化到临时 storage 再传递
                    temp_arr = f"__arr_arg_{self.builder.get_temp_var()}"
                    macro_args[pname] = temp_arr

            else:
                param_storage = f"{func_name}_{pname}"

                if isinstance(arg, Ident):
                    arg_storage = self.ctx.get_var(arg.name)[0]
                    # 传递 ptype 作为目标类型，以触发 int->float 转换
                    arg_cmds = self.gen_expr_to(arg, param_storage, ptype)
                    cmds.extend(arg_cmds)
                else:
                    # 非标识符表达式，直接生成，传递目标类型
                    arg_cmds = self.gen_expr_to(arg, param_storage, ptype)
                    cmds.extend(arg_cmds)

        func_cmd = self.builder.function_call(f"fn_{expr.callee.name}",
                                              macro_args if macro_args else None)
        if entity_selector:
            func_cmd = f"execute as {entity_selector} run {func_cmd}"
        cmds.append(func_cmd)

        if target_var and ret_type:
            ret_var = f"_ret_{expr.callee.name}"
            if ret_type.kind == 'struct':
                cmds.extend(self.struct_gen.gen_struct_copy(target_var, ret_var, ret_type.name))
            elif ret_type.kind == 'prim' and ret_type.name == 'string':
                # 字符串返回值：从函数的返回值 storage 路径复制
                cmds.append(self.builder.data_copy_storage(target_var, ret_var))
            else:
                cmds.append(self.builder.copy_score(target_var, ret_var))

        return cmds

    def _extract_selector(self, arg) -> Optional[str]:
        if isinstance(arg, SelectorExpr):
            return arg.raw
        elif isinstance(arg, Ident):
            storage, _ = self.ctx.get_var(arg.name)
            if isinstance(storage, str) and storage.startswith('@'):
                return storage
        return None

    def _gen_len(self, expr: CallExpr, target_var: Optional[str]) -> List[str]:
        """生成 len(arr) 代码 - 主入口，负责分发到具体处理器"""
        if not self._validate_len_args(expr, target_var):
            return []

        arr_expr = expr.args[0]

        if isinstance(arr_expr, Ident):
            return self._gen_len_for_ident(arr_expr, target_var)
        elif isinstance(arr_expr, IndexExpr):
            return self._gen_len_for_index_expr(arr_expr, target_var)

        return []

    def _validate_len_args(self, expr: CallExpr, target_var: Optional[str]) -> bool:
        """验证 len() 调用参数是否合法"""
        return bool(expr.args and target_var)

    def _gen_len_for_ident(self, arr_expr: Ident, target_var: str) -> List[str]:
        storage, _ = self.ctx.get_var(arr_expr.name)
        resolved = self.ctx.resolve_storage(storage)

        # 必须这样（没有 []）：
        return [
            f'execute store result score {target_var} _tmp run '
            f'data get storage {self.ctx.namespace}:data {resolved}'
        ]

    def _gen_len_for_index_expr(self, arr_expr: IndexExpr, target_var: str) -> List[str]:
        arr_path = self._extract_array_path_from_index_expr(arr_expr)
        if not arr_path:
            return []

        # 必须这样（没有 []）：
        return [
            f'execute store result score {target_var} _tmp run '
            f'data get storage {self.ctx.namespace}:data {arr_path}'
        ]

    def _extract_array_path_from_index_expr(self, arr_expr: IndexExpr) -> Optional[str]:
        """从索引表达式中提取数组的 storage 路径"""
        # 只处理 base 为 Ident 的简单情况（如 arr[0].field）
        if not isinstance(arr_expr.base, Ident):
            return None

        if not isinstance(arr_expr.index, (Ident, StringLiteral)):
            return None

        base_storage = self.ctx.get_var(arr_expr.base.name)[0]
        base_storage = self.ctx.resolve_storage(base_storage)

        field_name = (
            arr_expr.index.name
            if isinstance(arr_expr.index, Ident)
            else arr_expr.index.value
        )

        return f"{base_storage}_{field_name}"

    def _gen_index(self, expr: IndexExpr, target_var: str) -> List[str]:
        base_type = getattr(expr.base, '_type', UNKNOWN)

        # 处理嵌套索引（如 arr[field][index]）
        if isinstance(expr.base, IndexExpr):
            inner_base = expr.base.base
            field_expr = expr.base.index
            if isinstance(inner_base, Ident):
                base_storage, _ = self.ctx.get_var(inner_base.name)
                base_storage = self.ctx.resolve_storage(base_storage)
                if isinstance(field_expr, (Ident, StringLiteral)):
                    field_name = field_expr.name if isinstance(field_expr, Ident) else field_expr.value
                    arr_base = f"{base_storage}_{field_name}"
                    actual_arr = self.ctx.resolve_storage(arr_base)
                    if isinstance(expr.index, IntLiteral):
                        idx = expr.index.value
                        return [self.builder.copy_score(target_var, f"{actual_arr}_{idx}")]

                    cmds = []
                    idx_temp = self.builder.get_temp_var()
                    cmds.extend(self.gen_expr_to(expr.index, idx_temp))
                    upper_bound = min(self.ctx.array_lengths.get(actual_arr, self.max_array_index),
                                      self.max_array_index)
                    for i in range(upper_bound):
                        store_cmd = self.builder.copy_score(f"{actual_arr}_{i}", target_var)
                        branch = self.builder.execute_if_score_matches(idx_temp, "_tmp", str(i), store_cmd)
                        cmds.append(branch)
                    return cmds

        # ========== 关键修复：支持 FieldAccess（如 game.board） ==========
        if isinstance(expr.base, FieldAccess):
            # 使用 _get_storage_path 获取完整路径（如 game_board）
            base_path = self._get_storage_path(expr.base)
            if base_path:
                arr_path = self.ctx.resolve_storage(base_path)
                elem_type = base_type.elem if base_type and base_type.kind == 'array' else UNKNOWN
                return self._gen_array_index_impl(expr, target_var, arr_path, elem_type)
            return []

        if base_type.kind == 'array':
            return self._gen_array_index(expr, target_var, base_type)

        if base_type.kind == 'struct':
            if isinstance(expr.base, Ident):
                base_storage, _ = self.ctx.get_var(expr.base.name)
                base_storage = self.ctx.resolve_storage(base_storage)
                if isinstance(expr.index, (Ident, StringLiteral)):
                    field_name = expr.index.name if isinstance(expr.index, Ident) else expr.index.value
                    field_path = f"{base_storage}_{field_name}"

                    # 检查字段类型是否为字符串
                    if isinstance(expr.base, Ident):
                        base_name = expr.base.name
                        base_var_type = self.ctx.get_var(base_name)[1]
                        if base_var_type.kind == 'struct' and base_var_type.name in self.ctx.structs:
                            struct_fields = self.ctx.structs[base_var_type.name]
                            if field_name in struct_fields:
                                field_type = struct_fields[field_name]
                                if field_type.kind == 'prim' and field_type.name == 'string':
                                    return [self.builder.data_copy_storage(target_var, field_path)]

                    return [self.builder.copy_score(target_var, field_path)]

        if base_type.kind == 'entity':
            if isinstance(expr.base, Ident):
                selector = self.entity_gen.get_entity_selector(expr.base.name) or "@s"
                if isinstance(expr.index, (Ident, StringLiteral)):
                    field_name = expr.index.name if isinstance(expr.index, Ident) else expr.index.value
                    return self.entity_gen.gen_entity_read(expr, target_var, selector, field_name)

        return []

    def _gen_array_index(self, expr: IndexExpr, target_var: str, arr_type: TypeDesc) -> List[str]:
        """处理数组索引 - 现在支持 Ident 和 FieldAccess"""
        # 获取数组 storage 路径（支持 game.board 这种 FieldAccess）
        if isinstance(expr.base, Ident):
            arr_storage, _ = self.ctx.get_var(expr.base.name)
            arr_path = self.ctx.resolve_storage(arr_storage)
        elif isinstance(expr.base, FieldAccess):
            arr_path = self._get_storage_path(expr.base)
            arr_path = self.ctx.resolve_storage(arr_path) if arr_path else None
        else:
            return []

        if not arr_path:
            return []

        elem_type = arr_type.elem if arr_type.elem else UNKNOWN
        return self._gen_array_index_impl(expr, target_var, arr_path, elem_type)

    def _gen_array_index_impl(self, expr: IndexExpr, target_var: str, arr_path: str, elem_type: TypeDesc) -> List[str]:
        """数组索引生成的具体实现"""
        cmds = []

        if isinstance(expr.index, IntLiteral):
            # 编译期常量索引
            idx = expr.index.value

            if elem_type.kind == 'struct':
                # 结构体数组元素复制
                fields = self.ctx.structs.get(elem_type.name, {})
                for fname, ftype in fields.items():
                    src = f"{arr_path}[{idx}].{fname}"
                    dst = f"{target_var}_{fname}"
                    if ftype.kind == 'prim' and ftype.name == 'string':
                        cmds.append(self.builder.data_copy_storage(dst, src))
                    elif ftype.is_value_type():
                        type_str = "int" if ftype.name == 'int' else "double"
                        scale = 1 if ftype.name == 'int' else 0.01
                        cmds.append(
                            f'execute store result score {dst} _tmp run data get storage {self.ctx.namespace}:data {src} {scale}')
            elif elem_type.kind == 'prim' and elem_type.name == 'string':
                # 字符串数组
                src = f"{arr_path}[{idx}]"
                cmds.append(self.builder.data_copy_storage(target_var, src))
            else:
                # 基础数值类型
                scale = 1 if elem_type.name == 'int' else 0.01
                cmds.append(
                    f'execute store result score {target_var} _tmp run data get storage {self.ctx.namespace}:data {arr_path}[{idx}] {scale}')
        else:
            # 运行期动态索引（使用宏命令）
            idx_temp = self.builder.get_temp_var()
            cmds.extend(self.gen_expr_to(expr.index, idx_temp))
            cmds.append(
                f'execute store result storage {self.ctx.namespace}:data __args.index int 1 run scoreboard players get {idx_temp} _tmp')

            if arr_path.startswith('$'):
                cmds.append(f'$data modify storage {self.ctx.namespace}:data __args.path set value {arr_path}')
            else:
                cmds.append(f'data modify storage {self.ctx.namespace}:data __args.path set value "{arr_path}"')

            if elem_type.kind == 'struct':
                fields = self.ctx.structs.get(elem_type.name, {})
                for fname, ftype in fields.items():
                    cmds.append(f'data modify storage {self.ctx.namespace}:data __args.field set value "{fname}"')
                    cmds.append(
                        f'data modify storage {self.ctx.namespace}:data __args.target set value "{target_var}_{fname}"')

                    if ftype.kind == 'prim' and ftype.name == 'string':
                        cmds.append(
                            f'function {self.ctx.namespace}:__array_copy_field with storage {self.ctx.namespace}:data __args')
                    elif ftype.is_value_type():
                        type_str = "int" if ftype.name == 'int' else "double"
                        cmds.append(f'data modify storage {self.ctx.namespace}:data __args.type set value "{type_str}"')
                        cmds.append(
                            f'function {self.ctx.namespace}:__array_get_field with storage {self.ctx.namespace}:data __args')
            elif elem_type.kind == 'prim' and elem_type.name == 'string':
                cmds.append(f'data modify storage {self.ctx.namespace}:data __args.target set value "{target_var}"')
                cmds.append(
                    f'function {self.ctx.namespace}:__array_get_string with storage {self.ctx.namespace}:data __args')
            else:
                type_str = "int" if elem_type.name == 'int' else "double"
                cmds.append(f'data modify storage {self.ctx.namespace}:data __args.target set value "{target_var}"')
                cmds.append(f'data modify storage {self.ctx.namespace}:data __args.type set value "{type_str}"')
                cmds.append(f'function {self.ctx.namespace}:__array_get with storage {self.ctx.namespace}:data __args')

        return cmds

    def _gen_field_access(self, expr: FieldAccess, target_var: str, target_type: TypeDesc = None) -> List[str]:
        """生成点号访问代码"""

        # 情况1：数组长度语法糖 arr.length
        if getattr(expr, '_is_array_length', False):
            base_name = self._get_base_name(expr.base)
            if base_name:
                storage, _ = self.ctx.get_var(base_name)
                resolved = self.ctx.resolve_storage(storage)
                # Bug修复：使用 [] 获取列表长度
                return [
                    f'execute store result score {target_var} _tmp run data get storage {self.ctx.namespace}:data {resolved}'
                ]
            return []

        # 情况2：结构体字段
        if getattr(expr, '_is_struct_field', False):
            base_storage = self._get_storage_path(expr.base)
            if base_storage:
                field_path = f"{base_storage}_{expr.field}"
                resolved = self.ctx.resolve_storage(field_path)

                # 检查字段类型
                field_type = expr._type
                if field_type.kind == 'prim' and field_type.name == 'string':
                    return [self.builder.data_copy_storage(target_var, resolved)]
                else:
                    return [self.builder.copy_score(target_var, resolved)]
            return []

        # 情况3：实体 NBT 嵌套访问（包括嵌套如 pos.x）
        if getattr(expr, '_is_entity_attr', False):
            # 获取实体选择器
            selector = self._get_entity_selector(expr.base)
            if not selector:
                selector = "@s"

            nbt_path = getattr(expr, '_nbt_path', expr.field)
            field_type = getattr(expr, '_type', FLOAT)

            # === 新增：字符串类型特殊处理 ===
            if field_type.kind == 'prim' and field_type.name == 'string':
                # target_var 对于字符串应该是 storage 路径
                return self.entity_gen.gen_entity_read_string(
                    expr, target_var, selector, nbt_path
                )

            # 数值类型处理（原有逻辑）
            scale = "100" if field_type == FLOAT or field_type.name == 'float' else "1"
            return [
                f"execute store result score {target_var} _tmp run "
                f"data get entity {selector} {nbt_path} {scale}"
            ]

        return []

    def _get_base_name(self, expr) -> Optional[str]:
        """从表达式中提取基础变量名"""
        if isinstance(expr, Ident):
            return expr.name
        elif isinstance(expr, FieldAccess):
            return self._get_base_name(expr.base)
        return None

    def _get_storage_path(self, expr) -> Optional[str]:
        """递归构建storage路径（用于struct字段链）"""
        if isinstance(expr, Ident):
            storage, _ = self.ctx.get_var(expr.name)
            return self.ctx.resolve_storage(storage)
        elif isinstance(expr, FieldAccess):
            base = self._get_storage_path(expr.base)
            if base:
                return f"{base}_{expr.field}"
        return None

    def _get_entity_selector(self, expr) -> Optional[str]:
        """从表达式中提取实体选择器"""
        if isinstance(expr, SelectorExpr):
            return expr.raw
        elif isinstance(expr, Ident):
            storage, var_type = self.ctx.get_var(expr.name)
            if var_type.kind == 'entity':
                if isinstance(storage, str) and storage.startswith('@'):
                    return storage
                return "@s"
        elif isinstance(expr, FieldAccess):
            # 递归查找最底层的实体
            return self._get_entity_selector(expr.base)
        return None