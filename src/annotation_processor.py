"""
注解处理器 (Annotation Processor)
专门处理 $tag, $tick, $event, $predicate, $loot 的编译期逻辑
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Set

from ast_nodes import (
    FuncDecl, StaticTagDecl, TagAnnot, TickAnnot, EventAnnot,
    PredicateAnnot, LootAnnot, ConditionStmt, EntityCondition,
    ObjectLiteral, StringLiteral, BoolLiteral, IntLiteral, FloatLiteral, ArrayLiteral, LootConfigStmt
)
from semant import SemanticError


@dataclass
class AnnotationResult:
    """注解处理结果容器"""
    extra_files: Dict[str, Any] = field(default_factory=dict)  # 额外JSON文件 (advancements, predicates等)
    event_functions: Set[str] = field(default_factory=set)  # 需要注入revoke的函数名
    skip_function_body: Set[str] = field(default_factory=set)  # 不生成.mcfunction的函数 ($loot, $predicate)
    tick_timers: List[Dict[str, Any]] = field(default_factory=list)  # $tick(>1) 的计时器配置
    function_tags: Dict[str, List[str]] = field(default_factory=dict)  # 普通函数标签


class AnnotationProcessor:
    """注解处理器主类"""

    def __init__(self, namespace: str):
        self.namespace = namespace
        self.result = AnnotationResult()

    def process_program(self, program) -> AnnotationResult:
        """
        处理整个程序的所有注解
        返回 AnnotationResult 供 CodeGenerator 使用
        """
        for stmt in program.stmts:
            if isinstance(stmt, StaticTagDecl):
                self._process_static_tag(stmt)
            elif isinstance(stmt, FuncDecl) and stmt.annotations:
                # 单标签约束检查
                if len(stmt.annotations) > 1:
                    raise SemanticError(f"函数 {stmt.name} 声明了多个装饰器，当前仅支持单标签")
                self._process_annotated_func(stmt, stmt.annotations[0])

        return self.result

    def _process_static_tag(self, stmt: StaticTagDecl):
        """处理静态标签声明: $tag function("path") { "entries" }"""
        # path 格式: "namespace:path" 或 "path"
        path = stmt.path
        if ':' in path:
            ns, p = path.split(':', 1)
            # 静态声明遵循用户指定的命名空间，但强制存在 minecraft/tags/ 下
            file_path = f"data/minecraft/tags/{stmt.tag_type}/{p}.json"
        else:
            file_path = f"data/minecraft/tags/{stmt.tag_type}/{path}.json"

        # 规范化 entries 中的命名空间
        # 支持格式: "demo:init_part1" | "init_part1" | init_part1（裸标识符）
        normalized_entries = []
        for entry in stmt.entries:
            if not isinstance(entry, str):
                continue

            if ':' in entry:
                # 有命名空间前缀（如 "demo:init_part1"），替换为实际 namespace
                _, func_path = entry.split(':', 1)
                # 确保添加 fn_ 前缀
                if not func_path.startswith('fn_'):
                    func_path = f"fn_{func_path}"
                normalized_entries.append(f"{self.namespace}:{func_path}")
            else:
                # 没有命名空间前缀（裸标识符如 "init_part1" 或 init_part1）
                func_path = entry
                # 确保添加 fn_ 前缀
                if not func_path.startswith('fn_'):
                    func_path = f"fn_{func_path}"
                normalized_entries.append(f"{self.namespace}:{func_path}")

        # 合并到已有的 tag 文件
        if file_path in self.result.extra_files:
            # 已存在，合并 values（使用 set 去重）
            existing = self.result.extra_files[file_path].get("values", [])
            existing_set = set(existing)
            for entry in normalized_entries:
                existing_set.add(entry)
            # 排序保证输出稳定
            self.result.extra_files[file_path]["values"] = sorted(list(existing_set))
        else:
            self.result.extra_files[file_path] = {"values": normalized_entries}

    def _process_annotated_func(self, stmt: FuncDecl, ann):
        """单标签路由分发"""
        if isinstance(ann, TagAnnot):
            self._handle_tag(stmt.name, ann)
        elif isinstance(ann, TickAnnot):
            self._handle_tick(stmt.name, ann)
        elif isinstance(ann, EventAnnot):
            self._handle_event(stmt.name, ann)
        elif isinstance(ann, PredicateAnnot):
            self._handle_predicate(stmt, ann)
        elif isinstance(ann, LootAnnot):
            self._handle_loot(stmt, ann)
        else:
            raise SemanticError(f"未知的装饰器类型: {type(ann).__name__}")

    def _handle_tag(self, func_name: str, ann: TagAnnot):
        """$tag("namespace:path"): 将函数加入指定标签"""
        path = ann.path
        if ':' in path:
            ns, p = path.split(':', 1)
            file_path = f"data/minecraft/tags/function/{p}.json"
        else:
            file_path = f"data/minecraft/tags/function/{path}.json"

        if file_path not in self.result.extra_files:
            self.result.extra_files[file_path] = {"values": []}

        self.result.extra_files[file_path]["values"].append(f"{self.namespace}:fn_{func_name}")
        # 注意：$tag 仍需生成函数体，所以不加入 skip_function_body

    def _handle_tick(self, func_name: str, ann: TickAnnot):
        """$tick(interval): 注册定时执行"""
        interval = ann.interval

        if interval == 1:
            # 直接加入 tick.json
            tick_path = "data/minecraft/tags/functions/tick.json"
            if tick_path not in self.result.extra_files:
                self.result.extra_files[tick_path] = {"values": []}
            self.result.extra_files[tick_path]["values"].append(f"{self.namespace}:fn_{func_name}")
        else:
            # $tick(20) 等：生成计时器配置，由 CodeGenerator 生成包装逻辑
            self.result.tick_timers.append({
                'func_name': func_name,
                'interval': interval,
                'timer_var': f"__timer_{func_name}"
            })

    def _handle_event(self, func_name: str, ann: EventAnnot):
        """$event(trigger, conditions): 生成 Advancement JSON"""
        # 标记此函数需要在开头注入 advancement revoke
        self.result.event_functions.add(func_name)

        # 构建 Advancement JSON
        adv_data = {
            "criteria": {
                "trigger": {
                    "trigger": ann.trigger,
                    "conditions": self._convert_to_json(ann.conditions) if ann.conditions else {}
                }
            },
            "rewards": {
                "function": f"{self.namespace}:fn_{func_name}"
            }
        }

        # 强制使用 minecraft 命名空间
        file_path = f"data/minecraft/advancements/{self.namespace}/{func_name}.json"
        self.result.extra_files[file_path] = adv_data

    def _handle_predicate(self, stmt: FuncDecl, ann: PredicateAnnot):
        """$predicate("path"): 生成 Predicate JSON，不生成函数体"""
        # 验证：必须且只能包含一个 condition 语句
        if len(stmt.body) != 1 or not isinstance(stmt.body[0], ConditionStmt):
            raise SemanticError(f"$predicate 函数 {stmt.name} 必须且只能包含一个 condition {{...}} 语句")

        cond_stmt = stmt.body[0]
        predicate_json = self._build_predicate_json(cond_stmt.clauses)

        # 使用配置的命名空间
        file_path = f"data/{self.namespace}/predicates/{ann.path}.json"
        self.result.extra_files[file_path] = predicate_json

        # 标记跳过函数体生成
        self.result.skip_function_body.add(stmt.name)

    def _handle_loot(self, stmt: FuncDecl, ann: LootAnnot):
        """$loot("path"): 生成 Loot Table，支持函数体内定义 JSON"""
        import json

        loot_json = None

        # 查找函数体内的 loot 语句
        for s in stmt.body:
            if isinstance(s, LootConfigStmt):
                try:
                    loot_json = json.loads(s.json_content)
                    break
                except json.JSONDecodeError as e:
                    raise SemanticError(f"$loot 的 JSON 格式错误: {e}")

        # 如果没找到，使用默认配置
        if loot_json is None:
            loot_json = {
                "type": "generic",
                "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "minecraft:stone"}]}]
            }

        file_path = f"data/{self.namespace}/loot_tables/{ann.path}.json"
        self.result.extra_files[file_path] = loot_json
        self.result.skip_function_body.add(stmt.name)

    # ========== 辅助转换方法 ==========

    def _convert_to_json(self, obj) -> Any:
        """将 AST 对象转为 JSON 兼容结构"""
        if isinstance(obj, ObjectLiteral):
            return {k: self._convert_to_json(v) for k, v in obj.fields}
        elif isinstance(obj, (StringLiteral,)):
            return obj.value
        elif isinstance(obj, (IntLiteral, FloatLiteral)):
            return obj.value
        elif isinstance(obj, BoolLiteral):
            return obj.value
        elif isinstance(obj, ArrayLiteral):
            return [self._convert_to_json(item) for item in obj.items]
        elif isinstance(obj, list):
            return [self._convert_to_json(item) for item in obj]
        return obj

    def _build_predicate_json(self, clauses: list) -> dict:
        """将 ConditionStmt 的子句转为 Predicate JSON"""
        if not clauses:
            return {"condition": "minecraft:always_true"}

        terms = []
        for clause in clauses:
            if isinstance(clause, EntityCondition):
                term = {
                    "condition": "minecraft:entity_properties",
                    "entity": "this",
                    "predicate": self._convert_to_json(clause.nbt) if clause.nbt else {}
                }
                terms.append(term)
            # TODO: 可扩展其他条件类型 (block_state, damage 等)

        if len(terms) == 1:
            return terms[0]
        return {"condition": "minecraft:alternative", "terms": terms}