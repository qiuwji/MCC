from typing import Dict, List

from annotation_processor import AnnotationProcessor, AnnotationResult
from ast_nodes import Program, FuncDecl, StructDecl, IfStmt, ReturnStmt, StaticTagDecl
from command_builder import CommandBuilder
from context import GeneratorContext
from stmt_generator import StmtGenerator


class CodeGenerator:

    def __init__(self, namespace: str = "mcc", structs=None):
        self.builder = CommandBuilder(namespace)
        self.namespace = namespace
        self.ctx = GeneratorContext(namespace, structs or {})
        self.stmt_gen = StmtGenerator(self.ctx, self.builder)
        self.block_counter = 0
        self.annotation_result: AnnotationResult = None  # 新增：存储注解处理结果

    def get_storage_name(self, var_name: str, is_param: bool = False) -> str:
        return self.ctx.get_storage_name(var_name, is_param)

    def resolve_storage(self, storage: str) -> str:
        return self.ctx.resolve_storage(storage)

    def push_block(self) -> int:
        return self.ctx.push_block()

    def pop_block(self):
        vars_to_clean = self.ctx.pop_block()
        for var_name, storage in vars_to_clean:
            if self.ctx.current_mcfunc:
                self.ctx.current_mcfunc.add(self.builder.set_score(storage, "_tmp", 0))
            if var_name in self.ctx.var_map:
                del self.ctx.var_map[var_name]

    def emit(self, cmd: str):
        if self.ctx.current_mcfunc:
            if '$(' in cmd and not cmd.startswith('$'):
                cmd = '$' + cmd
            self.ctx.current_mcfunc.add(cmd)

    def emit_global_init(self, cmd: str):
        self.ctx.global_inits.append(cmd)

    def generate(self, program: Program) -> Dict[str, List[str]]:
        """主生成入口 - 集成注解处理器"""
        self.ctx.param_substitutions.clear()
        self.ctx.struct_params.clear()
        self.ctx.array_lengths.clear()

        processor = AnnotationProcessor(self.namespace)
        self.annotation_result = processor.process_program(program)

        for timer in self.annotation_result.tick_timers:
            var_name = timer['timer_var']
            self.ctx.global_inits.append(f"scoreboard players set {var_name} _tmp 0")

        self._collect_functions(program)

        load_func = self.builder.new_function("__init__", is_load=True)

        load_func.extend(self.builder.generate_init_commands())

        load_func.add("scoreboard players set _const100 _tmp 100")

        load_func.extend(self.ctx.global_inits)

        main_func = self.builder.new_function("main")
        self.ctx.current_mcfunc = main_func

        for stmt in program.stmts:
            if isinstance(stmt, (FuncDecl, StructDecl, StaticTagDecl)):
                continue
            self.stmt_gen.gen_stmt(stmt, main_func)

        for stmt in program.stmts:
            if isinstance(stmt, FuncDecl):
                # 跳过不生成函数体的（$loot, $predicate）
                if stmt.name not in self.annotation_result.skip_function_body:
                    self._gen_func_decl(stmt)

        result = {}

        for name, func in self.builder.functions.items():
            if func.is_load:
                result[f"data/{self.namespace}/functions/__init__.mcfunction"] = func.commands
            elif func.is_tick:
                result[f"data/{self.namespace}/functions/__tick__.mcfunction"] = func.commands
            else:
                result[f"data/{self.namespace}/functions/{name}.mcfunction"] = func.commands

        result[f"data/minecraft/tags/functions/load.json"] = {
            "values": [f"{self.namespace}:__init__"]
        }

        if self.annotation_result.tick_timers:
            tick_commands = []
            for timer in self.annotation_result.tick_timers:
                func_name = timer['func_name']
                var_name = timer['timer_var']
                interval = timer['interval']

                tick_commands.append(
                    f"execute if score {var_name} _tmp matches 0 "
                    f"run function {self.namespace}:fn_{func_name}"
                )

                tick_commands.append(f"scoreboard players add {var_name} _tmp 1")

                tick_commands.append(
                    f"execute if score {var_name} _tmp matches {interval}.. "
                    f"run scoreboard players set {var_name} _tmp 0"
                )

            # 合并或创建 __tick__.mcfunction
            tick_path = f"data/{self.namespace}/functions/__tick__.mcfunction"
            if tick_path in result:
                # 已存在（可能是用户自定义的 __tick__ 或 while true 生成的），追加到开头
                result[tick_path] = tick_commands + result[tick_path]
            else:
                result[tick_path] = tick_commands

            # 确保 tick.json 包含 __tick__
            tick_tag_path = "data/minecraft/tags/functions/tick.json"
            if tick_tag_path not in self.annotation_result.extra_files:
                self.annotation_result.extra_files[tick_tag_path] = {"values": []}

            tick_values = self.annotation_result.extra_files[tick_tag_path].setdefault("values", [])
            if f"{self.namespace}:__tick__" not in tick_values:
                tick_values.append(f"{self.namespace}:__tick__")

        tick_mcfunction_path = f"data/{self.namespace}/functions/__tick__.mcfunction"
        if tick_mcfunction_path in result:
            tick_tag_path = "data/minecraft/tags/functions/tick.json"
            # 确保 tick.json 存在
            if tick_tag_path not in self.annotation_result.extra_files:
                self.annotation_result.extra_files[tick_tag_path] = {"values": []}

            # 确保 __tick__ 在 values 中（避免重复）
            tick_values = self.annotation_result.extra_files[tick_tag_path].setdefault("values", [])
            tick_entry = f"{self.namespace}:__tick__"
            if tick_entry not in tick_values:
                tick_values.append(tick_entry)

        # ========== 第7步：合并注解处理器生成的 JSON 文件 ==========
        for path, content in self.annotation_result.extra_files.items():
            # content 是 dict，write_datapack 会处理 JSON 序列化
            result[path] = content

        # ========== 第8步：添加数组操作宏函数 ==========
        self._add_array_macros(result)

        return result

    def _collect_functions(self, program: Program):
        """收集结构体和函数签名"""
        for stmt in program.stmts:
            if isinstance(stmt, StructDecl):
                fields = {}
                for fname, ftype_node in stmt.fields:
                    fields[fname] = self._type_from_typenode(ftype_node)
                self.ctx.structs[stmt.name] = fields
            elif isinstance(stmt, FuncDecl):
                param_list = []
                for pname, ptype_node in stmt.params:
                    param_list.append((pname, self._type_from_typenode(ptype_node)))
                ret = self._type_from_typenode(stmt.ret_type) if stmt.ret_type else None
                self.ctx.funcs[stmt.name] = (param_list, ret, stmt)

    def _gen_func_decl(self, stmt: FuncDecl):
        """生成函数定义 - 支持 $event 的 revoke 注入"""
        func_name = stmt.name
        self.ctx.current_function = func_name

        mcfunc = self.builder.new_function(f"fn_{func_name}")
        self.ctx.current_mcfunc = mcfunc

        # 处理参数（保持原有逻辑）
        self.ctx.struct_params.clear()
        self.ctx.param_substitutions.clear()
        self.ctx.current_macro_args.clear()

        func_info = self.ctx.funcs[func_name]
        params, ret_type, _ = func_info
        for pname, ptype in params:
            if ptype.kind == 'struct':
                self.ctx.struct_params[pname] = f"$({pname})"
                self.ctx.current_macro_args[pname] = f"$({pname})"
                # ========== 关键修复：为结构体参数添加变量声明 ==========
                storage = self.ctx.get_storage_name(pname, is_param=True)
                self.ctx.add_var(pname, storage, ptype)
                # =====================================================
            elif ptype.kind == 'entity':
                self.ctx.add_var(pname, "@s", ptype)
            elif ptype.kind == 'array':
                storage = self.ctx.get_storage_name(pname, is_param=True)
                self.ctx.param_substitutions[storage] = f"$({pname})"
                self.ctx.current_macro_args[pname] = f"$({pname})"
                self.ctx.add_var(pname, storage, ptype)
            else:
                storage = self.ctx.get_storage_name(pname, is_param=True)
                self.ctx.add_var(pname, storage, ptype)

        self.ctx.push_block()

        # ========== $event 函数注入 revoke ==========
        if func_name in self.annotation_result.event_functions:
            self.emit(f"advancement revoke @s only minecraft:{self.namespace}/{func_name}")

        # 关键逻辑：处理 if-return 模式，自动转换为 if-else
        i = 0
        while i < len(stmt.body):
            s = stmt.body[i]
            # 检测：if 语句，then 块以 return 结尾，且没有 else 块
            if (isinstance(s, IfStmt) and
                    s.then_block and
                    isinstance(s.then_block[-1], ReturnStmt) and
                    not s.else_block and
                    i + 1 < len(stmt.body)):

                # 将 if 语句之后的所有语句收集为 else 块
                else_stmts = stmt.body[i + 1:]
                # 截断 body，只保留到 if 语句（包含）
                remaining_body = stmt.body[:i + 1]

                # 修改 if 语句，添加 else 块
                s.else_block = else_stmts

                # 生成修改后的 if 语句
                self.stmt_gen.gen_stmt(s, mcfunc)

                # 跳过已处理的语句
                break
            else:
                self.stmt_gen.gen_stmt(s, mcfunc)
                i += 1

        self._gen_cleanup()
        self.ctx.pop_block()
        self.ctx.current_macro_args.clear()
        self.ctx.current_function = None

    def _gen_cleanup(self):
        """生成函数退出时的清理代码"""
        func_prefix = f"{self.ctx.current_function}_"
        vars_to_clean = []

        for var_name, (storage, var_type) in list(self.ctx.var_map.items()):
            if var_name in self.ctx.struct_params:
                continue
            if not storage.startswith(func_prefix):
                continue

            if var_type.kind == 'struct':
                if var_type.name in self.ctx.structs:
                    for fname, ftype in self.ctx.structs[var_type.name].items():
                        if ftype.is_value_type():
                            self.emit(self.builder.set_score(f"{storage}_{fname}", "_tmp", 0))
                        elif ftype.kind == 'array':
                            self.emit(self.builder.set_score(f"{storage}_{fname}_len", "_tmp", 0))
                if var_name in self.ctx.var_map:
                    del self.ctx.var_map[var_name]
            elif var_type.kind == 'array':
                self.emit(self.builder.set_score(f"{storage}_len", "_tmp", 0))
                if var_name in self.ctx.var_map:
                    del self.ctx.var_map[var_name]
            elif var_type.kind == 'prim':
                vars_to_clean.append((var_name, storage))

        for var_name, storage in vars_to_clean:
            self.emit(self.builder.set_score(storage, "_tmp", 0))
            if var_name in self.ctx.var_map:
                del self.ctx.var_map[var_name]

    def _type_from_typenode(self, tn):
        """从 AST TypeNode 转换为 TypeDesc"""
        from semant import TypeDesc, INT, STRING, BOOL, FLOAT, VOID
        if tn is None:
            return VOID
        base = tn.base
        dims = tn.dims if hasattr(tn, 'dims') else []

        if base == 'int':
            base_t = INT
        elif base == 'string':
            base_t = STRING
        elif base == 'bool':
            base_t = BOOL
        elif base == 'float':
            base_t = FLOAT
        elif base == 'entity':
            base_t = TypeDesc('entity')
        else:
            base_t = TypeDesc('struct', name=base)

        if not dims:
            return base_t

        t = base_t
        for _ in reversed(dims):
            t = TypeDesc('array', elem=t)
        return t

    def _add_array_macros(self, result: Dict[str, List[str]]):
        """添加数组操作宏函数"""
        ns = self.namespace
        macros = {
            f"data/{ns}/functions/__array_get.mcfunction": [
                f"$execute store result score $(target) _tmp run data get storage {ns}:data $(path)[$(index)]"
            ],
            f"data/{ns}/functions/__array_set.mcfunction": [
                f"$execute store result storage {ns}:data $(path)[$(index)] $(type) 1 run scoreboard players get $(value) _tmp"
            ],
            f"data/{ns}/functions/__array_get_field.mcfunction": [
                f"$execute store result score $(target) _tmp run data get storage {ns}:data $(path)[$(index)].$(field)"
            ],
            f"data/{ns}/functions/__array_set_field.mcfunction": [
                f"$execute store result storage {ns}:data $(path)[$(index)].$(field) $(type) 1 run scoreboard players get $(value) _tmp"
            ],
            f"data/{ns}/functions/__array_copy_field.mcfunction": [
                f"$data modify storage {ns}:data $(target) set from storage {ns}:data $(path)[$(index)].$(field)"
            ],
            f"data/{ns}/functions/__array_get_string.mcfunction": [
                f"$data modify storage {ns}:data $(target) set from storage {ns}:data $(path)[$(index)]"
            ],
            f"data/{ns}/functions/__array_set_string.mcfunction": [
                f"$data modify storage {ns}:data $(path)[$(index)] set from storage {ns}:data $(source)"
            ],
            f"data/{ns}/functions/__array_set_struct.mcfunction": [
                f"$data modify storage {ns}:data $(path)[$(index)] set from storage {ns}:data $(source)"
            ],
        }
        result.update(macros)