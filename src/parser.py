from ply import yacc

from ply import yacc
from ast_nodes import *
from lexer import lexer, tokens

start = 'program'

precedence = (
    ('left', 'AND'),      # 逻辑与，较低优先级
    ('nonassoc', 'EQ', 'NE'),  # ==, !=
    ('nonassoc', 'LT', 'GT', 'LE', 'GE'),  # <, >, <=, >=
    ('left', 'PLUS', 'MINUS'),
    ('left', 'TIMES', 'DIV', 'MOD'),
    ('right', 'UMINUS'),
    ('left', 'DOT'),      # 点号，高优先级（应该在 AND 之后）
    ('left', '['),        # 数组索引，高优先级
)


# ==================== 程序结构 ====================

def p_program(p):
    "program : stmt_list"
    p[0] = Program(p[1])

def p_stmt_list_multi(p):
    "stmt_list : stmt_list stmt"
    p[0] = p[1] + [p[2]]

def p_expr_and(p):
    """expr : expr AND expr"""
    p[0] = BinOp('and', p[1], p[3])

def p_stmt_list_single(p):
    "stmt_list : stmt"
    p[0] = [p[1]]

def p_stmt(p):
    """stmt : decorated_func
            | static_tag_decl
            | func_decl
            | let_stmt
            | assign_stmt
            | struct_decl
            | for_stmt
            | while_stmt
            | if_stmt
            | return_stmt
            | expr_stmt
            | cmd_stmt
            | condition_stmt
            | loot_stmt
            | import_stmt"""
    p[0] = p[1]

# ==================== 装饰器系统 ====================

def p_decorated_func(p):
    """decorated_func : decorators func_decl"""
    p[2].annotations = p[1]
    p[0] = p[2]

def p_decorators_multi(p):
    """decorators : decorators decorator"""
    p[0] = p[1] + [p[2]]

def p_decorators_single(p):
    """decorators : decorator"""
    p[0] = [p[1]]

# $tag("path") - tag 是关键字 TAG，不是 IDENT
def p_decorator_tag(p):
    """decorator : DOLLAR TAG '(' STRING ')'"""
    p[0] = TagAnnot(path=p[4])

# $predicate("path"), $loot("path")
def p_decorator_string_arg(p):
    """decorator : DOLLAR IDENT '(' STRING ')'
                 | DOLLAR LOOT '(' STRING ')'"""  # ← 添加这一行
    name = p[2] if p.slice[2].type == 'IDENT' else 'loot'
    path = p[4]
    if name == 'predicate':
        p[0] = PredicateAnnot(path=path)
    elif name == 'loot':
        p[0] = LootAnnot(path=path)
    else:
        p[0] = ('unknown_decorator', name, path)

def p_decorator_tick(p):
    """decorator : DOLLAR IDENT '(' INT ')'"""
    if p[2] == 'tick':
        p[0] = TickAnnot(interval=p[4])
    else:
        raise SyntaxError(f"Line {p.lineno(2)}: Decorator ${p[2]} does not accept integer argument")

def p_decorator_event(p):
    """decorator : DOLLAR IDENT '(' STRING ',' primary ')'"""
    if p[2] == 'event':
        p[0] = EventAnnot(trigger=p[4], conditions=p[6])
    else:
        raise SyntaxError(f"Line {p.lineno(2)}: Decorator ${p[2]} does not accept (string, object) arguments")

# ==================== 静态标签声明 ====================
# $tag function("path") { ... }  或  $tag entity("path") { ... }

def p_static_tag_decl(p):
    """static_tag_decl : DOLLAR TAG tag_type '(' STRING ')' '{' tag_entries '}'"""
    p[0] = StaticTagDecl(tag_type=p[3], path=p[5], entries=p[8])

def p_tag_type(p):
    """tag_type : IDENT
                | ENTITY"""
    p[0] = p[1]

def p_tag_entries_empty(p):
    """tag_entries : """
    p[0] = []

# 新增：支持 STRING 或 IDENT 作为条目
def p_tag_entry_string(p):
    """tag_entry : STRING"""
    p[0] = p[1]

def p_tag_entry_ident(p):
    """tag_entry : IDENT"""
    p[0] = p[1]

def p_tag_entries_list_multi(p):
    """tag_entries : tag_entries ',' tag_entry"""
    p[0] = p[1] + [p[3]]

def p_tag_entries_list_single(p):
    """tag_entries : tag_entry"""
    p[0] = [p[1]]

# ==================== Predicate 条件语句 ====================

def p_condition_stmt(p):
    """condition_stmt : CONDITION '{' condition_clauses '}'"""
    p[0] = ConditionStmt(clauses=p[3])

def p_condition_clauses_multi(p):
    """condition_clauses : condition_clauses condition_clause"""
    p[0] = p[1] + [p[2]]

def p_condition_clauses_single(p):
    """condition_clauses : condition_clause"""
    p[0] = [p[1]]

def p_condition_clause_entity(p):
    """condition_clause : ENTITY primary '{' field_assign_list '}'"""
    p[0] = EntityCondition(selector=p[2], nbt=ObjectLiteral(p[4]))

def p_condition_clause_entity_simple(p):
    """condition_clause : ENTITY primary primary"""
    p[0] = EntityCondition(selector=p[2], nbt=p[3])

# ==================== 原有语句规则 ====================

def p_let_no_type(p):
    "let_stmt : LET IDENT '=' expr"
    p[0] = LetStmt(p[2], None, p[4])

def p_let_with_type(p):
    "let_stmt : LET IDENT ':' type '=' expr"
    p[0] = LetStmt(p[2], p[4], p[6])

def p_assign(p):
    "assign_stmt : expr '=' expr"
    p[0] = AssignStmt(p[1], p[3])

def p_struct_decl(p):
    "struct_decl : STRUCT IDENT '{' field_list '}'"
    p[0] = StructDecl(p[2], p[4])

def p_field_list_multi(p):
    "field_list : field_list ',' field"
    p[0] = p[1] + [p[3]]

def p_field_list_single(p):
    "field_list : field"
    p[0] = [p[1]]

def p_field(p):
    "field : IDENT ':' type"
    p[0] = (p[1], p[3])

def p_func_decl(p):
    "func_decl : FN IDENT '(' param_list_opt ')' ret_opt block"
    p[0] = FuncDecl(p[2], p[4], p[6], p[7], [])

def p_param_list_opt_multi(p):
    "param_list_opt : param_list"
    p[0] = p[1]

def p_param_list_opt_empty(p):
    "param_list_opt : "
    p[0] = []

def p_param_list_multi(p):
    "param_list : param_list ',' param"
    p[0] = p[1] + [p[3]]

def p_param_list_single(p):
    "param_list : param"
    p[0] = [p[1]]

def p_param(p):
    "param : IDENT ':' type"
    p[0] = (p[1], p[3])

def p_ret_opt_with_type(p):
    "ret_opt : ARROW type"
    p[0] = p[2]

def p_ret_opt_empty(p):
    "ret_opt : "
    p[0] = None

def p_type(p):
    "type : type_base type_dims"
    p[0] = TypeNode(p[1], dims=p[2])

def p_type_base_int(p):
    "type_base : INT_TYPE"
    p[0] = 'int'

def p_type_base_string(p):
    "type_base : STRING_TYPE"
    p[0] = 'string'

def p_type_base_entity(p):
    "type_base : ENTITY"
    p[0] = 'entity'

def p_type_base_ident(p):
    "type_base : IDENT"
    p[0] = p[1]

def p_type_dims_multi_fixed(p):
    "type_dims : type_dims '[' INT ']'"
    p[0] = p[1] + [p[3]]

def p_type_dims_multi_empty(p):
    "type_dims : type_dims '[' ']'"
    p[0] = p[1] + [None]

def p_type_dims_empty(p):
    "type_dims : "
    p[0] = []

def p_return_with_value(p):
    "return_stmt : RETURN expr"
    p[0] = ReturnStmt(p[2])

def p_return_empty(p):
    "return_stmt : RETURN"
    p[0] = ReturnStmt(None)

def p_for_range(p):
    "for_stmt : FOR IDENT IN expr DOTDOT expr block"
    p[0] = ForStmt(p[2], p[4], p[7], is_range=True, range_end=p[6])

def p_for_each(p):
    "for_stmt : FOR IDENT IN expr block"
    p[0] = ForStmt(p[2], p[4], p[5], is_range=False)

def p_while_stmt(p):
    "while_stmt : WHILE expr block"
    p[0] = WhileStmt(p[2], p[3])

def p_if_stmt(p):
    "if_stmt : IF expr block else_opt"
    p[0] = IfStmt(p[2], p[3], p[4])

def p_else_opt_with_block(p):
    "else_opt : ELSE block"
    p[0] = p[2]

def p_else_opt_empty(p):
    "else_opt : "
    p[0] = []

def p_block_with_stmts(p):
    "block : '{' stmt_list '}'"
    p[0] = p[2]

def p_block_empty(p):
    "block : '{' '}'"
    p[0] = []

# ==================== 表达式规则 ====================

def p_expr_comparison(p):
    """expr : expr LT expr
            | expr GT expr
            | expr LE expr
            | expr GE expr
            | expr EQ expr
            | expr NE expr"""
    p[0] = BinOp(p[2], p[1], p[3])

def p_expr_binop(p):
    """expr : expr PLUS expr
            | expr MINUS expr
            | expr TIMES expr
            | expr DIV expr
            | expr MOD expr"""
    p[0] = BinOp(p[2], p[1], p[3])

def p_expr_index(p):
    '''expr : expr '[' expr ']' '''
    p[0] = IndexExpr(p[1], p[3])

def p_expr_field(p):
    "expr : expr DOT IDENT"
    p[0] = FieldAccess(p[1], p[3])

def p_expr_call(p):
    "expr : primary '(' arg_list_opt ')'"
    p[0] = CallExpr(p[1], p[3])

def p_expr_primary(p):
    "expr : primary"
    p[0] = p[1]

def p_arg_list_opt_multi(p):
    "arg_list_opt : arg_list"
    p[0] = p[1]

def p_arg_list_opt_empty(p):
    "arg_list_opt : "
    p[0] = []

def p_arg_list_multi(p):
    "arg_list : arg_list ',' expr"
    p[0] = p[1] + [p[3]]

def p_arg_list_single(p):
    "arg_list : expr"
    p[0] = [p[1]]

def p_primary_object_literal(p):
    "primary : '{' field_assign_list '}'"
    p[0] = ObjectLiteral(p[2])

def p_field_assign_list_multi(p):
    "field_assign_list : field_assign_list ',' field_assign"
    p[0] = p[1] + [p[3]]

def p_field_assign_list_single(p):
    "field_assign_list : field_assign"
    p[0] = [p[1]]

def p_field_assign_list_empty(p):
    "field_assign_list : "
    p[0] = []

def p_field_assign(p):
    """field_assign : field_key ':' expr"""
    p[0] = (p[1], p[3])

def p_field_key_ident(p):
    """field_key : IDENT"""
    p[0] = p[1]

def p_field_key_entity(p):
    """field_key : ENTITY"""
    p[0] = p[1]

def p_field_key_tag(p):
    """field_key : TAG"""
    p[0] = p[1]

def p_field_key_condition(p):
    """field_key : CONDITION"""
    p[0] = p[1]

# ==================== 基础 Primary 规则 ====================

def p_primary_int(p):
    "primary : INT"
    p[0] = IntLiteral(p[1])

def p_primary_float(p):
    "primary : FLOAT"
    p[0] = FloatLiteral(p[1])

def p_primary_true(p):
    "primary : TRUE"
    p[0] = BoolLiteral(True)

def p_primary_false(p):
    "primary : FALSE"
    p[0] = BoolLiteral(False)

def p_primary_string(p):
    "primary : STRING"
    p[0] = StringLiteral(p[1])

def p_primary_ident(p):
    "primary : IDENT"
    p[0] = Ident(p[1])

def p_primary_selector(p):
    "primary : SELECTOR"
    p[0] = SelectorExpr(p[1])

def p_primary_paren(p):
    "primary : '(' expr ')'"
    p[0] = p[2]

def p_primary_array(p):
    "primary : array_literal"
    p[0] = p[1]

def p_array_literal_multi(p):
    "array_literal : '[' expr_list ']'"
    p[0] = ArrayLiteral(p[2])

def p_array_literal_empty(p):
    "array_literal : '[' ']'"
    p[0] = ArrayLiteral([])

def p_expr_list_multi(p):
    "expr_list : expr_list ',' expr"
    p[0] = p[1] + [p[3]]

def p_expr_list_single(p):
    "expr_list : expr"
    p[0] = [p[1]]

def p_expr_stmt(p):
    "expr_stmt : expr"
    p[0] = ExprStmt(p[1])

def p_cmd_stmt(p):
    "cmd_stmt : CMD STRING"
    p[0] = CmdStmt(p[2])

def p_loot_stmt(p):
    """loot_stmt : LOOT STRING"""
    p[0] = LootConfigStmt(p[2])

def p_expr_uminus(p):
    "expr : MINUS expr %prec UMINUS"
    p[0] = UnaryOp('-', p[2])

def p_error(p):
    if p:
        print(f"Syntax error at '{p.value}' (type: {p.type}) on line {p.lineno}")
    else:
        print("Syntax error at EOF")

def parse(data, debug=False):
    parser = yacc.yacc(debug=debug, write_tables=False)
    return parser.parse(data, lexer=lexer)

# ==================== Import 系统 ====================

def p_import_all(p):
    """import_stmt : IMPORT STRING"""
    p[0] = ImportStmt(module=p[2], names=None)

def p_import_selective(p):
    """import_stmt : IMPORT '{' id_list '}' FROM STRING"""
    p[0] = ImportStmt(module=p[6], names=p[3])

def p_id_list_multi(p):
    """id_list : id_list ',' IDENT"""
    p[0] = p[1] + [p[3]]

def p_id_list_single(p):
    """id_list : IDENT"""
    p[0] = [p[1]]