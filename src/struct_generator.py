from ast_nodes import *
from command_builder import CommandBuilder
from context import GeneratorContext
from my_types import TypeDesc


class StructGenerator:
    def __init__(self, ctx: GeneratorContext, builder: CommandBuilder):
        self.ctx = ctx
        self.builder = builder

    def gen_struct_init(self, expr, target_base: str, struct_name: str) -> List[str]:
        cmds = []
        fields = self.ctx.structs.get(struct_name, {})
        fields_dict = self._extract_fields(expr)

        for fname, ftype in fields.items():
            field_target = f"{target_base}_{fname}"
            if fname in fields_dict:
                cmds.extend(self._init_field(field_target, ftype, fields_dict[fname]))
            else:
                cmds.extend(self._init_default(field_target, ftype))
        return cmds

    def gen_struct_init_storage(self, expr, target_path: str, struct_name: str) -> List[str]:
        """生成将结构体初始化到 storage 路径的命令（用于数组元素初始化）"""
        cmds = []
        fields = self.ctx.structs.get(struct_name, {})
        fields_dict = self._extract_fields(expr)

        # 初始化空 compound
        cmds.append(f'data modify storage {self.ctx.namespace}:data {target_path} set value {{}}')

        for fname, ftype in fields.items():
            field_target = f"{target_path}.{fname}"
            if fname in fields_dict:
                cmds.extend(self._init_field_storage(field_target, ftype, fields_dict[fname]))
            else:
                cmds.extend(self._init_default_storage(field_target, ftype))
        return cmds

    def gen_struct_copy(self, target_base: str, source_base: str,
                        struct_name: str) -> List[str]:
        cmds = []
        fields = self.ctx.structs.get(struct_name, {})
        for fname, ftype in fields.items():
            if ftype.kind == 'prim' and ftype.name == 'string':
                # 字符串字段：storage to storage
                cmds.append(self.builder.data_copy_storage(
                    f"{target_base}_{fname}",
                    f"{source_base}_{fname}"
                ))
            elif ftype.is_value_type():
                cmds.append(self.builder.copy_score(
                    f"{target_base}_{fname}",
                    f"{source_base}_{fname}"
                ))
            elif ftype.kind == 'array':
                cmds.append(self.builder.copy_score(
                    f"{target_base}_{fname}_len",
                    f"{source_base}_{fname}_len"
                ))
        return cmds

    def _extract_fields(self, expr) -> dict:
        if isinstance(expr, CallExpr) and expr.args:
            if isinstance(expr.args[0], ObjectLiteral):
                return {n: e for n, e in expr.args[0].fields}
        elif isinstance(expr, StructLiteral):
            return {n: e for n, e in expr.fields}
        elif isinstance(expr, ObjectLiteral):
            return {n: e for n, e in expr.fields}
        return {}

    def _init_field(self, target: str, ftype: TypeDesc, value) -> List[str]:
        if ftype.kind == 'prim' and ftype.name == 'string':
            if isinstance(value, StringLiteral):
                return [self.builder.data_set_storage(target, value.value)]
            else:
                from expr_generator import ExprGenerator
                expr_gen = ExprGenerator(self.ctx, self.builder, None)
                return expr_gen.gen_expr_to(value, target, ftype)
        elif ftype.is_value_type():
            from expr_generator import ExprGenerator
            expr_gen = ExprGenerator(self.ctx, self.builder, None)
            return expr_gen.gen_expr_to(value, target, ftype)
        elif ftype.kind == 'array' and isinstance(value, ArrayLiteral):
            return self._init_array_field(target, ftype, value)
        elif ftype.kind == 'struct':
            # === 处理嵌套结构体（如 pos: Vec3）===
            if isinstance(value, (StructLiteral, ObjectLiteral, CallExpr)):
                # 递归初始化嵌套结构体
                struct_name = ftype.name
                if isinstance(value, CallExpr) and value.args:
                    # 处理 Entity({...}) 这种包装形式
                    if isinstance(value.args[0], ObjectLiteral):
                        return self.gen_struct_init(value.args[0], target, struct_name)
                    return self.gen_struct_init(value, target, struct_name)
                elif isinstance(value, ObjectLiteral):
                    return self.gen_struct_init(value, target, struct_name)
                else:
                    return self.gen_struct_init(value, target, struct_name)
            else:
                # 默认值初始化（全0）
                return self._init_default(target, ftype)
        return []

    def _init_field_storage(self, target: str, ftype: TypeDesc, value) -> List[str]:
        """初始化字段到 storage 路径"""
        if ftype.kind == 'prim' and ftype.name == 'string':
            if isinstance(value, StringLiteral):
                return [self.builder.data_set_storage(target, value.value)]
            else:
                # 从变量复制（假设 value 是 Ident）
                if isinstance(value, Ident):
                    src_storage, _ = self.ctx.get_var(value.name)
                    src = self.ctx.resolve_storage(src_storage)
                    return [self.builder.data_copy_storage(target, src)]
                else:
                    # 表达式求值到临时路径
                    temp = f"__tmp_str_{self.builder.get_temp_var()}"
                    from expr_generator import ExprGenerator
                    expr_gen = ExprGenerator(self.ctx, self.builder, None)
                    cmds = expr_gen.gen_expr_to(value, temp, ftype)  # 传递 ftype
                    cmds.append(self.builder.data_copy_storage(target, temp))
                    return cmds
        elif ftype.is_value_type():
            # 数值类型：先算到 scoreboard，再存入 storage
            temp = self.builder.get_temp_var()
            from expr_generator import ExprGenerator
            expr_gen = ExprGenerator(self.ctx, self.builder, None)
            # 传递 ftype 触发 int->float 转换
            cmds = expr_gen.gen_expr_to(value, temp, ftype)
            type_str = "int" if ftype.name == 'int' else "double"
            scale = 1 if ftype.name == 'int' else 0.01
            cmds.append(
                f'execute store result storage {self.ctx.namespace}:data {target} {type_str} {scale} run scoreboard players get {temp} _tmp')
            return cmds
        elif ftype.kind == 'array':
            # 嵌套数组：递归初始化
            return [f'data modify storage {self.ctx.namespace}:data {target} set value []']
        return []

    def _init_default(self, target: str, ftype: TypeDesc) -> List[str]:
        if ftype.kind == 'prim' and ftype.name == 'string':
            return [self.builder.data_set_storage(target, "")]
        elif ftype.is_value_type():
            return [self.builder.set_score(target, "_tmp", 0)]
        elif ftype.kind == 'array':
            return [self.builder.set_score(f"{target}_len", "_tmp", 0)]
        return []

    def _init_default_storage(self, target: str, ftype: TypeDesc) -> List[str]:
        if ftype.kind == 'prim' and ftype.name == 'string':
            return [f'data modify storage {self.ctx.namespace}:data {target} set value ""']
        elif ftype.is_value_type():
            return [f'data modify storage {self.ctx.namespace}:data {target} set value 0']
        elif ftype.kind == 'array':
            return [f'data modify storage {self.ctx.namespace}:data {target} set value []']
        return []

    def _init_array_field(self, target: str, ftype: TypeDesc, arr: ArrayLiteral) -> List[str]:
        cmds = [self.builder.set_score(f"{target}_len", "_tmp", len(arr.items))]
        for i, item in enumerate(arr.items):
            temp = self.builder.get_temp_var()
            from expr_generator import ExprGenerator
            expr_gen = ExprGenerator(self.ctx, self.builder, None)
            cmds.extend(expr_gen.gen_expr_to(item, temp))
            cmds.append(self.builder.copy_score(f"{target}_{i}", temp))
        return cmds